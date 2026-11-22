import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_SCRIPT = REPO_ROOT / "skills" / "vibe-observability" / "scripts" / "audit_observability.py"

sys.path.insert(0, str(AUDIT_SCRIPT.parent))
import audit_observability  # noqa: E402


class TestAuditObservability(unittest.TestCase):
    def _write_files(self, root: Path, files: dict[str, str]) -> None:
        for rel, content in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def test_clean_core_setup_scores_high(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_files(
                root,
                {
                    "package.json": '{"dependencies": {"next": "15.0.0", "posthog-js": "^1.0.0", "@sentry/nextjs": "^9.0.0", "pino": "^9.0.0"}}',
                    ".env.example": "\n".join(
                        [
                            "NEXT_PUBLIC_SENTRY_DSN=",
                            "NEXT_PUBLIC_POSTHOG_KEY=",
                            "NEXT_PUBLIC_POSTHOG_HOST=https://us.i.posthog.com",
                            "NEXT_PUBLIC_OBSERVABILITY_DEBUG=false",
                        ]
                    ),
                    "next.config.ts": """
import { withSentryConfig } from "@sentry/nextjs";
export default withSentryConfig({
  async rewrites() {
    return [{ source: "/ingest/:path*", destination: "https://us.i.posthog.com/:path*" }];
  },
}, { tunnelRoute: "/monitoring" });
""",
                    "src/lib/telemetry/index.ts": """
import posthog from "posthog-js";
import * as Sentry from "@sentry/nextjs";

const isProd = process.env.NODE_ENV === "production";
Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  enabled: isProd || process.env.NEXT_PUBLIC_OBSERVABILITY_DEBUG === "true",
  tracesSampleRate: isProd ? 0.1 : 0,
  sendDefaultPii: false,
});

posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY!, {
  api_host: "/ingest",
  ui_host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
  person_profiles: "identified_only",
  session_recording: { maskAllInputs: true },
  loaded: (ph) => { if (!isProd) ph.opt_out_capturing(); },
});
""",
                    "src/app/api/health/route.ts": """
import pino from "pino";
export const logger = pino();
export function GET() { return Response.json({ status: "ok" }); }
""",
                },
            )
            report = audit_observability.audit_project(root)
            self.assertEqual(report["score"], 100)
            self.assertEqual(report["findings"], [])
            self.assertEqual(set(report["detected_providers"]), {"sentry", "posthog"})

    def test_detects_dual_replay_hardcoded_secret_pii_and_unbounded_sampling(self) -> None:
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
            finding_ids = {f["id"] for f in report["findings"]}

            self.assertIn("OBS-001", finding_ids)  # hardcoded secrets
            self.assertIn("OBS-002", finding_ids)  # dual replay conflict
            self.assertIn("OBS-003", finding_ids)  # unbounded tracesSampleRate
            self.assertIn("OBS-004", finding_ids)  # PII to GA4 & sendDefaultPii
            self.assertIn("OBS-005", finding_ids)  # missing maskAllInputs
            self.assertIn("OBS-006", finding_ids)  # direct posthog without reverse proxy
            self.assertIn("OBS-007", finding_ids)  # scattered raw SDK calls
            self.assertIn("OBS-008", finding_ids)  # missing env var in .env.example
            self.assertIn("OBS-009", finding_ids)  # missing person_profiles
            self.assertLess(report["score"], 30)

    def test_deduped_full_profile_passes_dual_replay_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_files(
                root,
                {
                    "src/lib/telemetry.ts": """
import posthog from "posthog-js";
import Clarity from "@microsoft/clarity";
const isProd = process.env.NODE_ENV === "production";
posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY!, {
  api_host: "/ingest",
  person_profiles: "identified_only",
  disable_session_recording: true,
});
if (isProd) Clarity.init(process.env.NEXT_PUBLIC_CLARITY_PROJECT_ID!);
""",
                    ".env.example": "NEXT_PUBLIC_POSTHOG_KEY=\nNEXT_PUBLIC_CLARITY_PROJECT_ID=\n",
                },
            )
            report = audit_observability.audit_project(root)
            finding_ids = {f["id"] for f in report["findings"]}
            self.assertNotIn("OBS-002", finding_ids)
            self.assertNotIn("OBS-005", finding_ids)

    def test_starter_templates_score_100(self) -> None:
        for template_name in ("nextjs-app-router", "vite-react"):
            template_dir = REPO_ROOT / "templates" / template_name
            report = audit_observability.audit_project(template_dir)
            self.assertEqual(report["score"], 100, f"{template_name} findings: {report['findings']}")

    def test_cli_json_and_strict_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_files(
                root,
                {
                    "src/sentry.ts": 'Sentry.init({ tracesSampleRate: 1.0 });',
                },
            )
            proc = subprocess.run(
                [sys.executable, str(AUDIT_SCRIPT), str(root), "--json", "--strict"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 1)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["summary"]["HIGH"], 1)


if __name__ == "__main__":
    unittest.main()
