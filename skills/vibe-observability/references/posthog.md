# PostHog Setup, Reverse Proxy & LLM Analytics

PostHog is the core product analytics engine in `core`, `full-deduped`, and
`ai-app` profiles: typed events, funnels, retention, feature flags, session
replay (when not delegated to Clarity), and LLM observability.

## 1. Environment Variables

```env
NEXT_PUBLIC_POSTHOG_KEY=
NEXT_PUBLIC_POSTHOG_HOST=https://us.i.posthog.com
# For EU cloud: https://eu.i.posthog.com
# Prefer a first-party proxy path in the browser: /ingest
```

## 2. Production-Safe Initialization

Key settings that prevent noisy data, bloated bills, and broken SPA tracking:

```ts
posthog.init(key, {
  // Prefer same-origin reverse proxy '/ingest' to bypass AdBlockers
  api_host: "/ingest",
  ui_host: process.env.NEXT_PUBLIC_POSTHOG_HOST || "https://us.posthog.com",

  // Massive cost saver: only create person profiles for identified users
  // (up to 4x cheaper for anonymous landing-page traffic)
  person_profiles: "identified_only",

  // SPA / Next.js App Router: capture route transitions cleanly
  capture_pageview: "history_change",
  capture_pageleave: true,

  // Privacy guardrails for Session Replay
  disable_session_recording: useClarityForReplay, // MUST be true in `full-deduped`
  session_recording: {
    maskAllInputs: true,
    maskTextSelector: "[data-ph-mask]",
    blockSelector: "[data-ph-no-capture]",
  },

  // Respect Do Not Track / Consent flow if required
  respect_dnt: false, // Set true or use opt_out_capturing_by_default if strict EU mode
  autocapture: {
    // Keep autocapture focused; avoid scraping sensitive attributes
    dom_event_allowlist: ["click", "submit"],
  },
  loaded: (ph) => {
    if (process.env.NODE_ENV !== "production" && !debugEnabled) {
      ph.opt_out_capturing();
    }
  },
});
```

## 3. First-Party Reverse Proxy (Defeat AdBlockers)

Up to 40% of technical users block `*.posthog.com`. Route browser ingestion
through your own domain:

- **Next.js (`next.config.ts`)**:
  ```ts
  async rewrites() {
    return [
      { source: "/ingest/static/:path*", destination: "https://us-assets.i.posthog.com/static/:path*" },
      { source: "/ingest/:path*", destination: "https://us.i.posthog.com/:path*" },
      { source: "/ingest/decide", destination: "https://us.i.posthog.com/decide" },
    ];
  },
  skipTrailingSlashRedirect: true,
  ```
- **Cloudflare Pages / Vercel / Nginx**: Add equivalent rewrites for
  `/ingest/static/*` and `/ingest/*`.
- Never name the proxy `/analytics`, `/tracking`, or `/posthog` — filter lists
  block those path names too. Use neutral paths like `/ingest` or `/t`.

## 4. Server-Side Event Capture (Critical Conversion Events)

Never trust the browser alone for revenue-critical events (`subscription_paid`,
`plan_upgraded`, `webhook_processed`). Browser tabs close, extensions block
scripts, and clients can spoof payloads.

- Use `posthog-node` (or Python `posthog`) in your backend / Stripe webhook
  handler with the same `distinctId` (`user.id`).
- In serverless / edge functions, always call `await posthog.shutdown()` (or
  `flush()`) before the handler returns so buffered events are not dropped!

## 5. AI / LLM Observability (`ai-app` Profile)

For products calling OpenAI, Anthropic, Gemini, or custom models, capture
structured generation telemetry server-side (via `@posthog/ai` or manual
`$ai_generation` events):

| Property | Purpose |
| :--- | :--- |
| `$ai_trace_id` | Links multi-step agent/RAG calls to one user request |
| `$ai_model` / `$ai_provider` | Compare cost, latency, and error rate across models |
| `$ai_input_tokens` / `$ai_output_tokens` | Detect prompt bloat and per-user unit economics |
| `$ai_latency` (seconds) & `ttft_ms` | Spot slow models or streaming stalls |
| `$ai_is_error` / `$ai_error` | Separate upstream rate limits / timeouts from app bugs |
| `prompt_version` | Correlate prompt changes with user thumbs-up/down feedback |

**Privacy warning**: Never log raw user prompts or model outputs containing
customer PII unless explicitly consented and covered by your privacy policy;
default to logging metadata + hashed/truncated previews or opt-in privacy mode.
