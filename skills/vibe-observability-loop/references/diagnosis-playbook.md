# Root-Cause Diagnosis Playbook

How to turn raw telemetry signals into accurate source-code root causes instead
of superficial patches.

## 1. Sentry Error Triage Matrix

Sort by **unique affected users** and **new in latest release** first.

| Signal Pattern | Likely Root Cause | Where to Inspect in Code |
| :--- | :--- | :--- |
| Spike immediately after deploy (`release` tag) | Regression or missing prod env var | Diff since previous release; `.env` schema / build config |
| Concentrated on Safari / iOS WebView | Unsupported Web API (`structuredClone`, regex lookbehind, `crypto.randomUUID` over HTTP, date parsing) | Polyfills, `new Date("YYYY-MM-DD HH:mm")`, `Intl` usage |
| `Hydration failed` / React #418/#423/#425 | Server/client mismatch (`Date.now()`, `window`, `localStorage`, locale formatting during SSR) | Client-only hooks, `'use client'` boundaries, date/currency formatters |
| `ChunkLoadError` / `Failed to fetch dynamically imported module` | Stale HTML referencing old hashed JS chunks after a fresh deployment | Error boundary auto-reload once with sessionStorage guard |
| `401/403` bursts on background polling | Expired session token not handled by global fetch interceptor | Auth refresh middleware, visibility-change pause |

## 2. Funnel Drop-Off Diagnosis (PostHog / GA4)

When conversion drops sharply between Step A and Step B:

1. **Segment before guessing**: Break down the drop-off by:
   - Device (`Mobile` vs `Desktop`)
   - Browser (`Safari` vs `Chrome`)
   - Acquisition source (`utm_source`, `referrer`)
   - Release version
2. **Cross-reference errors**: Check if Sentry had a matching error spike on the
   same route or `posthog_distinct_id`.
3. **Watch 5–10 replays of drop-off sessions** (not random sessions):
   - Did the user wait >3s for a skeleton/spinner and leave? -> Latency bug.
   - Did validation fail silently without scrolling to the error? -> Form UX bug.
   - Did they hit a paywall/login wall too early before seeing value? -> Product flow issue.

## 3. Clarity / Replay Friction Signals

| Friction Signal | What Users Are Actually Feeling | Common Fixes |
| :--- | :--- | :--- |
| **Rage Click** on a button | Button looks clickable or takes >500ms with zero visual feedback | Add immediate disabled/loading state; check overlapping transparent `z-index` elements; optimize slow handler |
| **Dead Click** on text/card/icon | Visual affordance looks like a link/button (blue text, underline, card hover) but has no handler | Either make it interactive or remove misleading hover/cursor styling |
| **Quick Back** (<10s bounce back) | Landing promise mismatches page reality, or above-the-fold fails to load cleanly | Check LCP/CLS on mobile; tighten hero headline and primary CTA visibility |
| **Excessive Scrolling** | User is hunting for pricing, demo, or key info | Surface FAQ/pricing anchor higher; simplify information hierarchy |

## 4. AI / LLM Product Diagnostics (`ai-app`)

- **High `ttft_ms` (>2.5s)**: Check whether responses are buffered instead of
  streamed, or whether slow sequential tool calls run before the first token.
- **High cost per active user**: Inspect top 5% sessions by `input_tokens` —
  usually unbounded chat history being re-sent every turn without summarization
  or prompt caching.
- **High `regenerated` / `negative` feedback on a `prompt_version`**: Diff the
  prompt template and inspect structured error categories (JSON parse failure,
  refusal, context truncation).
