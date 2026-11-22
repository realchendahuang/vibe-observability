---
name: vibe-observability
description: >-
  Instrument web, full-stack, and AI applications with production-grade product
  and engineering observability (Sentry, PostHog, GA4, Microsoft Clarity,
  structured backend logs, health probes, and LLM telemetry) without bloat or
  billing surprises. Activate when the user asks to add observability, set up
  analytics/tracking/error monitoring, wire up Sentry/PostHog/GA/Clarity, or
  "把可观测性拉满 / 接埋点和监控" in a project.
---

# Vibe Observability

End-to-end runbook for adding lean, privacy-safe, cost-bounded observability to
products built rapidly with AI (Vibe Coding). Avoids the classic mistake of
dumping four overlapping client SDKs onto the page with no facade, no privacy
masking, and no backend visibility.

## Core Principles

1. **Never stack two session-replay SDKs at once.** Running PostHog Session
   Replay and Microsoft Clarity simultaneously doubles DOM MutationObserver load
   and hurts Core Web Vitals. Always pick a mutually-exclusive profile.
2. **One typed facade, zero scattered SDK calls.** Application code calls a
   single `telemetry` module (`track`, `identify`, `reset`, `captureError`),
   never raw `posthog.capture()` or `gtag()` across components.
3. **Cross-link errors to user sessions.** Attach the analytics user/session ID
   to Sentry scope so every crash links straight to the user's replay and funnel.
4. **Guardrails by default.** First-party reverse proxy / tunnel against
   AdBlockers, strict PII scrubbing, dev-environment opt-out, and explicit
   sampling budgets to prevent runaway bills from accidental render loops.
5. **Cover the backend blind spot.** Client SDKs go completely dark on 502s,
   broken webhooks, or expired TLS certs. Pair frontend telemetry with
   structured JSON logs, request correlation IDs, and a `/health` endpoint.

---

## Step-by-Step Workflow

### Step 1: Detect Stack & Existing Telemetry

Inspect the target repository first (e.g. `package.json`, `pyproject.toml`,
framework configs, existing `.env.example`, and any existing SDK imports).
Identify:

- **Frontend framework**: Next.js (App Router vs Pages), Vite + React/Vue,
  Astro, SvelteKit, static HTML, etc.
- **Backend / API layer**: Next.js API routes / Server Actions, Node (Express,
  Fastify, Hono), Python (FastAPI, Django), Go, etc.
- **AI / LLM calls**: OpenAI, Anthropic, Gemini, Vercel AI SDK, LangChain, etc.
- **Existing observability**: Any Sentry, PostHog, GA4, Clarity, OpenTelemetry,
  or logging setup already in place.

If this is an existing project with partial telemetry, run the audit script
first to map current gaps:

```bash
python3 <skill_dir>/scripts/audit_observability.py <project_root>
```

### Step 2: Select an Observability Profile

Read [references/profiles.md](./references/profiles.md) and select the lightest
profile that fits the product. Ask the user only if their intent is ambiguous;
otherwise default to **`core`** (or **`ai-app`** when LLM calls are detected):

- **`core` (Default for SaaS / Web Apps)**: Sentry + PostHog (errors, events,
  funnels, session replay, feature flags) + backend logs & `/health`.
- **`marketing` (Content / Landing / SEO Sites)**: Sentry + GA4 + MS Clarity
  (acquisition attribution, heatmaps, rage clicks, generous free tiers).
- **`full-deduped` (Growth + Attribution + Product)**: Sentry + PostHog
  (*session replay disabled*) + GA4 + MS Clarity (*owns replay & heatmaps*).
- **`ai-app` (LLM / Agent Products)**: `core` + LLM generation telemetry
  (latency, TTFT, tokens, cost, model/prompt version, user feedback score).

### Step 3: Build the Unified Telemetry Facade & Event Catalog

Before wiring any vendor SDK, read:
- [references/telemetry-facade.md](./references/telemetry-facade.md)
- [references/event-taxonomy.md](./references/event-taxonomy.md)

Create:
1. A central typed telemetry module (e.g. `src/lib/telemetry/index.ts` and
   `src/lib/telemetry/events.ts`), using the matching starter in the repo's
   `templates/` directory if helpful.
2. A concise event taxonomy using `object_action` snake_case naming (e.g.
   `signup_completed`, `checkout_failed`, `generation_requested`).
3. Cross-tool identity propagation (`identify(userId, safeTraits)` updates both
   analytics and Sentry user context; `reset()` clears both on logout).

### Step 4: Wire Selected Providers with Guardrails

Load **only** the reference docs required for the chosen profile:

- Sentry setup, Source Maps, Tunnel, Error Boundaries:
  [references/sentry.md](./references/sentry.md)
- PostHog setup, SPA pageviews, `/ingest` reverse proxy, LLM analytics:
  [references/posthog.md](./references/posthog.md)
- GA4 + Microsoft Clarity async loading, Consent Mode, deduped replay:
  [references/ga4-clarity.md](./references/ga4-clarity.md)
- Mandatory privacy, PII scrubbing, dev isolation, and cost limits:
  [references/privacy-and-cost.md](./references/privacy-and-cost.md)

### Step 5: Close the Backend & Uptime Blind Spot

If the project has a server, API routes, background jobs, or webhooks, read
[references/backend-and-uptime.md](./references/backend-and-uptime.md) and add:

1. Structured JSON logging (`pino` for Node/TS, `structlog` for Python).
2. `X-Request-Id` / `traceparent` propagation from client requests to server
   logs and Sentry tags.
3. Lightweight `/api/health` (or `/healthz`) liveness endpoint plus an external
   uptime monitor checklist in the setup summary.

### Step 6: Audit & Verification Checklist (Mandatory)

1. Update `.env.example` with every new environment variable, grouped by
   provider, with clear comments and empty placeholder values (never real keys).
2. Run the bundled static auditor against the target repo:
   ```bash
   python3 <skill_dir>/scripts/audit_observability.py <project_root>
   ```
3. Resolve every `CRITICAL` and `HIGH` finding before finishing.
4. Run the project's typecheck/build command (e.g. `npm run build`, `tsc --noEmit`,
   or `pytest`) to confirm zero SSR/hydration or import regressions.
5. Present the user a crisp **Activation & Smoke-Test Checklist**:
   - Exact env vars to fill in production
   - How to verify a test error reaches Sentry with source maps
   - How to verify a test event reaches PostHog / GA4 and respects dev opt-out
   - Reminder that once live data arrives, they can trigger the companion
     `vibe-observability-loop` skill to analyze issues and ship data-backed fixes.
