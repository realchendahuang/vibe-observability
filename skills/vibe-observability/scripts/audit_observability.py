#!/usr/bin/env python3
"""Static observability auditor for Vibe Coding & indie web/full-stack projects.

Zero external dependencies (Python 3.9+ stdlib only).
Checks for:
  - Hardcoded observability keys/tokens in source files
  - Dual session-replay conflicts (PostHog + Clarity / Sentry Replay overlap)
  - Unbounded Sentry tracesSampleRate (billing explosion risk)
  - Potential PII sent to GA4 or Sentry sendDefaultPii=true
  - Missing PostHog input masking or person_profiles cost guardrail
  - Direct PostHog ingestion without a first-party reverse proxy
  - Scattered raw vendor SDK calls instead of a unified telemetry facade
  - Missing observability env vars in .env.example
  - Backend missing /health probe or structured logging
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Tuple

SKIP_DIRS: Set[str] = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".vercel",
    ".turbo",
    "dist",
    "build",
    "out",
    "coverage",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".venv",
    "venv",
    "env",
    "vendor",
    "target",
    ".agents",
}

CODE_EXTENSIONS: Set[str] = {
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".vue",
    ".svelte",
    ".astro",
    ".py",
    ".go",
    ".html",
    ".htm",
}

CONFIG_FILENAMES: Set[str] = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "go.mod",
    "next.config.js",
    "next.config.mjs",
    "next.config.ts",
    "vite.config.ts",
    "vite.config.js",
    "vercel.json",
}

SEVERITY_RANK: Dict[str, int] = {
    "CRITICAL": 4,
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1,
    "INFO": 0,
}

SEVERITY_PENALTY: Dict[str, int] = {
    "CRITICAL": 30,
    "HIGH": 20,
    "MEDIUM": 10,
    "LOW": 5,
    "INFO": 0,
}

FACADE_PATH_HINTS = ("telemetry", "analytics", "observability", "tracking", "instrumentation", "sentry")

ENV_VAR_PATTERN = re.compile(
    r"\b((?:NEXT_PUBLIC_|VITE_|PUBLIC_|NUXT_PUBLIC_)?(?:SENTRY|POSTHOG|GA_MEASUREMENT|CLARITY|OBSERVABILITY)[A-Z0-9_]*)\b"
)

HARDCODED_PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    ("Sentry Auth Token", re.compile(r"\bsntrys_[A-Za-z0-9_=+/.-]{20,}\b")),
    (
        "Hardcoded PostHog Project Key",
        re.compile(r"""['"]phc_(?!x{4,}|X{4,}|example|dummy|test|placeholder|your)[A-Za-z0-9]{20,}['"]"""),
    ),
    (
        "Hardcoded Sentry DSN",
        re.compile(r"""['"]https://[a-f0-9]{16,}@[a-z0-9.-]*ingest[a-z0-9.-]*sentry\.io/\d+['"]""", re.IGNORECASE),
    ),
]


@dataclass
class Finding:
    id: str
    severity: str
    title: str
    detail: str
    remediation: str
    files: List[str] = field(default_factory=list)


def is_facade_file(rel_path: str) -> bool:
    lower = rel_path.lower()
    return any(hint in lower for hint in FACADE_PATH_HINTS)


def is_test_or_example_file(rel_path: str) -> bool:
    lower = rel_path.lower()
    parts = Path(lower).parts
    if any(p in {"test", "tests", "__tests__", "spec", "specs", "fixtures", "mocks"} for p in parts):
        return True
    name = Path(lower).name
    return ".test." in name or ".spec." in name or name.startswith("test_")


def collect_files(root: Path) -> Tuple[List[Path], List[Path]]:
    code_files: List[Path] = []
    config_files: List[Path] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for filename in filenames:
            if filename.endswith(".min.js") or filename.endswith(".map"):
                continue
            path = Path(dirpath) / filename
            if filename in CONFIG_FILENAMES:
                config_files.append(path)
            if path.suffix.lower() in CODE_EXTENSIONS:
                code_files.append(path)
    return code_files, config_files


def read_text_safe(path: Path, max_bytes: int = 512_000) -> str:
    try:
        if path.stat().st_size > max_bytes:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def parse_env_example(root: Path) -> Tuple[bool, Set[str]]:
    candidates = [root / ".env.example", root / ".env.sample", root / ".env.template"]
    found_vars: Set[str] = set()
    found_file = False
    for cand in candidates:
        if cand.is_file():
            found_file = True
            for line in read_text_safe(cand).splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key = stripped.split("=", 1)[0].strip()
                if key:
                    found_vars.add(key)
    return found_file, found_vars


def audit_project(root: Path) -> Dict[str, object]:
    root = root.resolve()
    code_files, config_files = collect_files(root)

    file_contents: Dict[str, str] = {}
    for p in sorted(set(code_files + config_files)):
        rel = str(p.relative_to(root))
        content = read_text_safe(p)
        if content:
            file_contents[rel] = content

    all_text = "\n".join(file_contents.values())
    code_only_items = [
        (rel, text)
        for rel, text in file_contents.items()
        if Path(rel).suffix.lower() in CODE_EXTENSIONS and not is_test_or_example_file(rel)
    ]

    # 1. Detect providers & stack characteristics
    providers: Dict[str, bool] = {
        "sentry": bool(re.search(r"@sentry/|sentry_sdk|Sentry\.init\(|SENTRY_DSN", all_text)),
        "posthog": bool(re.search(r"posthog-js|posthog-node|posthog\.init\(|POSTHOG_KEY", all_text)),
        "ga4": bool(
            re.search(
                r"googletagmanager\.com/gtag|@next/third-parties/google|<GoogleAnalytics|\bgtag\(|GA_MEASUREMENT_ID",
                all_text,
            )
        ),
        "clarity": bool(
            re.search(r"@microsoft/clarity|clarity\.ms/tag|CLARITY_PROJECT_ID|Clarity\.init\(", all_text)
        ),
        "opentelemetry": bool(re.search(r"@opentelemetry/|opentelemetry-api|opentelemetry-sdk", all_text)),
    }

    has_nextjs = any(
        Path(rel).name.startswith("next.config.") for rel in file_contents
    ) or bool(re.search(r'"next"\s*:', file_contents.get("package.json", "")))

    has_backend = bool(
        re.search(
            r"FastAPI\(|express\(|fastify\(|new Hono\(|app/api/|pages/api/|uvicorn|gunicorn",
            all_text,
        )
    ) or any(
        ("/api/" in rel.replace("\\", "/") or rel.replace("\\", "/").startswith("api/") or rel.startswith("server/"))
        for rel in file_contents
    )

    has_structured_logger = bool(
        re.search(r"\b(pino|winston|structlog|loguru|zerolog|bunyan)\b", all_text)
    )
    has_health_route = any(
        re.search(r"healthz?|readyz?", rel, re.IGNORECASE) for rel in file_contents
    ) or bool(re.search(r"""['"]/((api/)?healthz?|readyz?)['"]""", all_text))

    findings: List[Finding] = []

    # OBS-001: Hardcoded secrets/keys in source
    secret_hits: List[str] = []
    for rel, text in code_only_items:
        for label, pattern in HARDCODED_PATTERNS:
            if pattern.search(text):
                secret_hits.append(f"{rel} ({label})")
    if secret_hits:
        findings.append(
            Finding(
                id="OBS-001",
                severity="CRITICAL",
                title="Hardcoded observability key or token detected in source code",
                detail="Credentials or project keys should come from environment variables so keys can be rotated cleanly across staging and production.",
                remediation="Move all DSNs, PostHog keys, and Sentry auth tokens into environment variables and document placeholders in .env.example.",
                files=sorted(set(secret_hits)),
            )
        )

    # OBS-002: Dual session replay conflict
    # Treat `disable_session_recording` as explicitly handled unless hardcoded to `false`.
    posthog_replay_disabled = bool(
        re.search(r"disable_session_recording\s*:\s*(?!false\b)[^\n,}]+", all_text)
    )
    posthog_replay_always_off = bool(re.search(r"disable_session_recording\s*:\s*true\b", all_text))
    sentry_replay_enabled = bool(
        re.search(r"replayIntegration\s*\(|replaysSessionSampleRate\s*:\s*0?\.[1-9]|replaysSessionSampleRate\s*:\s*1\b", all_text)
    )

    if providers["posthog"] and providers["clarity"] and not posthog_replay_disabled:
        findings.append(
            Finding(
                id="OBS-002",
                severity="HIGH",
                title="Dual session-replay conflict: PostHog Replay + Microsoft Clarity both active",
                detail="Running both PostHog Session Replay and Clarity duplicates DOM MutationObservers, hurting LCP/INP and wasting PostHog replay quota.",
                remediation="Set `disable_session_recording: true` in `posthog.init(...)` when using Clarity (full-deduped profile), or drop Clarity and use PostHog Replay alone (core profile).",
                files=[
                    rel
                    for rel, text in code_only_items
                    if "posthog.init" in text or "clarity" in text.lower()
                ],
            )
        )

    if sentry_replay_enabled and ((providers["posthog"] and not posthog_replay_disabled) or providers["clarity"]):
        findings.append(
            Finding(
                id="OBS-002B",
                severity="HIGH",
                title="Sentry Session Replay overlaps with PostHog/Clarity replay",
                detail="Multiple session-replay SDKs are active simultaneously, inflating JS bundle size and browser CPU overhead.",
                remediation="Disable Sentry Replay (`replaysSessionSampleRate: 0`, remove `replayIntegration()`) and let one provider own session replay.",
                files=[rel for rel, text in code_only_items if "replay" in text.lower() and "sentry" in text.lower()],
            )
        )

    # OBS-003: Unbounded Sentry tracesSampleRate: 1.0
    unbounded_sentry_files: List[str] = []
    for rel, text in code_only_items:
        for line in text.splitlines():
            if re.search(r"traces(?:SampleRate|_sample_rate)\s*[:=]\s*1(?:\.0)?\b", line):
                # Ignore lines that explicitly branch by environment inline
                if "?" not in line and " if " not in line:
                    unbounded_sentry_files.append(rel)
                    break
    if unbounded_sentry_files:
        findings.append(
            Finding(
                id="OBS-003",
                severity="HIGH",
                title="Unbounded Sentry tracing sample rate (100%)",
                detail="Hardcoding `tracesSampleRate: 1.0` can exhaust Sentry free quota or cause unexpected overages during traffic spikes.",
                remediation="Use an environment-aware sample rate such as `tracesSampleRate: isProd ? 0.1 : 0` (or drive it from an env var).",
                files=sorted(set(unbounded_sentry_files)),
            )
        )

    # OBS-004: Potential PII leakage to GA4 / Sentry
    pii_files: List[str] = []
    for rel, text in code_only_items:
        if re.search(r"sendDefaultPii\s*:\s*true|send_default_pii\s*=\s*True", text):
            pii_files.append(f"{rel} (Sentry sendDefaultPii=true)")
        # Look for gtag() payloads containing direct email/phone/password/name keys
        for match in re.finditer(r"gtag\s*\([^;]{0,300}\)", text, re.DOTALL):
            snippet = match.group(0)
            if re.search(r"\b(email|phone|password|full_name|ssn|credit_card)\b\s*:", snippet, re.IGNORECASE):
                pii_files.append(f"{rel} (PII key inside gtag call)")
                break
    if pii_files:
        findings.append(
            Finding(
                id="OBS-004",
                severity="HIGH",
                title="Potential PII forwarded to GA4 or Sentry default PII capture enabled",
                detail="Google Analytics ToS strictly bans sending PII (email, phone, full name), and Sentry `sendDefaultPii: true` can leak cookies/IPs/headers.",
                remediation="Set `sendDefaultPii: false` in Sentry, scrub Authorization/Cookie headers in `beforeSend`, and never pass raw email/phone/name into `gtag()`.",
                files=sorted(set(pii_files)),
            )
        )

    # OBS-005: PostHog replay missing input masking
    if providers["posthog"] and not posthog_replay_always_off:
        if not re.search(r"maskAllInputs", all_text):
            findings.append(
                Finding(
                    id="OBS-005",
                    severity="MEDIUM",
                    title="PostHog Session Replay lacks explicit `maskAllInputs: true` guardrail",
                    detail="Without explicit input masking and block selectors, sensitive form fields or user notes may be captured in session recordings.",
                    remediation="Configure `session_recording: { maskAllInputs: true, blockSelector: '[data-ph-no-capture]' }` in `posthog.init(...)`.",
                    files=[rel for rel, text in code_only_items if "posthog.init" in text],
                )
            )

    # OBS-006: Missing reverse proxy / tunnel (AdBlock exposure)
    direct_ph_files = [
        rel
        for rel, text in code_only_items
        if re.search(r"api_host\s*:\s*['\"]https://(?:us|eu|app)(?:\.i)?\.posthog\.com", text)
    ]
    if direct_ph_files and not re.search(r"/ingest", all_text):
        findings.append(
            Finding(
                id="OBS-006",
                severity="MEDIUM",
                title="PostHog points directly to posthog.com without a first-party reverse proxy",
                detail="Up to 30–50% of developer and tech-savvy users run AdBlockers that drop requests sent directly to *.posthog.com.",
                remediation="Route browser ingestion through a neutral same-origin proxy path such as `/ingest` (e.g. via Next.js `rewrites()` or Cloudflare/Nginx proxy).",
                files=sorted(set(direct_ph_files)),
            )
        )

    if has_nextjs and providers["sentry"] and not re.search(r"tunnelRoute", all_text):
        findings.append(
            Finding(
                id="OBS-006B",
                severity="LOW",
                title="Next.js Sentry setup has no `tunnelRoute` configured",
                detail="AdBlockers commonly block *.ingest.sentry.io, hiding frontend exceptions from affected browsers.",
                remediation="Set `tunnelRoute: '/monitoring'` in `withSentryConfig(...)` and exclude `/monitoring` from auth middleware.",
                files=[rel for rel in file_contents if Path(rel).name.startswith("next.config.")],
            )
        )

    # OBS-007: Scattered raw vendor SDK calls outside facade
    raw_call_files: List[str] = []
    for rel, text in code_only_items:
        if is_facade_file(rel):
            continue
        if re.search(r"\bposthog\.capture\s*\(|\bgtag\s*\(\s*['\"]event['\"]|\bClarity\.event\s*\(", text):
            raw_call_files.append(rel)
    if len(raw_call_files) > 2:
        findings.append(
            Finding(
                id="OBS-007",
                severity="MEDIUM",
                title=f"Raw vendor analytics calls scattered across {len(raw_call_files)} non-facade files",
                detail="Calling `posthog.capture` or `gtag` directly in UI components causes naming drift, skips burst guards, and makes switching providers painful.",
                remediation="Consolidate tracking behind a typed `src/lib/telemetry/index.ts` facade with `track()`, `identify()`, `reset()`, and `captureError()`.",
                files=sorted(raw_call_files)[:10],
            )
        )

    # OBS-008: Env vars missing from .env.example
    referenced_env_vars: Set[str] = set()
    for rel, text in code_only_items:
        for match in ENV_VAR_PATTERN.finditer(text):
            var = match.group(1)
            # Only count actual env access patterns nearby or standard prefixes
            if any(
                token in text
                for token in (f"process.env.{var}", f"import.meta.env.{var}", f'getenv("{var}")', f"getenv('{var}')", f'environ["{var}"]', f"environ['{var}']")
            ):
                referenced_env_vars.add(var)

    has_env_example, documented_env_vars = parse_env_example(root)
    missing_env_vars = sorted(referenced_env_vars - documented_env_vars)
    if missing_env_vars:
        findings.append(
            Finding(
                id="OBS-008",
                severity="MEDIUM",
                title="Observability environment variables missing from .env.example",
                detail=(
                    f"Missing keys: {', '.join(missing_env_vars)}"
                    if has_env_example
                    else f"No .env.example found; referenced keys: {', '.join(missing_env_vars)}"
                ),
                remediation="Add every required observability variable (with empty placeholders) to `.env.example` so deployments never silently drop telemetry.",
                files=[".env.example"] if has_env_example else [],
            )
        )

    # OBS-009: PostHog cost guardrail (person_profiles)
    if providers["posthog"] and re.search(r"posthog\.init\s*\(", all_text):
        if "person_profiles" not in all_text:
            findings.append(
                Finding(
                    id="OBS-009",
                    severity="LOW",
                    title="PostHog initialization missing `person_profiles: 'identified_only'`",
                    detail="Without `person_profiles: 'identified_only'`, anonymous bounce visitors can generate costly person profiles.",
                    remediation="Add `person_profiles: 'identified_only'` to `posthog.init(...)` to significantly cut PostHog event cost.",
                    files=[rel for rel, text in code_only_items if "posthog.init" in text],
                )
            )

    # OBS-010: Backend blind spot (health check & structured logging)
    if has_backend:
        missing_backend_bits: List[str] = []
        if not has_health_route:
            missing_backend_bits.append("liveness endpoint (/api/health or /healthz)")
        if not has_structured_logger:
            missing_backend_bits.append("structured JSON logger (e.g. pino / structlog)")
        if missing_backend_bits:
            findings.append(
                Finding(
                    id="OBS-010",
                    severity="LOW",
                    title="Backend observability gap detected",
                    detail=f"Backend/API code detected without: {', '.join(missing_backend_bits)}. Client SDKs cannot report 502s or failed webhooks.",
                    remediation="Add a fast `/api/health` route for external uptime monitoring and adopt structured JSON logging with `request_id` correlation.",
                    files=[],
                )
            )

    # OBS-011: No environment isolation guard detected
    any_client_provider = any(providers[k] for k in ("sentry", "posthog", "ga4", "clarity"))
    if any_client_provider:
        init_files = [
            rel
            for rel, text in code_only_items
            if re.search(r"(Sentry|posthog|Clarity)\.init\s*\(|gtag\s*\(\s*['\"]config['\"]", text)
        ]
        guarded = any(
            re.search(r"NODE_ENV|import\.meta\.env\.(PROD|DEV|MODE)|opt_out_capturing|enabled\s*:", file_contents.get(rel, ""))
            for rel in init_files
        )
        if init_files and not guarded:
            findings.append(
                Finding(
                    id="OBS-011",
                    severity="INFO",
                    title="No dev-environment opt-out guard detected in telemetry initialization",
                    detail="Firing telemetry unconditionally on localhost pollutes production funnels and burns error/replay quotas.",
                    remediation="Disable external reporting unless `NODE_ENV === 'production'` (or an explicit `OBSERVABILITY_DEBUG=true` flag is set).",
                    files=sorted(set(init_files)),
                )
            )

    # If zero providers detected at all, report cleanly
    if not any(providers.values()):
        findings.append(
            Finding(
                id="OBS-000",
                severity="INFO",
                title="No observability providers detected yet",
                detail="This repository does not appear to have Sentry, PostHog, GA4, Clarity, or OpenTelemetry configured yet.",
                remediation="Select a profile (`core`, `marketing`, `full-deduped`, or `ai-app`) and run the `vibe-observability` setup workflow.",
                files=[],
            )
        )

    findings.sort(key=lambda f: (-SEVERITY_RANK[f.severity], f.id))
    score = max(0, 100 - sum(SEVERITY_PENALTY[f.severity] for f in findings))

    return {
        "project_root": str(root),
        "files_scanned": len(file_contents),
        "detected_providers": [k for k, v in providers.items() if v],
        "detected_stack": {
            "nextjs": has_nextjs,
            "backend": has_backend,
            "structured_logger": has_structured_logger,
            "health_route": has_health_route,
        },
        "score": score,
        "summary": {
            sev: sum(1 for f in findings if f.severity == sev)
            for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")
        },
        "findings": [asdict(f) for f in findings],
    }


def render_markdown_report(report: Dict[str, object]) -> str:
    lines: List[str] = []
    providers = report["detected_providers"] or ["(none)"]
    stack = report["detected_stack"]
    summary = report["summary"]

    lines.append(f"Vibe Observability Audit — {report['project_root']}")
    lines.append("=" * 68)
    lines.append(f"Files scanned : {report['files_scanned']}")
    lines.append(f"Providers     : {', '.join(providers)}")
    lines.append(
        f"Stack hints   : nextjs={stack['nextjs']}, backend={stack['backend']}, "
        f"structured_logger={stack['structured_logger']}, health_route={stack['health_route']}"
    )
    lines.append(
        f"Score         : {report['score']}/100  "
        f"(CRITICAL={summary['CRITICAL']} HIGH={summary['HIGH']} "
        f"MEDIUM={summary['MEDIUM']} LOW={summary['LOW']} INFO={summary['INFO']})"
    )
    lines.append("")

    findings = report["findings"]
    if not findings:
        lines.append("PASS: No observability issues found.")
        return "\n".join(lines)

    for f in findings:
        lines.append(f"[{f['severity']}] {f['id']}: {f['title']}")
        lines.append(f"  Detail : {f['detail']}")
        lines.append(f"  Fix    : {f['remediation']}")
        if f["files"]:
            lines.append(f"  Files  : {', '.join(f['files'])}")
        lines.append("")

    return "\n".join(lines).rstrip()


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit a repository's observability setup for common vibe-coding pitfalls."
    )
    parser.add_argument("path", nargs="?", default=".", help="Path to the project root (default: current directory)")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON output for AI agents / CI")
    parser.add_argument(
        "--fail-on",
        choices=("NONE", "CRITICAL", "HIGH", "MEDIUM", "LOW"),
        default="NONE",
        help="Exit non-zero if any finding meets or exceeds this severity (default: NONE)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Shorthand for --fail-on HIGH",
    )
    args = parser.parse_args(argv)

    target = Path(args.path)
    if not target.exists() or not target.is_dir():
        print(f"Error: target path is not an existing directory: {target}", file=sys.stderr)
        return 2

    report = audit_project(target)

    if args.as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render_markdown_report(report))

    threshold_name = "HIGH" if args.strict and args.fail_on == "NONE" else args.fail_on
    if threshold_name != "NONE":
        threshold = SEVERITY_RANK[threshold_name]
        if any(SEVERITY_RANK[f["severity"]] >= threshold for f in report["findings"]):
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
