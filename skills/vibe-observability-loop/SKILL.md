---
name: vibe-observability-loop
description: >-
  Close the self-improving AI feedback loop ("左脚踩右脚"): pull or ingest live
  production signals from Sentry, PostHog, GA4, Microsoft Clarity, and backend
  logs; correlate errors, funnel drop-offs, rage clicks, and LLM cost spikes
  against the codebase; prioritize root-cause fixes; and define post-deploy
  verification metrics. Activate when the user asks to analyze production data,
  investigate Sentry errors or PostHog funnels, review Clarity rage clicks, or
  run an observability-driven optimization cycle.
---

# Vibe Observability Loop (Data -> AI Diagnosis -> Fix -> Verify)

Instrumentation without a feedback loop is just a prettier dashboard. This skill
turns real production signals into prioritized, evidence-backed code changes and
prevents "fake optimizations" by enforcing post-deploy metric verification.

## Operating Modes

1. **Live MCP / CLI Mode (Preferred)**: Query connected MCP servers or CLIs
   directly (e.g. Sentry MCP, PostHog MCP/API, Clarity export API, server logs).
2. **Snapshot Mode (Zero Setup)**: Accept pasted error stacks, Sentry JSON,
   PostHog funnel screenshots/CSV exports, Clarity rage-click/dead-click
   summaries, or log excerpts from the user.

Never fabricate live metrics. If neither MCP access nor a user snapshot is
available for a data source, explicitly state what is missing and ask the user
for the smallest export needed (or recommend connecting the relevant MCP).

---

## 5-Step Optimization Loop

### Step 1: Collect Multi-Signal Evidence

Gather the last 24h–7d signals across four buckets (whichever are active in the
project):

1. **Reliability (Sentry & Backend Logs)**: Top errors by affected users (not
   just raw count), new regressions since the latest `release`, and p95 latency
   spikes on critical endpoints.
2. **Conversion & Retention (PostHog / GA4)**: Biggest step-to-step drop-offs
   in the core funnel (`signup_started -> signup_completed -> activation_achieved
   -> checkout_started -> subscription_activated`), segmented by device/browser.
3. **UX Friction (Clarity / PostHog Replay)**: Pages and CSS selectors with high
   **Rage Clicks**, **Dead Clicks**, **Quick Backs**, or excessive scroll without
   conversion.
4. **Unit Economics & Quality (AI Apps)**: High-latency models (`ttft_ms`),
   token/cost outliers per user, upstream failure rates, and negative
   `generation_feedback_given` clusters.

### Step 2: Rank Opportunities (Evidence Over Guesswork)

Read [references/diagnosis-playbook.md](./references/diagnosis-playbook.md) to
correlate symptoms with the codebase. Score candidate issues using:

`Priority = (User Impact × Revenue/Activation Leverage × Confidence) / Effort`

Always fix in this order:
1. **P0 — Broken Money / Broken Entry**: Crashes blocking login, onboarding, or
   checkout; 5xx spikes; dead primary CTAs.
2. **P1 — High-Confidence Friction**: High Rage Click / Dead Click selectors,
   mobile layout breakage, slow LCP/TTFT causing immediate bounce.
3. **P2 — Funnel & Growth Experiments**: Copy, pricing, onboarding steps, or
   prompt-version improvements tested behind Feature Flags.

### Step 3: Trace to Root Cause in the Codebase

For the top 1–3 issues, inspect the actual source code before proposing edits:
- Map Sentry stack traces + `release` + `request_id` to exact file and line.
- Map Clarity Rage Click selectors or PostHog funnel drop-offs to the exact
  React/Vue/HTML component, form validation, or API handler.
- Distinguish **symptom** from **root cause** (e.g. a "Rage Click on Submit"
  is often caused by a missing loading spinner during a slow 4s API call, not a
  broken button handler).

### Step 4: Ship Surgical Fixes with Guardrails

Before editing code:
- Write or update a regression test reproducing the bug whenever feasible.
- Ensure the fix preserves or enhances typed telemetry (e.g. if a failure mode
  was previously silent, add an `action_failed` event or structured warning log).
- For UX/copy/prompt experiments (P2), gate behind a PostHog Feature Flag rather
  than overwriting blindly when traffic supports an A/B comparison.

### Step 5: Define Post-Deploy Verification & Rollback Plan

Read [references/experiment-loop.md](./references/experiment-loop.md) and always
close your report with a concrete **Verification Contract**:

- **Target Metric**: Exact metric and baseline (e.g. "`checkout_started ->
  subscription_activated` currently 18% on mobile Safari; expect >= 30%").
- **Guardrail Metric**: What must NOT regress (e.g. error rate, p95 latency,
  token cost per session).
- **Observation Window**: Minimum time or sample size before declaring success
  (avoid calling winners on 5 users).
- **Rollback Trigger**: Clear threshold to revert the release or flip the flag
  off.
