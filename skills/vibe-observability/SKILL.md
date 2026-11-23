---
name: vibe-observability
description: >-
  Instrument web SPAs, edge workers, full-stack services, self-hosted backends,
  desktop/native apps, AI apps, and automation scripts with production-grade
  observability (Sentry, PostHog, GA4, Microsoft Clarity, structured logs,
  Prometheus/Pigsty/OpenTelemetry, health probes, and cron monitors) without
  bloat, privacy leaks, or billing surprises. Activate when the user asks to
  add observability, set up analytics/tracking/error monitoring, wire up
  Sentry/PostHog/GA/Clarity, audit an existing telemetry setup, or
  "把可观测性拉满 / 接埋点和监控".
---

# Vibe Observability

Framework-agnostic runbook for adding lean, privacy-safe, cost-bounded
observability across modern full-stack, edge, self-hosted, desktop/native, AI,
and batch-job codebases.

## Core Principles

1. **Match telemetry to the runtime — never force web trackers onto non-web apps.**
   Never install GA4 or Microsoft Clarity in Electron, Wails, Tauri, iOS,
   Android, or backend jobs.
2. **Never stack two session-replay SDKs at once.** Running PostHog Session
   Replay, Microsoft Clarity, or Sentry Replay simultaneously duplicates DOM
   observers, hurts Core Web Vitals, and wastes quota.
3. **One typed facade, zero scattered SDK calls.** Application code imports one
   `telemetry` module (`track`, `identify`, `reset`, `captureError`), enforced
   by linter rules (e.g. Oxc `oxlint` / ESLint `no-restricted-imports`).
4. **Cross-link errors, traces, and sessions.** Share opaque `userId` and
   `X-Request-Id` across frontend, backend logs, Sentry, and PostHog so crashes
   link straight to session replays and server logs.
5. **Guardrails by default.** First-party reverse proxy / tunnel against
   AdBlockers, strict PII scrubbing, dev/test opt-out, explicit flush in
   serverless/edge runtimes (`ctx.waitUntil`), and bounded sampling budgets.

---

## Step-by-Step Workflow

### Step 1: Detect Stack, Runtime & Existing Telemetry

Inspect manifests (`package.json`, `wrangler.toml`/`wrangler.jsonc`, `go.mod`,
`Cargo.toml`, `pyproject.toml`, `Package.swift`, `build.gradle*`, `Caddyfile`,
`docker-compose.yml`), `.env.example`, and existing SDK imports.

If the repo already has partial telemetry, run the static auditor first:

```bash
python3 <skill_dir>/scripts/audit_observability.py <project_root>
```

Classify the target into one or more runtime shapes:
- **Web SPA / Full-Stack JS**: Vite + React/Vue/Svelte, TanStack Router/Query/Start, Hono, Better Auth, Oxc
- **Cloudflare Edge**: Workers, Hono, D1, KV, Queues, R2
- **SSR Meta-Framework**: Next.js, Nuxt, SvelteKit, Astro
- **Self-Hosted Backend / High Concurrency**: Go + Gin + Caddy, Node/FastAPI, Pigsty (PG + `pgmq` + Valkey + RustFS), OpenTelemetry
- **Desktop / Native Client**: Electron, Go + Wails v3, Rust (Tauri 2 / Win32), Swift (macOS/iOS), Kotlin (Android)
- **Data Scraping / Automation Jobs**: Python + `uv`, scheduled scrapers, batch pipelines

### Step 2: Select an Observability Profile

Read [references/profiles.md](./references/profiles.md). Default to the lightest
non-overlapping profile for the detected runtime:

- **`core`** *(default for Web/SaaS)*: Sentry + PostHog + structured backend logs & `/api/health`.
- **`marketing`** *(SEO / landing / ads)*: Sentry + GA4 + MS Clarity + `/api/health`.
- **`full-deduped`** *(growth + ads + product)*: Sentry + PostHog (*replay OFF*) + GA4 + MS Clarity (*replay ON*) + backend logs.
- **`ai-app`** *(LLM / agent apps)*: `core` + LLM generation telemetry (`$ai_generation`, TTFT, tokens, cost, feedback).
- **`desktop-native`** *(Electron / Wails / Tauri / Swift / Kotlin)*: Native crash reporting (Sentry / MetricKit) + local rotating diagnostic logs + opt-out anonymous events (NO GA4, NO Clarity, NO silent replay).
- **`selfhosted-infra`** *(Go/Gin + Caddy + Pigsty/Prometheus)*: `log/slog` + Sentry + `/metrics` into Pigsty/Prometheus + `pgmq`/Valkey health + Caddy `/ingest` proxy.
- **`batch-jobs`** *(Python + `uv` scrapers/workers)*: `structlog` JSON + Sentry Crons dead-man's switch + structured Run Summary & volume-drop anomaly alerts.

### Step 3: Load Only the Matching Stack Adapter(s)

Use progressive disclosure — read **only** the adapter(s) matching Step 1:

- Vite + React + TanStack + Hono + Better Auth + Oxc + Web Vitals:
  [references/stack-web-vite-tanstack.md](./references/stack-web-vite-tanstack.md)
- Cloudflare Workers + Hono + D1/KV/Queues/R2:
  [references/stack-cloudflare-edge.md](./references/stack-cloudflare-edge.md)
- Go + Gin + Caddy + Pigsty + `pgmq` + OpenTelemetry path:
  [references/stack-go-selfhosted.md](./references/stack-go-selfhosted.md)
- Electron, Wails v3, Tauri 2 / Rust, Swift (macOS/iOS), Kotlin (Android):
  [references/stack-desktop-native.md](./references/stack-desktop-native.md)
- Python + `uv` scrapers & automation jobs:
  [references/stack-python-jobs.md](./references/stack-python-jobs.md)
- Next.js, Nuxt, SvelteKit, Astro SSR:
  [references/stack-ssr-metaframeworks.md](./references/stack-ssr-metaframeworks.md)

### Step 4: Build the Unified Facade & Wire Providers with Guardrails

Read these core references as needed:
- Facade & Sentry ↔ PostHog cross-linking: [references/telemetry-facade.md](./references/telemetry-facade.md)
- Event taxonomy (`object_action` snake_case): [references/event-taxonomy.md](./references/event-taxonomy.md)
- Privacy, PII scrubbing, dev/test opt-out & cost limits: [references/privacy-and-cost.md](./references/privacy-and-cost.md)
- Vendor specifics (load only those in the selected profile):
  - [references/sentry.md](./references/sentry.md)
  - [references/posthog.md](./references/posthog.md)
  - [references/ga4-clarity.md](./references/ga4-clarity.md)
  - [references/backend-and-uptime.md](./references/backend-and-uptime.md)

Self-contained starter implementations live in [examples/](./examples/):
- [examples/vite-tanstack-hono/telemetry.ts](./examples/vite-tanstack-hono/telemetry.ts)
- [examples/cloudflare-workers-hono/observability.ts](./examples/cloudflare-workers-hono/observability.ts)
- [examples/go-gin-caddy/observability.go](./examples/go-gin-caddy/observability.go) & [examples/go-gin-caddy/Caddyfile.snippet](./examples/go-gin-caddy/Caddyfile.snippet)
- [examples/python-uv-job/job_telemetry.py](./examples/python-uv-job/job_telemetry.py)
- [examples/nextjs-app-router/telemetry.ts](./examples/nextjs-app-router/telemetry.ts)

### Step 5: Static Audit, Build Check & Live Smoke Verification (Mandatory)

1. Document every new environment variable (with empty placeholders) in
   `.env.example`.
2. Run the bundled static auditor and fix every `CRITICAL` and `HIGH` finding:
   ```bash
   python3 <skill_dir>/scripts/audit_observability.py <project_root> --strict
   ```
3. Run the project's lint, typecheck, and build/test commands (e.g. `pnpm lint`,
   `oxlint`, `tsrs`/`tsc`, `vitest`, `go test ./...`, `uv run pytest`).
4. If the app has a live staging or production URL, run the post-deploy smoke
   verifier to catch middleware redirects on `/ingest`, leaked `.js.map` files,
   broken `/api/health`, or blocking CSP headers:
   ```bash
   python3 <skill_dir>/scripts/verify_live.py https://<your-domain>
   ```
5. Hand off a concise **Activation Checklist** (env vars, provider billing cap
   reminder, and how to trigger `vibe-observability-loop` once live signals
   arrive).
