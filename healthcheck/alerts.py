"""Alert only on confirmed failures, escalate repeated failures, notify on recovery."""
from __future__ import annotations

import logging
import time
from typing import Protocol

import requests

from .checker import CheckResult
from .config import Endpoint, Settings
from .history import History

log = logging.getLogger("healthcheck.alerts")


class Notifier(Protocol):
    def send(self, kind: str, title: str, message: str) -> None: ...


class ConsoleNotifier:
    def send(self, kind: str, title: str, message: str) -> None:
        print(f"[{kind}] {title}\n    {message}", flush=True)


class WebhookNotifier:
    """Teams / Slack / generic webhook with a {"text": "..."} payload."""

    def __init__(self, url: str, timeout: float = 10):
        self.url, self.timeout = url, timeout

    def send(self, kind: str, title: str, message: str) -> None:
        try:
            r = requests.post(self.url, json={"text": f"**[{kind}] {title}**\n\n{message}"}, timeout=self.timeout)
            r.raise_for_status()
        except requests.RequestException as exc:
            log.error("Webhook delivery failed (%s): %s", self.url, exc)


class AlertManager:
    def __init__(self, settings: Settings, history: History,
                 notifiers: list[Notifier] | None = None,
                 escalation_notifiers: list[Notifier] | None = None):
        self.settings = settings
        self.history = history
        self.notifiers = notifiers if notifiers is not None else build_notifiers(settings.webhook_url)
        self.escalation_notifiers = (escalation_notifiers if escalation_notifiers is not None
                                     else build_notifiers(settings.escalation_webhook_url, console=False))

    def _send(self, notifiers: list[Notifier], kind: str, title: str, message: str, name: str = "") -> None:
        self.history.add_event(kind, name, title, message)
        for n in notifiers:
            n.send(kind, title, message)

    def process(self, ep: Endpoint, result: CheckResult) -> str | None:
        """Update state; return the triggered event (ALERT / ESCALATION / RECOVERY) or None."""
        st = self.history.state(ep.name)
        if result.ok:
            event = None
            if st["alerting"]:
                down = time.time() - (st["down_since"] or time.time())
                self._send(self.notifiers, "RECOVERY", f"{ep.name} recovered",
                           f"{ep.url} is healthy again ({result.elapsed_ms:.0f} ms). Downtime ~{down / 60:.1f} min.",
                           ep.name)
                event = "RECOVERY"
            st.update(consecutive_failures=0, alerting=False, escalations=0, down_since=None)
            return event

        st["consecutive_failures"] += 1
        n = st["consecutive_failures"]
        if n == 1:
            st["down_since"] = result.timestamp
        details = "; ".join(result.errors)
        confirm, esc = self.settings.confirm_failures, self.settings.escalate_after

        if not st["alerting"] and n >= confirm:
            st["alerting"] = True
            st["alerts_sent"] += 1
            self._send(self.notifiers, "ALERT", f"{ep.name} is DOWN (confirmed, {n} consecutive failures)",
                       f"{ep.method} {ep.url}: {details}", ep.name)
            return "ALERT"

        if st["alerting"] and esc > 0 and n > confirm and (n - confirm) % esc == 0:
            st["escalations"] += 1
            targets = self.escalation_notifiers or self.notifiers
            self._send(targets, "ESCALATION",
                       f"{ep.name} still failing ({n} consecutive failures, escalation #{st['escalations']})",
                       f"{ep.method} {ep.url}: {details}", ep.name)
            return "ESCALATION"
        return None


def build_notifiers(webhook_url: str, console: bool = True) -> list[Notifier]:
    out: list[Notifier] = [ConsoleNotifier()] if console else []
    if webhook_url:
        out.append(WebhookNotifier(webhook_url))
    return out
