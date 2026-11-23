# Observability Profiles Matrix

Choose the lightest profile that matches the application's runtime and goals.
Never stack overlapping replay engines or force browser trackers into desktop,
native, or batch runtimes.

## Profile Comparison

| Profile | Included Stack | Best For | Key Rule |
| :--- | :--- | :--- | :--- |
| **`core`** *(default Web)* | Sentry + PostHog + Backend Logs & `/health` | React/Vite/TanStack/Hono, Next.js, SaaS, Indie Web Apps | Single product-analytics SDK covers events, funnels, replay & flags; Sentry owns errors & traces. Zero overlap. |
| **`marketing`** | Sentry + GA4 + MS Clarity + `/health` | Landing pages, SEO/content sites, Google Ads funnels | Maximum free tier for acquisition attribution + heatmaps/rage clicks without heavy product SDKs. |
| **`full-deduped`** | Sentry + PostHog *(replay OFF)* + GA4 + MS Clarity *(replay ON)* + Backend Logs | Growth products needing **both** deep product funnels/flags **and** Google Ads + unlimited free heatmaps | **MUST** set `disable_session_recording: true` in PostHog and disable Sentry Replay so only Clarity records DOM. |
| **`ai-app`** | `core` + LLM Generation Telemetry (`$ai_generation`, TTFT, tokens, cost, user feedback) | AI apps, copilots, agents, RAG pipelines | Tracks unit economics (cost/user), latency (`ttft_ms`), upstream rate limits, and prompt-version quality. |
| **`selfhosted-infra`** | `log/slog` (or Pino) + Sentry + `/metrics` (Prometheus / Pigsty) + Caddy `/ingest` proxy + Queue depth alerts | Go + Gin + Docker + Caddy, Pigsty (PG + `pgmq` + Valkey + RustFS), high-concurrency APIs | Reuse Pigsty's built-in Prometheus + Grafana + Loki for infra/DB/queue metrics; reserve Sentry/PostHog for crashes and product funnel. |
| **`desktop-native`** | Native Sentry (`@sentry/electron`, `sentry-go`, `sentry` Rust, `sentry-cocoa`/`MetricKit`, `sentry-android`) + Rotating local diagnostic logs + Opt-out PostHog events | Electron, Go + Wails v3 + SQLite, Rust Tauri 2 / Win32, Swift (macOS/iOS), Kotlin (Android) | **NO GA4, NO MS Clarity, NO silent session replay.** Always expose a visible telemetry opt-out toggle and one-click diagnostic log export. |
| **`batch-jobs`** | `structlog` JSON + Sentry Crons (check-in monitors) + Run Summary & volume-drop anomaly alerts | Python + `uv` scrapers, Ego Lite automation, ETL, scheduled workers | Silent zero-row runs caused by site redesigns or anti-bot walls are deadlier than crashes; monitor output volume & completion heartbeats. |

## Strict Anti-Patterns

1. **Dual Replay Conflict**: Enabling PostHog Session Replay and Microsoft
   Clarity (or Sentry Replay) on the same page.
2. **Browser Trackers in Desktop/Native Apps**: Installing GA4 or Clarity in
   Electron, Wails, Tauri, iOS, or Android breaks non-HTTP protocols and triggers
   privacy backlash.
3. **Unflushed Serverless/Edge Telemetry**: Calling `posthog-node` or Sentry
   inside Cloudflare Workers or Lambda without `ctx.waitUntil(...)` / `shutdown()`.
4. **Paying Twice When Self-Hosting with Pigsty**: Buying expensive hosted APM /
   log SaaS when Pigsty already runs Prometheus, Grafana, and Loki for PG,
   `pgmq`, Valkey, and RustFS.
5. **Over-Instrumenting Throwaway Scripts**: Local one-off scripts should use
   structured console/file logs only — skip external SaaS SDKs entirely.

## Fast Decision Tree

```text
What kind of runtime is this?
├─ Desktop or Native Mobile/OS app -> `desktop-native` (NO GA4/Clarity)
├─ Data scraper / cron / CLI batch job -> `batch-jobs`
├─ Go / High-concurrency self-hosted backend (Docker/Caddy/Pigsty) -> `selfhosted-infra` (+ `core` if it also serves a Web UI)
└─ Web / Full-Stack / Edge app:
   ├─ Core LLM / Agent feature -> `ai-app`
   ├─ Pure SEO / landing / ad funnel -> `marketing`
   ├─ Needs BOTH PostHog funnels/flags AND GA4+Clarity -> `full-deduped` (PostHog replay OFF)
   └─ Default SaaS / Web app -> `core`
```
