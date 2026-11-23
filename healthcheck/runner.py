"""One full run: check -> history -> alerting -> status page."""
from __future__ import annotations

import time
from xml.etree import ElementTree as ET

from .alerts import AlertManager
from .checker import CheckResult, run_checks
from .config import Config
from .history import History
from .statuspage import write_status_page


class Runner:
    def __init__(self, config: Config, alerts: bool = True):
        self.config = config
        self.history = History(config.settings.history_file, config.settings.history_limit)
        self.alerts = AlertManager(config.settings, self.history) if alerts else None

    def run_once(self) -> list[CheckResult]:
        results = run_checks(self.config)
        for ep, res in zip(self.config.endpoints, results):
            self.history.record(res)
            if self.alerts:
                self.alerts.process(ep, res)
        times = [r.elapsed_ms for r in results if r.elapsed_ms is not None]
        uptimes = [u for u in (self.history.uptime(ep.name, 86400) for ep in self.config.endpoints) if u is not None]
        self.history.add_run({
            "ts": time.time(),
            "ok": sum(1 for r in results if r.ok),
            "total": len(results),
            "avg_ms": sum(times) / len(times) if times else None,
            "uptime24": sum(uptimes) / len(uptimes) if uptimes else None,
        })
        self.history.save()
        write_status_page(self.config, self.history)
        return results


def write_junit(results: list[CheckResult], path) -> None:
    """JUnit XML for the Azure DevOps 'Publish Test Results' task."""
    failures = sum(1 for r in results if not r.ok)
    suite = ET.Element("testsuite", name="api-health-check", tests=str(len(results)),
                       failures=str(failures), errors="0",
                       time=f"{sum((r.elapsed_ms or 0) for r in results) / 1000:.3f}")
    for r in results:
        case = ET.SubElement(suite, "testcase", classname="healthcheck", name=r.name,
                             time=f"{(r.elapsed_ms or 0) / 1000:.3f}")
        if not r.ok:
            msg = "; ".join(r.errors)
            ET.SubElement(case, "failure", message=msg).text = (
                f"{msg}\nHTTP: {r.status}  Attempts: {r.attempts}")
    root = ET.Element("testsuites")
    root.append(suite)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
