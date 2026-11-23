"""Demo REST API for trying out the health checker.

Run:  py mock_api.py [port] [mode]     (defaults: 8000, degraded)

  GET  /health                 -> 200 {"status": "ok"}
  GET  /api/users              -> 200 list of users
  POST /api/users              -> 201 created user
  GET  /api/report             -> 200 (slow in "degraded" mode: ~1.2 s, breaks the limit)
  GET  /api/payments/status    -> 200 (in "degraded" mode: 503 about 30% of the time)

Demo modes, switchable at runtime (the desktop app's DEMO API card uses this):
  GET  /__demo/mode            -> {"mode": "...", "modes": [...]}
  POST /__demo/mode            <- {"mode": "healthy" | "degraded" | "outage"}

  healthy   every endpoint is fast and returns 2xx
  degraded  /api/report is slow, /api/payments/status is flaky
  outage    every endpoint returns 503
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODES = ("healthy", "degraded", "outage")
MODE = "degraded"
CONTROL = "/__demo/mode"

USERS = [
    {"id": 1, "name": "Anna Smith", "email": "anna@example.com"},
    {"id": 2, "name": "Peter Jones", "email": "peter@example.com"},
]


def set_mode(mode: str) -> None:
    global MODE
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}, expected one of {MODES}")
    MODE = mode


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        if self.path == CONTROL:
            return self._send(200, {"mode": MODE, "modes": list(MODES)})
        if MODE == "outage":
            return self._send(503, {"error": "service unavailable (demo outage)"})
        if self.path == "/health":
            self._send(200, {"status": "ok"})
        elif self.path == "/api/users":
            self._send(200, USERS)
        elif self.path == "/api/report":
            if MODE == "degraded":
                time.sleep(1.2)
            self._send(200, {"rows": 42})
        elif self.path == "/api/payments/status":
            if MODE == "degraded" and random.random() < 0.3:
                self._send(503, {"error": "upstream unavailable"})
            else:
                self._send(200, {"status": "up"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            data = self._read_json()
        except ValueError:
            return self._send(400, {"error": "invalid json"})
        if self.path == CONTROL:
            try:
                set_mode(str(data.get("mode")))
            except ValueError as exc:
                return self._send(400, {"error": str(exc)})
            return self._send(200, {"mode": MODE})
        if MODE == "outage":
            return self._send(503, {"error": "service unavailable (demo outage)"})
        if self.path != "/api/users":
            return self._send(404, {"error": "not found"})
        self._send(201, {"id": len(USERS) + 1, **data})

    def log_message(self, fmt, *args):
        pass


def serve(port: int = 8000, host: str | None = None) -> ThreadingHTTPServer:
    """Bind to 127.0.0.1 by default; set DEMO_HOST=0.0.0.0 inside a container."""
    return ThreadingHTTPServer((host or os.environ.get("DEMO_HOST", "127.0.0.1"), port), Handler)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    if len(sys.argv) > 2:
        set_mode(sys.argv[2])
    server = serve(port)
    print(f"Demo API: http://{server.server_address[0]}:{port}  mode={MODE}  (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
