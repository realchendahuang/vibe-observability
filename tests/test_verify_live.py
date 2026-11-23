import http.server
import json
import subprocess
import sys
import threading
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFY_SCRIPT = REPO_ROOT / "skills" / "vibe-observability" / "scripts" / "verify_live.py"

sys.path.insert(0, str(VERIFY_SCRIPT.parent))
import verify_live  # noqa: E402


class _MockLiveHandler(http.server.BaseHTTPRequestHandler):
    mode = "healthy"

    def log_message(self, format, *args):  # noqa: A002
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'")
            self.end_headers()
            self.wfile.write(b'<html><body><script src="/assets/app.js"></script></body></html>')
            return

        if self.path == "/api/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
            return

        if self.path == "/ingest/static/array.js":
            if self.mode == "broken":
                self.send_response(307)
                self.send_header("Location", "/login")
                self.end_headers()
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript")
                self.end_headers()
                self.wfile.write(b"/* posthog sdk */")
            return

        if self.path == "/assets/app.js.map":
            if self.mode == "broken":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"version":3,"sources":["src/app.ts"],"mappings":"AAAA"}')
            else:
                self.send_response(404)
                self.end_headers()
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/monitoring":
            if self.mode == "broken":
                self.send_response(302)
                self.send_header("Location", "/login")
                self.end_headers()
            else:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"Missing DSN"}')
            return
        self.send_response(404)
        self.end_headers()


class TestVerifyLive(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _MockLiveHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def test_healthy_deployment_passes_strict(self) -> None:
        _MockLiveHandler.mode = "healthy"
        proc = subprocess.run(
            [sys.executable, str(VERIFY_SCRIPT), f"http://127.0.0.1:{self.port}", "--json", "--strict"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["summary"]["CRITICAL"], 0)
        self.assertEqual(data["summary"]["HIGH"], 0)
        self.assertGreaterEqual(data["summary"]["PASS"], 5)

    def test_detects_auth_redirect_and_sourcemap_leak(self) -> None:
        _MockLiveHandler.mode = "broken"
        report = verify_live.verify_live(
            base_url=f"http://127.0.0.1:{self.port}",
            health_paths=["/api/health"],
        )
        statuses = {c["id"]: c["status"] for c in report["checks"]}
        self.assertEqual(statuses["LIVE-003"], "HIGH")      # /ingest 307 -> /login
        self.assertEqual(statuses["LIVE-004"], "HIGH")      # /monitoring 302 -> /login
        self.assertEqual(statuses["LIVE-005"], "CRITICAL")  # public .js.map exposed


if __name__ == "__main__":
    unittest.main()
