import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import mock_api  # noqa: E402
from healthcheck.alerts import AlertManager  # noqa: E402
from healthcheck.checker import CheckResult, check_endpoint  # noqa: E402
from healthcheck.config import Endpoint, Settings, load_config  # noqa: E402
from healthcheck.history import History  # noqa: E402
from healthcheck.postman import export_collection, import_collection  # noqa: E402
from healthcheck.runner import Runner, write_junit  # noqa: E402


@pytest.fixture(scope="module")
def base_url():
    server = mock_api.serve(0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


FAST = Settings(retries=2, retry_delay_seconds=0, timeout_seconds=5)


def test_ok_with_schema(base_url):
    ep = Endpoint("users", f"{base_url}/api/users", max_response_ms=2000,
                  schema={"type": "array", "items": {"type": "object", "required": ["id"]}})
    r = check_endpoint(ep, FAST)
    assert r.ok and r.status == 200 and r.attempts == 1


def test_schema_violation(base_url):
    ep = Endpoint("users", f"{base_url}/api/users", max_response_ms=2000,
                  schema={"type": "array", "items": {"required": ["phone"]}})
    r = check_endpoint(ep, FAST)
    assert not r.ok and r.attempts == 3
    assert any("phone" in e for e in r.errors)


def test_wrong_status_and_slow(base_url):
    assert "Status 404" in check_endpoint(Endpoint("x", f"{base_url}/nope"), FAST).errors[0]
    r = check_endpoint(Endpoint("slow", f"{base_url}/api/report", max_response_ms=200),
                       Settings(retries=0, timeout_seconds=5))
    assert not r.ok and "Response time" in r.errors[0]


def test_connection_error():
    r = check_endpoint(Endpoint("down", "http://127.0.0.1:9/"), Settings(retries=0, timeout_seconds=1))
    assert not r.ok and r.status is None and "Request failed" in r.errors[0]


def test_post_body(base_url):
    ep = Endpoint("create", f"{base_url}/api/users", method="POST", body={"name": "a", "email": "b"},
                  expected_status=[201], max_response_ms=2000, contains=['"name": "a"'])
    assert check_endpoint(ep, FAST).ok


class Recorder:
    def __init__(self):
        self.events = []

    def send(self, kind, title, message):
        self.events.append(kind)


def _res(ok):
    return CheckResult("svc", 0.0, ok, 200 if ok else 500, 10.0, 1, [] if ok else ["boom"])


def test_alert_confirmation_escalation_recovery(tmp_path):
    rec, esc = Recorder(), Recorder()
    mgr = AlertManager(Settings(confirm_failures=3, escalate_after=2), History(tmp_path / "h.json"), [rec], [esc])
    ep = Endpoint("svc", "http://x")
    events = [mgr.process(ep, _res(ok)) for ok in [False, True, False, False, False, False, False, True]]
    # a single failure doesn't alert; 3 in a row -> ALERT; +2 -> ESCALATION; then RECOVERY
    assert events == [None, None, None, None, "ALERT", None, "ESCALATION", "RECOVERY"]
    assert rec.events == ["ALERT", "RECOVERY"] and esc.events == ["ESCALATION"]


def test_uptime(tmp_path):
    h = History(tmp_path / "h.json")
    import time
    for ok in [True, True, True, False]:
        r = _res(ok)
        r.timestamp = time.time()
        h.record(r)
    assert h.uptime("svc", 3600) == 75.0
    h.save()
    assert History(tmp_path / "h.json").uptime("svc", 3600) == 75.0


def test_postman_roundtrip():
    cfg = load_config(ROOT / "endpoints.yaml")
    coll = export_collection(cfg)
    assert {"key": "BASE_URL", "value": "http://127.0.0.1:8000"} in coll["variable"]
    assert coll["item"][0]["request"]["url"] == "{{BASE_URL}}/health"
    back = import_collection(json.loads(json.dumps(coll)))["endpoints"]
    assert len(back) == len(cfg.endpoints)
    users = back[1]
    assert users["url"] == "${BASE_URL:-http://127.0.0.1:8000}/api/users"
    assert users["max_response_ms"] == 500 and users["schema"]["type"] == "array"
    assert back[2]["expected_status"] == [200, 201]
    assert back[0]["contains"] == ['"status": "ok"']


def test_full_run(tmp_path, base_url, monkeypatch):
    monkeypatch.setenv("BASE_URL", base_url)
    cfg_text = (ROOT / "endpoints.yaml").read_text(encoding="utf-8")
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas" / "user.json").write_text((ROOT / "schemas/user.json").read_text("utf-8"), "utf-8")
    (tmp_path / "endpoints.yaml").write_text(cfg_text.replace("retry_delay_seconds: 1", "retry_delay_seconds: 0"),
                                             encoding="utf-8")
    cfg = load_config(tmp_path / "endpoints.yaml")
    results = Runner(cfg, alerts=False).run_once()
    by = {r.name: r for r in results}
    assert by["Health"].ok and by["List users"].ok and by["Create user"].ok
    assert not by["Report (slow)"].ok
    page = cfg.settings.status_page.read_text(encoding="utf-8")
    assert "List users" in page and "service(s) down" not in page  # one failure is not confirmed yet
    write_junit(results, tmp_path / "j.xml")
    assert 'failures="' in (tmp_path / "j.xml").read_text(encoding="utf-8")


def test_demo_modes(base_url):
    import requests
    ctl = f"{base_url}/__demo/mode"
    report = Endpoint("report", f"{base_url}/api/report", max_response_ms=800)
    health = Endpoint("health", f"{base_url}/health", max_response_ms=2000)
    fast = Settings(retries=0, timeout_seconds=5)
    try:
        assert requests.post(ctl, json={"mode": "healthy"}, timeout=5).json()["mode"] == "healthy"
        assert check_endpoint(report, fast).ok                      # no artificial delay
        requests.post(ctl, json={"mode": "outage"}, timeout=5)
        r = check_endpoint(health, fast)
        assert not r.ok and r.status == 503
        assert requests.post(ctl, json={"mode": "nope"}, timeout=5).status_code == 400
    finally:
        requests.post(ctl, json={"mode": "degraded"}, timeout=5)
    assert requests.get(ctl, timeout=5).json()["mode"] == "degraded"