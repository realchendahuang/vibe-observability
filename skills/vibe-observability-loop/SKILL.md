---
name: vibe-observability-loop
description: >-
  Close the self-improving AI feedback loop ("左脚踩右脚"): pull or ingest live
  production signals from Sentry, PostHog, GA4, Microsoft Clarity, Pigsty /
  Prometheus, backend logs, and Python job run summaries; correlate errors,
  funnel drop-offs, rage clicks, queue backlogs, and LLM cost spikes against
  the codebase; prioritize root-cause fixes; and define post-deploy
  verification metrics. Activate when the user asks to analyze production data,
  investigate Sentry errors or PostHog funnels, review Clarity rage clicks,
  debug queue/scraper regressions, or run an observability-driven optimization
  cycle.
---

# Vibe Observability Loop (Data -> AI Diagnosis -> Fix -> Verify)

Instrumentation without a feedback loop is just a prettier dashboard. This skill
turns real production signals into prioritized, evidence-backed code changes and
prevents "fake optimizations" by enforcing post-deploy metric verification.

## Signal Ingestion Modes

1. **Live MCP Mode (Best Interactive Experience)**: Query connected MCP servers
   directly (Sentry MCP / Antigravity Sentry plugin, PostHog MCP). See
   [references/mcp-and-apis.md](./references/mcp-and-apis.md).
2. **One-Command Read-Only Puller (Zero MCP Overhead)**: Run the bundled
   zero-dependency script using read-only tokens and/or local job history files
   to generate a compact AI-ready signal brief:
   ```bash
   python3 <skill_dir>/scripts/pull_signals.py --days 7
   # Optional: include Python scraper JSONL run summaries:
   python3 <skill_dir>/scripts/pull_signals.py --days 7 --job-history ./logs/runs.jsonl
   ```
3. **Snapshot Mode (Zero Credentials)**: Accept pasted error stacks, Sentry
   JSON, PostHog funnel exports, Clarity Rage Click summaries, Pigsty/Grafana
   alerts, or desktop diagnostic log zips directly from the user.

Never fabricate live metrics. If a source is neither connected nor provided,
state exactly what is missing and request the smallest export needed.

---

## 5-Step Optimization Loop

### Step 1: Collect Multi-Signal Evidence

Gather the last 24h–7d signals across the buckets relevant to the runtime:

1. **Reliability & Infra (Sentry, Backend Logs, Pigsty/Prometheus, Queues)**:
   Top unresolved issues by **unique affected users**, regressions introduced in
   the latest `release`, p95 API latency spikes, Cloudflare Queues DLQ or
   `pgmq` `oldest_msg_age_sec` growth, and native crash/ANR clusters.
2. **Conversion & Retention (PostHog / GA4)**: Biggest step-to-step funnel
   drop-offs (`signup_started -> signup_completed -> activation_achieved ->
   checkout_started -> subscription_activated`), segmented by device/browser.
3. **UX Friction (Clarity / PostHog Replay)**: Routes and CSS selectors with
   elevated **Rage Clicks**, **Dead Clicks**, **Quick Backs**, or poor Web
   Vitals (`LCP` / `INP` / `CLS`).
4. **AI Economics & Job Health (`ai-app` & `batch-jobs`)**: High `ttft_ms`,
   token/cost outliers per user, negative `generation_feedback_given` clusters,
   or scraper `items_fetched` volume drops / `auth_expired` / `selector_drift`.

### Step 2: Rank Opportunities (Evidence Over Guesswork)

Read [references/diagnosis-playbook.md](./references/diagnosis-playbook.md) to
correlate symptoms with the codebase. Score candidates using:

`Priority = (User Impact × Revenue/Activation Leverage × Confidence) / Effort`

Always fix in order:
1. **P0 — Broken Money / Broken Entry / Silent Data Loss**: Crashes blocking
   login/checkout, 5xx spikes, stuck `pgmq`/Cloudflare Queues, or scrapers
   returning 0 rows.
2. **P1 — High-Confidence Friction**: Rage Click / Dead Click selectors, mobile
   Safari breakage, slow LCP/TTFT causing immediate bounce.
3. **P2 — Funnel & Growth Experiments**: Copy, pricing, onboarding steps, or
   prompt-version changes tested behind Feature Flags.

### Step 3: Trace to Root Cause in the Codebase

Inspect real source code before proposing edits:
- Map Sentry stack traces + `release` + `request_id` (`cf_ray`) to exact file
  and line.
- Map Clarity Rage Click selectors or PostHog drop-offs to the exact component,
  TanStack Query mutation, form validation, or Hono/Gin handler.
- Distinguish **symptom** from **root cause** (e.g. a Rage Click on Submit is
  usually a missing loading state during a slow API call, not a dead button).

### Step 4: Ship Surgical Fixes with Guardrails

Before editing code:
- Add a regression test reproducing the bug whenever feasible (Vitest,
  Playwright, `go test`, `uv run pytest`).
- Preserve or strengthen typed telemetry (if a failure mode was previously
  silent, emit `action_failed` or a structured warning log).
- Gate P2 UX/copy/prompt experiments behind a PostHog Feature Flag when traffic
  supports an A/B comparison.

### Step 5: Define Post-Deploy Verification & Rollback Plan

Read [references/experiment-loop.md](./references/experiment-loop.md) and close
every optimization cycle with a concrete **Verification Contract**:

- **Target Metric & Baseline**: Exact ratio/latency/error metric before change.
- **Guardrail Metrics**: Error rate, p95 latency, queue age, or token cost must
  not regress.
- **Observation Window**: Minimum days or sessions before declaring victory.
- **Rollback Trigger**: Clear threshold to revert the deploy or flip the flag.
