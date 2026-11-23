"""Background thread for scheduled checks + immutable snapshots for the UI."""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Config, load_config
from ..history import History
from ..runner import Runner


@dataclass
class EndpointView:
    name: str
    method: str
    url: str
    expected_status: list[int]
    max_ms: int
    sla_target: float
    has_schema: bool
    contains: list[str]
    results: list[dict]
    state: dict
    up24: float | None
    up7: float | None
    up30: float | None
    avg: float | None
    p95: float | None

    @property
    def last(self) -> dict | None:
        return self.results[-1] if self.results else None

    @property
    def status(self) -> str:
        if not self.results:
            return "none"
        if self.state.get("alerting"):
            return "down"
        return "ok" if self.last["ok"] else "warn"

    @property
    def sla_met(self) -> bool:
        return self.up30 is None or self.up30 >= self.sla_target

    @property
    def error_budget(self) -> float | None:
        """Percent of the 30-day error budget left (negative = exceeded)."""
        allowed = 100.0 - self.sla_target
        if self.up30 is None or allowed <= 0:
            return None
        return (1 - (100.0 - self.up30) / allowed) * 100


@dataclass
class Snapshot:
    config_path: Path
    interval: int
    status_page: Path
    endpoints: list[EndpointView]
    events: list[dict]
    runs: list[dict]
    total_checks: int
    created: float = field(default_factory=time.time)

    @property
    def last_run(self) -> float | None:
        return self.runs[-1]["ts"] if self.runs else None


def build_snapshot(cfg: Config, history: History) -> Snapshot:
    views, total = [], 0
    for ep in cfg.endpoints:
        res = history.results(ep.name)
        total += len(res)
        stats = history.response_stats(ep.name)
        views.append(EndpointView(
            name=ep.name, method=ep.method, url=ep.url, expected_status=list(ep.expected_status),
            max_ms=ep.max_response_ms, sla_target=ep.sla_target, has_schema=ep.schema is not None,
            contains=list(ep.contains), results=list(res[-200:]), state=dict(history.state(ep.name)),
            up24=history.uptime(ep.name, 86400), up7=history.uptime(ep.name, 7 * 86400),
            up30=history.uptime(ep.name, 30 * 86400), avg=stats["avg"], p95=stats["p95"]))
    return Snapshot(config_path=cfg.path, interval=cfg.settings.interval_seconds,
                    status_page=cfg.settings.status_page, endpoints=views,
                    events=list(history.events()[-300:]), runs=list(history.runs()[-200:]),
                    total_checks=total)


class Monitor(threading.Thread):
    """All history/runner access happens on this thread.

    Outbox messages: ("snapshot", Snapshot) | ("busy", bool) | ("error", str)
    """

    def __init__(self, config_path: str | Path, enabled: bool = True) -> None:
        super().__init__(daemon=True, name="healthcheck-monitor")
        self.config_path = Path(config_path)
        self.outbox: queue.Queue = queue.Queue()
        self.enabled = enabled
        self.next_run = time.time()
        self.interval = 60
        self.busy = False
        self._wake = threading.Event()
        self._stop_event = threading.Event()
        self._force = False
        self._reload = True
        self.runner: Runner | None = None

    # -- control (called from the UI thread) ------------------------------------------------
    def run_now(self) -> None:
        self._force = True
        self._wake.set()

    def set_enabled(self, on: bool) -> None:
        self.enabled = on
        if on:
            self.next_run = time.time()
        self._wake.set()

    def reload(self) -> None:
        self._reload = True
        self._wake.set()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake.set()

    # -- thread -----------------------------------------------------------------
    def run(self) -> None:
        while not self._stop_event.is_set():
            if self._reload:
                self._reload = False
                try:
                    cfg = load_config(self.config_path)
                    self.runner = Runner(cfg)
                    self.interval = cfg.settings.interval_seconds
                    self.outbox.put(("snapshot", build_snapshot(cfg, self.runner.history)))
                except Exception as exc:  # noqa: BLE001
                    self.outbox.put(("error", f"Configuration: {exc}"))

            due = self.enabled and time.time() >= self.next_run
            if self.runner and (self._force or due):
                self._force = False
                self.busy = True
                self.outbox.put(("busy", True))
                try:
                    self.runner.run_once()
                    self.outbox.put(("snapshot", build_snapshot(self.runner.config, self.runner.history)))
                except Exception as exc:  # noqa: BLE001
                    self.outbox.put(("error", f"Run failed: {exc}"))
                finally:
                    self.busy = False
                    self.next_run = time.time() + self.interval
                    self.outbox.put(("busy", False))
            self._wake.wait(0.5)
            self._wake.clear()
