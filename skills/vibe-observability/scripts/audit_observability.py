#!/usr/bin/env python3
"""Static observability auditor for Web, Edge, Backend, Desktop/Native, and Job repos.

Zero external dependencies (Python 3.9+ stdlib only).
Checks for:
  - OBS-001 (CRITICAL): Hardcoded observability keys/tokens in source files
  - OBS-002 / 002B (HIGH): Dual session-replay conflicts (PostHog + Clarity / Sentry)
  - OBS-003 (HIGH): Unbounded Sentry tracesSampleRate (billing explosion risk)
  - OBS-004 (HIGH): Potential PII sent to GA4 or Sentry sendDefaultPii=true
  - OBS-005 (MEDIUM): Missing PostHog input masking (`maskAllInputs`)
  - OBS-006 / 006B (MEDIUM/LOW): Direct ingestion without first-party reverse proxy / tunnel
  - OBS-007 (MEDIUM): Scattered raw vendor SDK calls instead of a unified telemetry facade
  - OBS-008 (MEDIUM): Observability env vars missing from `.env.example`
  - OBS-009 (LOW): PostHog missing `person_profiles: 'identified_only'` cost guardrail
  - OBS-010 (LOW): Backend missing `/health` probe or structured logger
  - OBS-011 (INFO): Client init missing dev/test environment opt-out guard
  - OBS-012 (HIGH): Desktop/Native app includes web-only GA4 or MS Clarity
  - OBS-013 (HIGH): Serverless/Edge PostHog missing `shutdown()`/`flush()` or `waitUntil()`
  - OBS-014 (HIGH): Auth middleware likely intercepts `/ingest` or `/monitoring` proxy
  - OBS-015 (MEDIUM): Sentry build plugin missing sourcemap deletion after upload
  - OBS-016 (HIGH): Cloudflare Workers importing `@sentry/node` instead of `@sentry/cloudflare`
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
    ".wrangler",
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
    "Pods",
    ".gradle",
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
    ".rs",
    ".swift",
    ".kt",
    ".kts",
    ".html",
    ".htm",
}

CONFIG_FILENAMES: Set[str] = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "go.mod",
    "Cargo.toml",
    "Package.swift",
    "build.gradle",
    "build.gradle.kts",
    "next.config.js",
    "next.config.mjs",
    "next.config.ts",
    "nuxt.config.ts",
    "nuxt.config.js",
    "vite.config.ts",
    "vite.config.js",
    "vite.config.mts",
    "wrangler.toml",
    "wrangler.jsonc",
    "wrangler.json",
    "vercel.json",
    "Caddyfile",
    "wails.json",
    "tauri.conf.json",
    ".oxlintrc.json",
    "oxlint.json",
    "docker-compose.yml",
    "docker-compose.yaml",
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
    if any(p in {"test", "tests", "__tests__", "spec", "specs", "fixtures", "mocks", "e2e"} for p in parts):
        return True
    name = Path(lower).name
    return ".test." in name or ".spec." in name or name.startswith("test_") or name.endswith("_test.go")


def load_project_config(root: Path) -> Tuple[Set[str], Set[str]]:
    """Load optional `.vibe-observability.json` ignore rules and excluded path prefixes."""
    cfg_path = root / ".vibe-observability.json"
    ignored_rules: Set[str] = set()
    exclude_paths: Set[str] = set()
    if not cfg_path.is_file():
        return ignored_rules, exclude_paths
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ignored_rules, exclude_paths
    if isinstance(data, dict):
        for item in data.get("ignore", []) or []:
            if isinstance(item, str) and item.strip():
                ignored_rules.add(item.strip().upper())
        for item in data.get("exclude_paths", []) or []:
            if isinstance(item, str) and item.strip():
                exclude_paths.add(item.strip().replace("\\", "/").lstrip("./"))
    return ignored_rules, exclude_paths


def is_excluded_path(rel_path: str, exclude_paths: Set[str]) -> bool:
    if not exclude_paths:
        return False
    norm = rel_path.replace("\\", "/").lstrip("./")
    for prefix in exclude_paths:
        clean_prefix = prefix.rstrip("/")
        if norm == clean_prefix or norm.startswith(clean_prefix + "/"):
            return True
    return False


def collect_files(root: Path, exclude_paths: Set[str] | None = None) -> Tuple[List[Path], List[Path]]:
    code_files: List[Path] = []
    config_files: List[Path] = []
    excludes = exclude_paths or set()

    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        dirnames[:] = [
            d
            for d in dirnames
            if d not in SKIP_DIRS and not is_excluded_path(f"{rel_dir}/{d}" if rel_dir != "." else d, excludes)
        ]
        for filename in filenames:
            if filename.endswith(".min.js") or filename.endswith(".map"):
                continue
            path = Path(dirpath) / filename
            rel = path.relative_to(root).as_posix()
            if is_excluded_path(rel, excludes):
                continue
            if filename in CONFIG_FILENAMES or filename.startswith("Caddyfile"):
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


def audit_project(root: Path, cli_ignore: Set[str] | None = None) -> Dict[str, object]:
    root = root.resolve()
    cfg_ignore, exclude_paths = load_project_config(root)
    ignored_rules = cfg_ignore | {r.strip().upper() for r in (cli_ignore or set()) if r.strip()}
    code_files, config_files = collect_files(root, exclude_paths=exclude_paths)

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

    pkg_json = file_contents.get("package.json", "")

    # 1. Detect providers & stack characteristics
    providers: Dict[str, bool] = {
        "sentry": bool(
            re.search(
                r"@sentry/|sentry_sdk|getsentry/sentry-go|sentry-cocoa|sentry-android|sentry-tauri|Sentry\.init\(|sentry\.Init\(|sentry_sdk\.init\(|SENTRY_DSN",
                all_text,
            )
        ),
        "posthog": bool(
            re.search(r"posthog-js|posthog-node|posthog-ios|posthog-android|posthog\.init\(|POSTHOG_KEY", all_text)
        ),
        "ga4": bool(
            re.search(
                r"googletagmanager\.com/gtag|@next/third-parties/google|<GoogleAnalytics|\bgtag\(|GA_MEASUREMENT_ID",
                all_text,
            )
        ),
        "clarity": bool(
            re.search(r"@microsoft/clarity|clarity\.ms/tag|CLARITY_PROJECT_ID|Clarity\.init\(", all_text)
        ),
        "opentelemetry": bool(re.search(r"@opentelemetry/|opentelemetry-api|opentelemetry-sdk|go\.opentelemetry\.io", all_text)),
    }

    has_nextjs = any(Path(rel).name.startswith("next.config.") for rel in file_contents) or bool(
        re.search(r'"next"\s*:', pkg_json)
    )
    has_vite = any(Path(rel).name.startswith("vite.config.") for rel in file_contents) or bool(
        re.search(r'"vite"\s*:', pkg_json)
    )
    has_cloudflare_workers = any(
        Path(rel).name in {"wrangler.toml", "wrangler.jsonc", "wrangler.json"} for rel in file_contents
    ) or bool(re.search(r"@sentry/cloudflare|@cloudflare/workers-types|ExecutionContext|CF_VERSION_METADATA", all_text))
    has_go = any(Path(rel).suffix == ".go" or Path(rel).name == "go.mod" for rel in file_contents)
    has_python = any(Path(rel).suffix == ".py" or Path(rel).name == "pyproject.toml" for rel in file_contents)
    has_desktop_native = (
        any(Path(rel).name in {"wails.json", "tauri.conf.json", "Package.swift"} for rel in file_contents)
        or any(Path(rel).suffix in {".swift", ".kt", ".kts"} for rel in file_contents)
        or bool(re.search(r'"electron"\s*:|"@tauri-apps/|@sentry/electron|wailsapp/wails', all_text))
    )
    has_oxlint = any(Path(rel).name in {".oxlintrc.json", "oxlint.json"} for rel in file_contents) or bool(
        re.search(r'"oxlint"\s*:', pkg_json)
    )

    has_backend = (
        has_cloudflare_workers
        or has_go
        or bool(
            re.search(
                r"FastAPI\(|express\(|fastify\(|new Hono\(|gin\.Default\(|gin\.New\(|app/api/|pages/api/|uvicorn|gunicorn",
                all_text,
            )
        )
        or any(
            ("/api/" in rel.replace("\\", "/") or rel.replace("\\", "/").startswith("api/") or rel.startswith("server/"))
            for rel in file_contents
        )
    )

    has_structured_logger = bool(
        re.search(
            r"\b(pino|winston|structlog|loguru|zerolog|bunyan|tracing_subscriber|electron-log|OSLog)\b|log/slog|slog\.NewJSONHandler|JSON\.stringify\(\{\s*ts:|observability\s*[:=]\s*\{[^}]*enabled\s*:\s*true",
            all_text,
        )
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
    posthog_replay_disabled = bool(
        re.search(r"disable_session_recording\s*:\s*(?!false\b)[^\n,}]+", all_text)
    )
    posthog_replay_always_off = bool(re.search(r"disable_session_recording\s*:\s*true\b", all_text))
    sentry_replay_enabled = bool(
        re.search(
            r"replayIntegration\s*\(|replaysSessionSampleRate\s*:\s*0?\.[1-9]|replaysSessionSampleRate\s*:\s*1\b",
            all_text,
        )
    )

    if providers["posthog"] and providers["clarity"] and not posthog_replay_disabled:
        findings.append(
            Finding(
                id="OBS-002",
                severity="HIGH",
                title="Dual session-replay conflict: PostHog Replay + Microsoft Clarity both active",
                detail="Running both PostHog Session Replay and Clarity duplicates DOM MutationObservers, hurting LCP/INP and wasting PostHog replay quota.",
                remediation="Set `disable_session_recording: true` (or guard dynamically on Clarity ID) in `posthog.init(...)`, or drop Clarity and use PostHog Replay alone.",
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
            if re.search(r"(?:tracesSampleRate|TracesSampleRate|traces_sample_rate)\s*[:=]\s*1(?:\.0)?\b", line):
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
                remediation="Use an environment-aware sample rate such as `0.1` in production and `0` in dev (or drive it from an env var).",
                files=sorted(set(unbounded_sentry_files)),
            )
        )

    # OBS-004: Potential PII leakage to GA4 / Sentry
    pii_files: List[str] = []
    for rel, text in code_only_items:
        if re.search(r"sendDefaultPii\s*:\s*true|SendDefaultPII\s*:\s*true|send_default_pii\s*=\s*True", text):
            pii_files.append(f"{rel} (Sentry sendDefaultPii=true)")
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

    # OBS-005: PostHog replay missing input masking (browser init only)
    has_browser_posthog = bool(re.search(r"posthog\.init\s*\(", all_text))
    if has_browser_posthog and not posthog_replay_always_off:
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
                remediation="Route browser ingestion through a neutral same-origin proxy path such as `/ingest` (via Hono/Workers, Caddy, Nginx, or framework rewrites).",
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
                remediation="Consolidate tracking behind a typed `telemetry` facade and enforce it via oxlint/ESLint `no-restricted-imports`.",
                files=sorted(raw_call_files)[:10],
            )
        )

    # OBS-008: Env vars missing from .env.example
    referenced_env_vars: Set[str] = set()
    for rel, text in code_only_items:
        for match in ENV_VAR_PATTERN.finditer(text):
            var = match.group(1)
            if any(
                token in text
                for token in (
                    f"process.env.{var}",
                    f"import.meta.env.{var}",
                    f"env.{var}",
                    f'getenv("{var}")',
                    f"getenv('{var}')",
                    f'Getenv("{var}")',
                    f'environ["{var}"]',
                    f"environ['{var}']",
                )
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
    if has_browser_posthog and "person_profiles" not in all_text:
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
            missing_backend_bits.append("structured JSON logger (e.g. slog / pino / structlog)")
        if missing_backend_bits:
            findings.append(
                Finding(
                    id="OBS-010",
                    severity="LOW",
                    title="Backend observability gap detected",
                    detail=f"Backend/API code detected without: {', '.join(missing_backend_bits)}. Client SDKs cannot report 502s or failed webhooks.",
                    remediation="Add a fast `/api/health` or `/healthz` route for external uptime monitoring and adopt structured JSON logging with `request_id` correlation.",
                    files=[],
                )
            )

    # OBS-011: No dev-environment guard detected
    any_client_provider = any(providers[k] for k in ("sentry", "posthog", "ga4", "clarity"))
    if any_client_provider:
        init_files = [
            rel
            for rel, text in code_only_items
            if re.search(r"(?:Sentry|posthog|Clarity)\.init\s*\(|sentry\.Init\(|sentry_sdk\.init\(|gtag\s*\(\s*['\"]config['\"]", text)
        ]
        guarded = any(
            re.search(
                r"NODE_ENV|APP_ENV|import\.meta\.env\.(PROD|DEV|MODE)|opt_out_capturing|enabled\s*:|env\s*!=\s*\"production\"|app_env\s*!=\s*\"production\"",
                file_contents.get(rel, ""),
            )
            for rel in init_files
        )
        if init_files and not guarded:
            findings.append(
                Finding(
                    id="OBS-011",
                    severity="INFO",
                    title="No dev-environment opt-out guard detected in telemetry initialization",
                    detail="Firing telemetry unconditionally on localhost pollutes production funnels and burns error/replay quotas.",
                    remediation="Disable external reporting unless running in production (or an explicit `OBSERVABILITY_DEBUG=true` flag is set).",
                    files=sorted(set(init_files)),
                )
            )

    # OBS-012: Desktop / Native app using web-only GA4 or MS Clarity
    if has_desktop_native and (providers["ga4"] or providers["clarity"]):
        offenders = [
            rel
            for rel, text in code_only_items
            if re.search(r"googletagmanager|@microsoft/clarity|clarity\.ms|\bgtag\(|Clarity\.init", text)
        ]
        findings.append(
            Finding(
                id="OBS-012",
                severity="HIGH",
                title="Web-only tracker (GA4 / Microsoft Clarity) detected in Desktop/Native app",
                detail="GA4 and Clarity break on custom app protocols (wails://, tauri://, app://) and trigger user privacy backlash in desktop/native tools.",
                remediation="Remove GA4 and Clarity; use native crash capture (Sentry / MetricKit), local rotating diagnostic logs, and opt-out anonymous events only.",
                files=sorted(set(offenders)),
            )
        )

    # OBS-013: Serverless / Edge PostHog missing flush/shutdown/waitUntil
    server_ph_files = [
        rel
        for rel, text in code_only_items
        if re.search(r"posthog-node|new\s+PostHog\s*\(", text)
    ]
    if server_ph_files and (has_cloudflare_workers or has_nextjs or "vercel.json" in file_contents):
        has_flush = any(
            re.search(r"\.(shutdown|flush)\s*\(|waitUntil\s*\(", file_contents.get(rel, ""))
            for rel in server_ph_files
        ) or bool(re.search(r"posthog\.(shutdown|flush)\s*\(", all_text))
        if not has_flush:
            findings.append(
                Finding(
                    id="OBS-013",
                    severity="HIGH",
                    title="Server-side PostHog in Serverless/Edge runtime missing `shutdown()`/`flush()` or `waitUntil()`",
                    detail="Short-lived isolates (Cloudflare Workers, Vercel/Lambda) freeze immediately after sending the HTTP response, dropping buffered PostHog events.",
                    remediation="Wrap `posthog.shutdown()` (or capture fetch) inside `ctx.waitUntil(...)` on Workers, or `await posthog.shutdown()` before returning in serverless handlers.",
                    files=sorted(set(server_ph_files)),
                )
            )

    # OBS-014: Middleware potentially intercepting /ingest or /monitoring reverse proxy
    uses_proxy_paths = bool(re.search(r"""['"]/ingest\b|tunnelRoute\s*:\s*['"]/monitoring['"]""", all_text))
    if uses_proxy_paths:
        middleware_files = [
            (rel, text)
            for rel, text in code_only_items
            if Path(rel).stem in {"middleware", "proxy"} and "matcher" in text
        ]
        blocking_mw = [
            rel
            for rel, text in middleware_files
            if ("/ingest" in all_text and "ingest" not in text)
            or ("/monitoring" in all_text and "monitoring" not in text)
        ]
        if blocking_mw:
            findings.append(
                Finding(
                    id="OBS-014",
                    severity="HIGH",
                    title="Auth/routing middleware matcher does not exclude `/ingest` or `/monitoring`",
                    detail="If middleware redirects unauthenticated requests to `/login`, first-party PostHog `/ingest` and Sentry `/monitoring` traffic silently dies with 302/307.",
                    remediation="Exclude `ingest`, `monitoring`, and `api/health` from your middleware `matcher` regex, then confirm with `verify_live.py`.",
                    files=sorted(set(blocking_mw)),
                )
            )

    # OBS-015: Sentry build plugin missing sourcemap deletion after upload
    sentry_build_files = [
        rel
        for rel, text in file_contents.items()
        if re.search(r"\b(withSentryConfig|sentryVitePlugin)\s*\(", text)
    ]
    if sentry_build_files:
        deletes_maps = any(
            re.search(r"deleteSourcemapsAfterUpload\s*:\s*true|filesToDeleteAfterUpload", file_contents.get(rel, ""))
            for rel in sentry_build_files
        )
        if not deletes_maps:
            findings.append(
                Finding(
                    id="OBS-015",
                    severity="MEDIUM",
                    title="Sentry build plugin does not delete source maps after upload",
                    detail="Uploading source maps without deleting them from build output can expose your original source code publicly via `.js.map` URLs.",
                    remediation="Set `sourcemaps: { deleteSourcemapsAfterUpload: true }` (Next.js) or `sourcemaps: { filesToDeleteAfterUpload: ['./dist/**/*.map'] }` (Vite).",
                    files=sorted(set(sentry_build_files)),
                )
            )

    # OBS-016: Cloudflare Workers importing @sentry/node
    if has_cloudflare_workers:
        bad_worker_sentry = [
            rel for rel, text in code_only_items if re.search(r"""['"]@sentry/node['"]""", text)
        ]
        if bad_worker_sentry:
            findings.append(
                Finding(
                    id="OBS-016",
                    severity="HIGH",
                    title="Cloudflare Workers project imports `@sentry/node` instead of `@sentry/cloudflare`",
                    detail="`@sentry/node` relies on Node runtime assumptions that break or drop isolate context on Cloudflare Workers.",
                    remediation="Replace `@sentry/node` with `@sentry/cloudflare` (`Sentry.withSentry(...)`) and enable `nodejs_compat` in Wrangler.",
                    files=sorted(set(bad_worker_sentry)),
                )
            )

    # Zero providers detected
    if not any(providers.values()):
        findings.append(
            Finding(
                id="OBS-000",
                severity="INFO",
                title="No observability providers detected yet",
                detail="This repository does not appear to have Sentry, PostHog, GA4, Clarity, or OpenTelemetry configured yet.",
                remediation="Select a profile matching your runtime (`core`, `marketing`, `full-deduped`, `ai-app`, `selfhosted-infra`, `desktop-native`, or `batch-jobs`) and follow `vibe-observability`.",
                files=[],
            )
        )

    suppressed_ids = sorted({f.id for f in findings if f.id.upper() in ignored_rules})
    findings = [f for f in findings if f.id.upper() not in ignored_rules]
    findings.sort(key=lambda f: (-SEVERITY_RANK[f.severity], f.id))
    instrumented = any(providers.values())
    score = max(0, 100 - sum(SEVERITY_PENALTY[f.severity] for f in findings)) if instrumented else None

    return {
        "project_root": str(root),
        "files_scanned": len(file_contents),
        "instrumented": instrumented,
        "detected_providers": [k for k, v in providers.items() if v],
        "detected_stack": {
            "vite": has_vite,
            "nextjs": has_nextjs,
            "cloudflare_workers": has_cloudflare_workers,
            "go_backend": has_go,
            "python": has_python,
            "desktop_native": has_desktop_native,
            "oxlint": has_oxlint,
            "backend": has_backend,
            "structured_logger": has_structured_logger,
            "health_route": has_health_route,
        },
        "ignored_rules": sorted(ignored_rules),
        "suppressed_findings": suppressed_ids,
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
    active_stack = [k for k, v in stack.items() if v]
    score_str = f"{report['score']}/100" if report["score"] is not None else "N/A (not instrumented yet)"

    lines.append(f"Vibe Observability Audit — {report['project_root']}")
    lines.append("=" * 68)
    lines.append(f"Files scanned : {report['files_scanned']}")
    lines.append(f"Providers     : {', '.join(providers)}")
    lines.append(f"Stack hints   : {', '.join(active_stack) if active_stack else '(generic)'}")
    if report.get("ignored_rules"):
        lines.append(f"Ignored rules : {', '.join(report['ignored_rules'])}")
    lines.append(
        f"Score         : {score_str}  "
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
        description="Audit a repository's observability setup across Web, Edge, Backend, Desktop/Native, and Job stacks."
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
    parser.add_argument(
        "--ignore",
        action="append",
        default=[],
        help="Comma-separated rule IDs to ignore (e.g. --ignore OBS-006B,OBS-010); merges with .vibe-observability.json",
    )
    args = parser.parse_args(argv)

    target = Path(args.path)
    if not target.exists() or not target.is_dir():
        print(f"Error: target path is not an existing directory: {target}", file=sys.stderr)
        return 2

    cli_ignore: Set[str] = set()
    for raw in args.ignore:
        for item in raw.split(","):
            if item.strip():
                cli_ignore.add(item.strip().upper())

    report = audit_project(target, cli_ignore=cli_ignore)

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
