# Sentry Setup & Production Guardrails

Sentry is the backbone for exception capture, stack traces, release health, and
lightweight performance tracing across frontend and backend.

## 1. Environment Variables

Use your frontend framework's public prefix (`VITE_` for Vite, `NEXT_PUBLIC_`
for Next.js, `PUBLIC_` for Astro/SvelteKit, `NUXT_PUBLIC_` for Nuxt):

```env
# Public (browser-safe, DSN is write-only)
<PUBLIC_PREFIX>_SENTRY_DSN=

# Server / Build-time only (NEVER expose with a public browser prefix)
SENTRY_DSN=
SENTRY_ORG=
SENTRY_PROJECT=
SENTRY_AUTH_TOKEN=
```

## 2. Sampling & Cost Protection (Mandatory)

Never leave `tracesSampleRate: 1.0` hardcoded in production — traffic spikes or
polling endpoints will burn free quota in hours.

```ts
const isProd = env.MODE === "production"; // or process.env.NODE_ENV === "production"

Sentry.init({
  dsn: env.SENTRY_DSN,
  enabled: isProd || env.OBSERVABILITY_DEBUG === "true",
  environment: env.APP_ENV || env.MODE,
  release: env.GIT_SHA,

  // Safe default budgets (override via env var if needed)
  tracesSampleRate: isProd ? 0.1 : 0,

  // Only enable Sentry Session Replay if NOT using PostHog Replay or Clarity
  replaysSessionSampleRate: 0,
  replaysOnErrorSampleRate: 0,

  sendDefaultPii: false,
  ignoreErrors: [
    "ResizeObserver loop limit exceeded",
    "ResizeObserver loop completed with undelivered notifications",
    "Non-Error promise rejection captured",
    /^AbortError/i,
  ],
  beforeSend(event) {
    // Strip authorization headers / cookies if accidentally attached
    if (event.request?.headers) {
      delete event.request.headers.authorization;
      delete event.request.headers.cookie;
    }
    return event;
  },
});
```

> **Replay Deduplication Rule**: When using `core` (PostHog owns replay) or
> `marketing` / `full-deduped` (Clarity owns replay), keep Sentry's
> `replaysSessionSampleRate: 0` and `replaysOnErrorSampleRate: 0` and omit
> `Sentry.replayIntegration()` to save bundle size (~50KB+) and CPU overhead.

## 3. AdBlock Bypass via Tunnel Route

Browser extensions commonly block `*.ingest.sentry.io`.

- **Next.js**: Configure `tunnelRoute: "/monitoring"` inside
  `withSentryConfig(nextConfig, { ... })`. Remember to exclude `/monitoring`
  from auth middleware!
- **Vite + Custom Backend**: Expose a narrow proxy endpoint (e.g.
  `POST /api/monitoring`) that validates the `dsn` host against your exact
  allowlisted Sentry project before forwarding the envelope (never create an
  open proxy).

## 4. Source Maps & Release Tagging

Minified stack traces are nearly useless for AI root-cause diagnosis.

- **Next.js**: Use `@sentry/nextjs` `withSentryConfig` with
  `sourcemaps: { deleteSourcemapsAfterUpload: true }` so source maps reach
  Sentry but are never served publicly in `.next/static`.
- **Vite**: Use `@sentry/vite-plugin` with `sourcemaps.filesToDeleteAfterUpload`.
- Always pass a `release` identifier (e.g. `VERCEL_GIT_COMMIT_SHA` or
  `GITHUB_SHA`) so Sentry isolates regressions introduced by a specific deploy.

## 5. Error Boundaries & Global Handlers

- **Next.js App Router**:
  - `src/app/global-error.tsx`: Capture fatal root-layout crashes with
    `Sentry.captureException(error)` inside `useEffect`.
  - `src/instrumentation.ts`: Register `sentry.server.config.ts` and
    `sentry.edge.config.ts`, plus `onRequestError = Sentry.captureRequestError`.
- **React SPA (Vite)**:
  - Wrap `<App />` in `<Sentry.ErrorBoundary fallback={...}>` with a friendly
    recovery button ("Reload page") instead of a blank white screen.
- **Node / FastAPI Backend**:
  - Initialize Sentry at process entrypoint before app routes mount.
  - Attach `request_id` tag per request and flush gracefully on shutdown.
