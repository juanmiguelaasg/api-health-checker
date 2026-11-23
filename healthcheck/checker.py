"""Check one endpoint: status code, response time, body and JSON schema, with retries."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Callable

import requests
from jsonschema.validators import validator_for

from .config import Config, Endpoint, Settings


@dataclass
class CheckResult:
    name: str
    timestamp: float
    ok: bool
    status: int | None
    elapsed_ms: float | None
    attempts: int
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate(ep: Endpoint, resp: requests.Response, elapsed_ms: float) -> list[str]:
    errors: list[str] = []
    if resp.status_code not in ep.expected_status:
        errors.append(f"Status {resp.status_code}, expected {ep.expected_status}")
    if elapsed_ms > ep.max_response_ms:
        errors.append(f"Response time {elapsed_ms:.0f} ms > limit {ep.max_response_ms} ms")
    for needle in ep.contains:
        if needle not in resp.text:
            errors.append(f"Body does not contain {needle!r}")
    if ep.schema is not None:
        try:
            data = resp.json()
        except ValueError:
            errors.append("Body is not valid JSON")
        else:
            validator = validator_for(ep.schema)(ep.schema)
            schema_errors = sorted(validator.iter_errors(data), key=lambda e: list(map(str, e.path)))
            for err in schema_errors[:5]:
                where = "/".join(map(str, err.path)) or "(root)"
                errors.append(f"Schema: {where}: {err.message}")
            if len(schema_errors) > 5:
                errors.append(f"Schema: {len(schema_errors) - 5} more error(s)")
    return errors


def check_endpoint(
    ep: Endpoint,
    settings: Settings,
    session: requests.Session | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> CheckResult:
    """Run the check; on failure retry up to `retries` times to filter transient errors."""
    session = session or requests.Session()
    timeout = ep.timeout_seconds or settings.timeout_seconds
    attempts = settings.retries + 1
    result: CheckResult | None = None

    for attempt in range(1, attempts + 1):
        ts = time.time()
        kwargs: dict = {"headers": ep.headers, "timeout": timeout}
        if isinstance(ep.body, (dict, list)):
            kwargs["json"] = ep.body
        elif ep.body is not None:
            kwargs["data"] = str(ep.body)

        start = time.perf_counter()
        try:
            resp = session.request(ep.method, ep.url, **kwargs)
            elapsed = (time.perf_counter() - start) * 1000
            status: int | None = resp.status_code
            errors = evaluate(ep, resp, elapsed)
        except requests.RequestException as exc:
            elapsed, status = None, None
            errors = [f"Request failed: {type(exc).__name__}: {exc}"]

        result = CheckResult(ep.name, ts, not errors, status, elapsed, attempt, errors)
        if result.ok:
            return result
        if attempt < attempts:
            sleep(settings.retry_delay_seconds)

    assert result is not None
    return result


def run_checks(config: Config, max_workers: int = 8) -> list[CheckResult]:
    """Check all endpoints in parallel; results come back in config order."""
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(lambda ep: check_endpoint(ep, config.settings), config.endpoints))
