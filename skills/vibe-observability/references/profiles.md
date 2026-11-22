# Observability Profiles Matrix

Never install overlapping client SDKs blindly. Choose the smallest profile that
answers the questions the product actually needs.

## Profile Comparison

| Profile | Included Stack | Best For | Why This Combo Works |
| :--- | :--- | :--- | :--- |
| **`core`** *(default)* | Sentry + PostHog + Backend Logs/Health | SaaS, Indie Web Apps, Mobile-Web MVPs | One product-analytics SDK covers events, funnels, session replay, web analytics, and feature flags; Sentry handles errors, source maps, and APM. Zero overlap. |
| **`marketing`** | Sentry + GA4 + MS Clarity + Health | Landing pages, SEO/content sites, ad-driven funnels | GA4 integrates natively with Google Ads & Search Console; Clarity gives unlimited free heatmaps and rage-click replays; Sentry catches broken pages/forms. |
| **`full-deduped`** | Sentry + PostHog *(replay OFF)* + GA4 + MS Clarity *(replay ON)* + Backend Logs/Health | High-growth products needing **both** deep product funnels/A/B tests **and** Google Ads attribution + free unlimited heatmaps | Deduplicates heavy DOM recording: PostHog handles typed events, funnels, retention, flags; Clarity owns visual heatmaps & session replay; GA4 owns acquisition attribution. |
| **`ai-app`** | `core` + LLM Generation Telemetry (PostHog LLM Analytics / OpenTelemetry / Langfuse) | AI wrappers, copilots, agents, RAG apps | Standard pageviews miss what matters in AI apps: TTFT, token burn per user, model fallback rate, tool-call failures, and thumbs-up/down quality score. |

## Strict Anti-Patterns

1. **Dual Replay Conflict**: Enabling both PostHog Session Replay and Microsoft
   Clarity on the same page.
   - *Fix*: In `full-deduped`, explicitly set `disable_session_recording: true`
     in `posthog.init(...)` (or omit Clarity and keep PostHog replay).
2. **Heavy SDKs on Static Docs/Marketing Pages**: Loading full Sentry Replay +
   PostHog + GA4 + Clarity on a simple waitlist page destroys LCP/INP.
   - *Fix*: Prefer `marketing` or `core` with deferred script loading.
3. **Frontend-Only Blindness on Full-Stack Apps**: Shipping an app with Stripe
   webhooks, auth callbacks, or DB writes using only browser analytics.
   - *Fix*: Always include structured backend logging + Sentry server SDK +
     `/api/health` external uptime probe.
4. **Instrumenting Throwaway Prototypes**: If the user explicitly says this is a
   local-only throwaway script not going to production, advise skipping external
   SaaS SDKs and keeping lightweight structured local logs only.

## Decision Tree

```text
Does the app have real external users / production deploy?
├─ No  -> Skip external SaaS SDKs; add structured local logging only.
└─ Yes -> Does it make LLM / AI model calls as a core feature?
          ├─ Yes -> Start with `ai-app` (or `full-deduped` + LLM events if running heavy Google Ads)
          └─ No  -> Is it primarily SEO/ads/landing conversion without logged-in workflows?
                    ├─ Yes -> `marketing`
                    └─ No  -> Does the user explicitly need GA4/Ads + Clarity heatmaps alongside PostHog?
                              ├─ Yes -> `full-deduped` (MUST disable PostHog replay)
                              └─ No  -> `core` (Recommended default)
```
