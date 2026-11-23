"""Demo REST API for trying out the health checker.

Run:  py mock_api.py [port]     (default: 8000)
  GET  /health                 -> 200 {"status": "ok"}
  GET  /api/users              -> 200 list of users
  POST /api/users              -> 201 created user
  GET  /api/report             -> 200, but after ~1.2 s (breaks the response-time limit)
  GET  /api/payments/status    -> 503 about 30% of the time (flaky service)
"""
import json
import random
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

USERS = [
    {"id": 1, "name": "Anna Smith", "email": "anna@example.com"},
    {"id": 2, "name": "Peter Jones", "email": "peter@example.com"},
]


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok"})
        elif self.path == "/api/users":
            self._send(200, USERS)
        elif self.path == "/api/report":
            time.sleep(1.2)
            self._send(200, {"rows": 42})
        elif self.path == "/api/payments/status":
            if random.random() < 0.3:
                self._send(503, {"error": "upstream unavailable"})
            else:
                self._send(200, {"status": "up"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/api/users":
            return self._send(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._send(400, {"error": "invalid json"})
        self._send(201, {"id": len(USERS) + 1, **data})

    def log_message(self, fmt, *args):
        pass


def serve(port: int = 8000) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"Demo API: http://127.0.0.1:{port}  (Ctrl+C to stop)")
    try:
        serve(port).serve_forever()
    except KeyboardInterrupt:
        pass
