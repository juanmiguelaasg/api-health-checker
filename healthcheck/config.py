"""Load the YAML configuration: settings, endpoints and expectations."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ${VAR} or ${VAR:-default}
ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)
    if isinstance(value, dict):
        return {k: expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env(v) for v in value]
    return value


@dataclass
class Endpoint:
    name: str
    url: str
    raw_url: str = ""                      # before env expansion (used by the Postman export)
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    raw_headers: dict[str, str] = field(default_factory=dict)
    body: Any = None
    expected_status: list[int] = field(default_factory=lambda: [200])
    max_response_ms: int = 1000
    sla_target: float = 99.9
    schema: dict | None = None
    contains: list[str] = field(default_factory=list)
    timeout_seconds: float | None = None


@dataclass
class Settings:
    interval_seconds: int = 60
    timeout_seconds: float = 10.0
    retries: int = 2
    retry_delay_seconds: float = 1.0
    confirm_failures: int = 2
    escalate_after: int = 5
    history_file: Path = Path("data/history.json")
    history_limit: int = 5000
    status_page: Path = Path("site/index.html")
    webhook_url: str = ""
    escalation_webhook_url: str = ""


@dataclass
class Config:
    settings: Settings
    endpoints: list[Endpoint]
    path: Path


class ConfigError(ValueError):
    pass


def _status_list(value: Any) -> list[int]:
    if value is None:
        return [200]
    if isinstance(value, (int, str)):
        return [int(value)]
    return [int(v) for v in value]


def load_config(path: str | Path) -> Config:
    path = Path(path).resolve()
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    base = path.parent

    s_raw = expand_env(raw.get("settings") or {})
    alerts = s_raw.pop("alerts", {}) or {}
    settings = Settings(
        interval_seconds=int(s_raw.get("interval_seconds", 60)),
        timeout_seconds=float(s_raw.get("timeout_seconds", 10)),
        retries=int(s_raw.get("retries", 2)),
        retry_delay_seconds=float(s_raw.get("retry_delay_seconds", 1)),
        confirm_failures=max(1, int(s_raw.get("confirm_failures", 2))),
        escalate_after=int(s_raw.get("escalate_after", 5)),
        history_file=base / s_raw.get("history_file", "data/history.json"),
        history_limit=int(s_raw.get("history_limit", 5000)),
        status_page=base / s_raw.get("status_page", "site/index.html"),
        webhook_url=alerts.get("webhook_url", "") or "",
        escalation_webhook_url=alerts.get("escalation_webhook_url", "") or "",
    )

    endpoints: list[Endpoint] = []
    seen: set[str] = set()
    for i, item in enumerate(raw.get("endpoints") or []):
        if not isinstance(item, dict) or not item.get("name") or not item.get("url"):
            raise ConfigError(f"Endpoint #{i + 1}: 'name' and 'url' are required.")
        name = str(item["name"])
        if name in seen:
            raise ConfigError(f"Duplicate endpoint name: {name}")
        seen.add(name)

        schema = item.get("schema")
        if item.get("schema_file"):
            schema = json.loads((base / item["schema_file"]).read_text(encoding="utf-8"))

        expanded = expand_env(item)
        endpoints.append(Endpoint(
            name=name,
            url=expanded["url"],
            raw_url=item["url"],
            method=str(item.get("method", "GET")).upper(),
            headers={k: str(v) for k, v in (expanded.get("headers") or {}).items()},
            raw_headers={k: str(v) for k, v in (item.get("headers") or {}).items()},
            body=expanded.get("body"),
            expected_status=_status_list(item.get("expected_status")),
            max_response_ms=int(item.get("max_response_ms", 1000)),
            sla_target=float(item.get("sla_target", 99.9)),
            schema=schema,
            contains=[str(c) for c in item.get("contains") or []],
            timeout_seconds=item.get("timeout_seconds"),
        ))

    if not endpoints:
        raise ConfigError("No endpoints defined under 'endpoints'.")
    return Config(settings=settings, endpoints=endpoints, path=path)
