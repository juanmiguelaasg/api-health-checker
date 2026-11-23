"""Checks that keep the Docker setup honest without needing Docker installed."""
import fnmatch
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import mock_api  # noqa: E402
from healthcheck.cli import main as cli_main  # noqa: E402
from healthcheck.history import History  # noqa: E402


def _names(path: Path) -> set[str]:
    return {line.split(">=")[0].split("==")[0].strip().lower()
            for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")}


def test_headless_path_does_not_need_tk():
    # the image has no tkinter / customtkinter, and healthcheck/ui is not copied
    code = ("import sys, healthcheck.cli, healthcheck.runner, healthcheck.postman, mock_api;"
            "bad = [m for m in ('tkinter', 'customtkinter', 'healthcheck.ui') if m in sys.modules];"
            "print(bad); sys.exit(1 if bad else 0)")
    res = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr


def test_headless_requirements_are_a_subset():
    headless, full = _names(ROOT / "requirements-headless.txt"), _names(ROOT / "requirements.txt")
    assert headless and headless <= full
    assert "customtkinter" not in headless


def test_dockerignore_keeps_what_the_image_copies():
    ignored = [l.strip() for l in (ROOT / ".dockerignore").read_text().splitlines() if l.strip()]
    for needed in ("healthcheck", "schemas", "endpoints.yaml", "mock_api.py", "requirements-headless.txt"):
        assert not any(fnmatch.fnmatch(needed, pat) for pat in ignored), needed
        assert (ROOT / needed).exists(), needed


def test_dockerfile_and_compose_point_at_real_things():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert '"heartbeat"' in dockerfile and '"watch"' in dockerfile
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = compose["services"]
    assert {"checker", "status-page", "demo-api"} <= set(services)
    assert services["demo-api"]["profiles"] == ["demo"]
    assert services["demo-api"]["entrypoint"][-1] == "mock_api.py"
    assert services["demo-api"]["command"][1] in mock_api.MODES
    for vol in services["checker"]["volumes"]:
        src = vol.split(":")[0]
        if src.startswith("./"):
            assert (ROOT / src[2:]).exists(), src


def _config(tmp_path: Path) -> Path:
    cfg = tmp_path / "endpoints.yaml"
    cfg.write_text("settings: {interval_seconds: 10}\nendpoints:\n  - {name: x, url: 'http://127.0.0.1:9/'}\n",
                   encoding="utf-8")
    return cfg


def test_heartbeat(tmp_path, capsys):
    cfg = _config(tmp_path)
    assert cli_main(["-c", str(cfg), "heartbeat"]) == 1          # no runs yet
    h = History(tmp_path / "data/history.json")
    h.add_run({"ts": time.time() - 120, "ok": 1, "total": 1, "avg_ms": 5, "uptime24": 100})
    h.save()
    assert cli_main(["-c", str(cfg), "heartbeat"]) == 1          # stale: 120 s > 3 x 10 s
    assert cli_main(["-c", str(cfg), "heartbeat", "--max-age", "300"]) == 0
    h.add_run({"ts": time.time(), "ok": 1, "total": 1, "avg_ms": 5, "uptime24": 100})
    h.save()
    assert cli_main(["-c", str(cfg), "heartbeat"]) == 0
    assert "ok: last run" in capsys.readouterr().out


def test_demo_api_binds_demo_host(monkeypatch):
    monkeypatch.setenv("DEMO_HOST", "0.0.0.0")
    server = mock_api.serve(0)
    try:
        assert server.server_address[0] == "0.0.0.0"
    finally:
        server.server_close()
    monkeypatch.delenv("DEMO_HOST")
    server = mock_api.serve(0)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()
