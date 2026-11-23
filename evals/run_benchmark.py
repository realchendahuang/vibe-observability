#!/usr/bin/env python3
"""Reproducible Before-vs-After observability benchmark.

Compares three typical naive vibe-coded setups (generated cleanly in temp dirs)
against the five self-contained `vibe-observability` reference stacks using
the same static auditor (`audit_observability.py`).

Run:
  python3 evals/run_benchmark.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_DIR = REPO_ROOT / "skills" / "vibe-observability" / "scripts"
EXAMPLES_DIR = REPO_ROOT / "skills" / "vibe-observability" / "examples"

sys.path.insert(0, str(AUDIT_DIR))
import audit_observability  # noqa: E402


def _write(root: Path, files: Dict[str, str]) -> None:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def _naive_scenarios() -> List[Tuple[str, Dict[str, str]]]:
    return [
        (
            "Naive Web App (unbounded 4-SDK dump)",
            {
                "package.json": '{"dependencies":{"vite":"^8.0.0","posthog-js":"^1.0.0","@microsoft/clarity":"^1.0.0","@sentry/react":"^9.0.0"}}',
                "src/main.tsx": """
import posthog from "posthog-js";
import Clarity from "@microsoft/clarity";
import * as Sentry from "@sentry/react";

Sentry.init({
  dsn: import.meta.env.VITE_SENTRY_DSN,
  tracesSampleRate: 1.0,
  sendDefaultPii: true,
});
posthog.init(import.meta.env.VITE_POSTHOG_KEY, {
  api_host: "https://us.i.posthog.com",
});
Clarity.init(import.meta.env.VITE_CLARITY_PROJECT_ID);
gtag("event", "signup", { email: "demo@example.com" });
""",
                "src/pages/Home.tsx": 'posthog.capture("clicked_hero");',
                "src/pages/Pricing.tsx": 'posthog.capture("viewed_pricing");',
                "src/pages/Checkout.tsx": 'posthog.capture("started_checkout");',
            },
        ),
        (
            "Naive Cloudflare Worker (Node SDK + no waitUntil)",
            {
                "wrangler.toml": 'name = "naive-worker"\n',
                "src/index.ts": """
import * as Sentry from "@sentry/node";
import { PostHog } from "posthog-node";

const ph = new PostHog(env.POSTHOG_KEY);
Sentry.init({ dsn: env.SENTRY_DSN, tracesSampleRate: 1.0 });

export default {
  async fetch() {
    ph.capture({ distinctId: "u1", event: "api_hit" });
    return new Response("ok");
  },
};
""",
            },
        ),
        (
            "Naive Desktop Tauri App (web Clarity + GA4)",
            {
                "tauri.conf.json": '{"productName":"LocalTool"}',
                "src/main.ts": """
import Clarity from "@microsoft/clarity";
import * as Sentry from "@sentry/react";

Sentry.init({ dsn: import.meta.env.VITE_SENTRY_DSN, sendDefaultPii: true });
Clarity.init(import.meta.env.VITE_CLARITY_PROJECT_ID);
gtag("event", "app_open", { email: "local@user.test" });
""",
            },
        ),
    ]


def run_benchmark() -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        for idx, (label, files) in enumerate(_naive_scenarios()):
            case_dir = tmp_root / f"naive_{idx}"
            _write(case_dir, files)
            rep = audit_observability.audit_project(case_dir)
            rows.append(
                {
                    "group": "Before (Naive)",
                    "name": label,
                    "score": rep["score"],
                    "high_crit": rep["summary"]["CRITICAL"] + rep["summary"]["HIGH"],
                    "findings": [f["id"] for f in rep["findings"]],
                }
            )

    for example in (
        "vite-tanstack-hono",
        "cloudflare-workers-hono",
        "go-gin-caddy",
        "python-uv-job",
        "nextjs-app-router",
    ):
        rep = audit_observability.audit_project(EXAMPLES_DIR / example)
        rows.append(
            {
                "group": "After (`vibe-observability`)",
                "name": f"Starter: `{example}`",
                "score": rep["score"],
                "high_crit": rep["summary"]["CRITICAL"] + rep["summary"]["HIGH"],
                "findings": [f["id"] for f in rep["findings"]],
            }
        )

    return rows


def main() -> int:
    rows = run_benchmark()
    print("| Category | Scenario | Audit Score | Critical/High | Triggered Rules |")
    print("| :--- | :--- | :---: | :---: | :--- |")
    for r in rows:
        rules = ", ".join(r["findings"]) if r["findings"] else "None (PASS)"
        print(f"| {r['group']} | {r['name']} | **{r['score']}/100** | {r['high_crit']} | {rules} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
