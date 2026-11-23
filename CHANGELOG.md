# Changelog

All notable changes to `vibe-observability` are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/).

## [0.3.0] - 2026-11-23

### Added
- Unified zero-dependency `vibe-obs` CLI (`pyproject.toml` + `src/vibe_observability/`) supporting instant `uvx --from git+... vibe-obs audit|verify|pull` usage with single-source wheel bundling.
- Rule suppression and path exclusion in `audit_observability.py` via `--ignore` CLI flag and project-root `.vibe-observability.json`.
- Read-only Microsoft Clarity Live Insights API and Prometheus/Pigsty PromQL support in `pull_signals.py`.
- Reproducible Before-vs-After benchmark (`evals/run_benchmark.py`).
- Open-source governance files: `SECURITY.md`, `CHANGELOG.md`, GitHub Issue templates (bug/false-positive & stack adapter request), and PR template.

### Changed
- Removed remaining `NEXT_PUBLIC_*` defaults from core vendor references (`sentry.md`, `posthog.md`, `ga4-clarity.md`, `privacy-and-cost.md`) for full framework neutrality.
- Upgraded `README.md` and `README_ZH.md` to full bilingual parity with real CLI demo outputs, benchmark table, and `uvx` quickstart.

## [0.2.0] - 2026-11-23

### Added
- Self-contained skill packaging (`examples/` moved inside `skills/vibe-observability/`).
- Six progressive-disclosure stack adapters: Vite/TanStack/Hono/Oxc, Cloudflare Workers, Go/Gin/Caddy/Pigsty/OpenTelemetry, Desktop/Native (Electron, Wails v3, Tauri 2, Swift, Kotlin), Python + `uv` jobs, and SSR meta-frameworks.
- Five self-contained starter examples scoring 100/100 on the static auditor.
- Five new static audit rules (`OBS-012` through `OBS-016`) and `N/A` score semantics for uninstrumented repositories.
- Post-deploy live smoke verifier (`verify_live.py`) checking `/api/health`, `/ingest` auth redirects, `/monitoring` tunnel, public `.js.map` leaks, and CSP headers.
- Read-only production signal puller (`pull_signals.py`) and MCP/API setup guide (`mcp-and-apis.md`) for `vibe-observability-loop`.
- Strict zero-warning CI (`python3 -W error`).

## [0.1.0] - 2026-11-22

### Added
- Initial release of `vibe-observability` and `vibe-observability-loop` Agent Skills.
- Core static auditor (`OBS-001`–`OBS-011`), cross-agent `install.sh`, and unit test suite.
