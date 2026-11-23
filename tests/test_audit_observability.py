import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_SCRIPT = REPO_ROOT / "skills" / "vibe-observability" / "scripts" / "audit_observability.py"
EXAMPLES_DIR = REPO_ROOT / "skills" / "vibe-observability" / "examples"

sys.path.insert(0, str(AUDIT_SCRIPT.parent))
import audit_observability  # noqa: E402


class TestAuditObservability(unittest.TestCase):
    def _write_files(self, root: Path, files: dict[str, str]) -> None:
        for rel, content in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def test_all_starter_examples_score_100(self) -> None:
        expected = [
            "vite-tanstack-hono",
            "cloudflare-workers-hono",
            "go-gin-caddy",
            "python-uv-job",
            "nextjs-app-router",
        ]
        for name in expected:
            example_dir = EXAMPLES_DIR / name
            self.assertTrue(example_dir.is_dir(), f"Missing example {name}")
            report = audit_observability.audit_project(example_dir)
            self.assertEqual(report["score"], 100, f"{name} findings: {report['findings']}")

    def test_detects_core_web_pitfalls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_files(
                root,
                {
                    "package.json": '{"dependencies": {"posthog-js": "^1.0.0", "@microsoft/clarity": "^1.0.0", "@sentry/react": "^9.0.0"}}',
                    "src/main.ts": """
import posthog from "posthog-js";
import Clarity from "@microsoft/clarity";
import * as Sentry from "@sentry/react";

Sentry.init({
  dsn: "https://0123456789abcdef0123456789abcdef@o12345.ingest.us.sentry.io/999999",
  tracesSampleRate: 1.0,
  sendDefaultPii: true,
});

posthog.init("phc_AbCdEfGhIjKlMnOpQrStUvWxYz123456", {
  api_host: "https://us.i.posthog.com",
});

Clarity.init(import.meta.env.VITE_CLARITY_PROJECT_ID);
gtag("event", "signup", { email: "user@example.com" });
""",
                    "src/components/A.tsx": 'posthog.capture("a");',
                    "src/components/B.tsx": 'posthog.capture("b");',
                    "src/components/C.tsx": 'posthog.capture("c");',
                },
            )
            report = audit_observability.audit_project(root)
            ids = {f["id"] for f in report["findings"]}

            for expected_id in ("OBS-001", "OBS-002", "OBS-003", "OBS-004", "OBS-005", "OBS-006", "OBS-007", "OBS-008", "OBS-009"):
                self.assertIn(expected_id, ids)
            self.assertLess(report["score"], 30)

    def test_detects_desktop_native_web_trackers_obs012(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_files(
                root,
                {
                    "tauri.conf.json": '{"productName": "MyWinTool"}',
                    "src/main.ts": 'import Clarity from "@microsoft/clarity"; Clarity.init(import.meta.env.VITE_CLARITY_PROJECT_ID);',
                    ".env.example": "VITE_CLARITY_PROJECT_ID=\n",
                },
            )
            report = audit_observability.audit_project(root)
            ids = {f["id"] for f in report["findings"]}
            self.assertTrue(report["detected_stack"]["desktop_native"])
            self.assertIn("OBS-012", ids)

    def test_detects_cloudflare_workers_traps_obs013_and_obs016(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_files(
                root,
                {
                    "wrangler.toml": 'name = "edge-tool"\n',
                    "src/index.ts": """
import * as Sentry from "@sentry/node";
import { PostHog } from "posthog-node";

const ph = new PostHog(env.POSTHOG_KEY);
export default {
  fetch() {
    ph.capture({ distinctId: "u1", event: "ping" });
    return new Response("ok");
  }
};
""",
                    ".env.example": "POSTHOG_KEY=\n",
                },
            )
            report = audit_observability.audit_project(root)
            ids = {f["id"] for f in report["findings"]}
            self.assertTrue(report["detected_stack"]["cloudflare_workers"])
            self.assertIn("OBS-013", ids)  # missing shutdown/flush/waitUntil
            self.assertIn("OBS-016", ids)  # @sentry/node on Cloudflare Workers

    def test_detects_middleware_blocking_proxy_and_sourcemap_leak_obs014_obs015(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_files(
                root,
                {
                    "package.json": '{"dependencies": {"next": "15.0.0", "@sentry/nextjs": "^9.0.0"}}',
                    "next.config.ts": """
import { withSentryConfig } from "@sentry/nextjs";
export default withSentryConfig({
  async rewrites() {
    return [{ source: "/ingest/:path*", destination: "https://us.i.posthog.com/:path*" }];
  },
}, { tunnelRoute: "/monitoring" });
""",
                    "src/middleware.ts": """
export function middleware() {}
export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
""",
                },
            )
            report = audit_observability.audit_project(root)
            ids = {f["id"] for f in report["findings"]}
            self.assertIn("OBS-014", ids)
            self.assertIn("OBS-015", ids)

    def test_cli_json_and_strict_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_files(root, {"src/sentry.ts": "Sentry.init({ tracesSampleRate: 1.0 });"})
            proc = subprocess.run(
                [sys.executable, str(AUDIT_SCRIPT), str(root), "--json", "--strict"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 1)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["summary"]["HIGH"], 1)

    def test_uninstrumented_repo_reports_none_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_files(root, {"src/app.ts": "export const hello = () => 'world';"})
            report = audit_observability.audit_project(root)
            self.assertFalse(report["instrumented"])
            self.assertIsNone(report["score"])
            self.assertIn("N/A (not instrumented yet)", audit_observability.render_markdown_report(report))


if __name__ == "__main__":
    unittest.main()
