import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PULL_SCRIPT = REPO_ROOT / "skills" / "vibe-observability-loop" / "scripts" / "pull_signals.py"


class _MockSignalAPI(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/0/projects/my-org/my-proj/issues/"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    [
                        {
                            "shortId": "APP-42",
                            "title": "TypeError: Cannot read properties of undefined",
                            "culprit": "src/checkout.ts",
                            "level": "error",
                            "count": "120",
                            "userCount": 37,
                            "firstSeen": "2026-11-20T00:00:00Z",
                            "lastSeen": "2026-11-23T00:00:00Z",
                            "permalink": "https://sentry.io/issues/42/",
                        }
                    ]
                ).encode("utf-8")
            )
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/projects/99/query/":
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            query_sql = body.get("query", {}).get("query", "")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if "$ai_generation" in query_sql and "GROUP BY model" in query_sql:
                self.wfile.write(json.dumps({"results": [["gemini-2.5-flash", 450, 1.24, 90000, 32000]]}).encode("utf-8"))
            else:
                self.wfile.write(
                    json.dumps(
                        {
                            "results": [
                                ["signup_completed", 80, 79],
                                ["$ai_generation", 450, 62],
                            ]
                        }
                    ).encode("utf-8")
                )
            return
        self.send_response(404)
        self.end_headers()


class TestPullSignals(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _MockSignalAPI)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def test_pulls_sentry_posthog_and_job_history_without_leaking_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / "runs.jsonl"
            history.write_text(
                "\n".join(
                    [
                        json.dumps({"job": "xhs_sync", "run_id": "r1", "status": "ok", "items_fetched": 120}),
                        json.dumps(
                            {
                                "job": "xhs_sync",
                                "run_id": "r2",
                                "status": "degraded",
                                "items_fetched": 0,
                                "anomaly_reason": "zero_items_fetched",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            env = {
                "PATH": os.environ.get("PATH", ""),
                "SENTRY_AUTH_TOKEN": "sntrys_super_secret_token_do_not_print",
                "SENTRY_ORG": "my-org",
                "SENTRY_PROJECT": "my-proj",
                "SENTRY_BASE_URL": f"http://127.0.0.1:{self.port}",
                "POSTHOG_PERSONAL_API_KEY": "phx_super_secret_key_do_not_print",
                "POSTHOG_PROJECT_ID": "99",
                "POSTHOG_HOST": f"http://127.0.0.1:{self.port}",
            }

            proc = subprocess.run(
                [sys.executable, str(PULL_SCRIPT), "--days", "7", "--job-history", str(history), "--json"],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn("super_secret", proc.stdout)
            self.assertNotIn("super_secret", proc.stderr)

            payload = json.loads(proc.stdout)
            self.assertEqual(payload["sentry"]["status"], "ok")
            self.assertEqual(payload["sentry"]["issues"][0]["short_id"], "APP-42")
            self.assertEqual(payload["posthog"]["status"], "ok")
            self.assertEqual(payload["posthog"]["ai_generations"][0]["model"], "gemini-2.5-flash")
            self.assertEqual(payload["jobs"]["jobs"]["xhs_sync"]["degraded"], 1)

    def test_graceful_skip_when_unconfigured(self) -> None:
        env = {"PATH": os.environ.get("PATH", "")}
        proc = subprocess.run(
            [sys.executable, str(PULL_SCRIPT), "--json"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["sentry"]["status"], "skipped")
        self.assertEqual(payload["posthog"]["status"], "skipped")
        self.assertEqual(payload["jobs"]["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
