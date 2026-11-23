"""Result history and alert state persisted as JSON; availability / SLA calculations."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .checker import CheckResult

WINDOWS = {"24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400}


def default_state() -> dict:
    return {"consecutive_failures": 0, "alerting": False, "alerts_sent": 0, "escalations": 0, "down_since": None}


class History:
    def __init__(self, path: Path, limit: int = 5000):
        self.path = Path(path)
        self.limit = limit
        self.data: dict = {"endpoints": {}}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                # Corrupt file: move it aside and start fresh
                self.path.replace(self.path.with_suffix(".corrupt.json"))

    def _entry(self, name: str) -> dict:
        eps = self.data.setdefault("endpoints", {})
        return eps.setdefault(name, {"results": [], "state": default_state()})

    def record(self, result: CheckResult) -> None:
        results = self._entry(result.name)["results"]
        results.append(result.to_dict())
        if len(results) > self.limit:
            del results[: len(results) - self.limit]

    def add_event(self, kind: str, name: str, title: str, message: str) -> None:
        events = self.data.setdefault("events", [])
        events.append({"ts": time.time(), "kind": kind, "name": name, "title": title, "message": message})
        del events[:-500]

    def add_run(self, summary: dict) -> None:
        runs = self.data.setdefault("runs", [])
        runs.append(summary)
        del runs[:-2000]

    def events(self) -> list[dict]:
        return self.data.get("events", [])

    def runs(self) -> list[dict]:
        return self.data.get("runs", [])

    def results(self, name: str, since: float | None = None) -> list[dict]:
        res = self._entry(name)["results"]
        return res if since is None else [r for r in res if r["timestamp"] >= since]

    def state(self, name: str) -> dict:
        return self._entry(name)["state"]

    def uptime(self, name: str, window_seconds: int, now: float | None = None) -> float | None:
        res = self.results(name, since=(now or time.time()) - window_seconds)
        if not res:
            return None
        return 100.0 * sum(1 for r in res if r["ok"]) / len(res)

    def response_stats(self, name: str, window_seconds: int = 86400) -> dict:
        times = sorted(r["elapsed_ms"] for r in self.results(name, time.time() - window_seconds)
                       if r.get("elapsed_ms") is not None)
        if not times:
            return {"avg": None, "p95": None}
        p95 = times[min(len(times) - 1, int(round(0.95 * (len(times) - 1))))]
        return {"avg": sum(times) / len(times), "p95": p95}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)


def sla_report(config, history: History) -> list[dict]:
    rows = []
    for ep in config.endpoints:
        row = {"name": ep.name, "target": ep.sla_target}
        for label, secs in WINDOWS.items():
            row[label] = history.uptime(ep.name, secs)
        row["met"] = row["30d"] is None or row["30d"] >= ep.sla_target
        row.update(history.response_stats(ep.name))
        row["state"] = history.state(ep.name)
        rows.append(row)
    return rows
