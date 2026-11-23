# Stack Adapter: Vite + React + TanStack + Hono + Better Auth + Oxc

Tailored for modern TypeScript full-stack apps using Vite (including Vite 8),
React, TanStack (Router / Query / Start), Hono, Zod, Drizzle, Better Auth,
Oxc (`oxlint` / `oxfmt` / `tsrs`), Vitest, and Playwright.

## 1. Frontend: Vite + TanStack Router & Query + Web Vitals

### Env Prefix & Build Guardrails
- Use `VITE_*` prefixes (`VITE_SENTRY_DSN`, `VITE_POSTHOG_KEY`,
  `VITE_POSTHOG_PROXY=/ingest`, `VITE_OBSERVABILITY_DEBUG`).
- Guard init with `import.meta.env.PROD` (and ensure `import.meta.env.MODE !== "test"`
  so Vitest / Playwright runs never pollute production analytics).
- **Source Maps (Vite / Rolldown)**: Enable `build.sourcemap = "hidden"` and use
  `@sentry/vite-plugin` with:
  ```ts
  sentryVitePlugin({
    org: process.env.SENTRY_ORG,
    project: process.env.SENTRY_PROJECT,
    authToken: process.env.SENTRY_AUTH_TOKEN,
    sourcemaps: {
      filesToDeleteAfterUpload: ["./dist/**/*.map"],
    },
  })
  ```

### TanStack Router Integration
- Pass `router` to Sentry's `tanstackRouterBrowserTracingIntegration(router)`
  for clean parameterized route transactions (`/projects/$projectId` instead of
  noisy raw URLs).
- PostHog: `capture_pageview: "history_change"` tracks TanStack Router client
  navigations automatically without duplicate fires.

### TanStack Query Centralized Error Capture (Stop Per-Component `try/catch`)
Attach global handlers once on `QueryCache` and `MutationCache` instead of
scattering `captureError` across components:

```ts
const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error, query) => {
      // Ignore expected auth/validation states; report 5xx & network crashes
      const status = (error as { status?: number })?.status;
      if (status && status < 500) return;
      telemetry.captureError(error, {
        action: `query:${JSON.stringify(query.queryKey)}`,
        requestId: (error as { requestId?: string })?.requestId,
      });
    },
  }),
  mutationCache: new MutationCache({
    onError: (error, _vars, _ctx, mutation) => {
      const status = (error as { status?: number })?.status;
      if (status && status >= 400 && status < 500) return;
      telemetry.captureError(error, {
        action: `mutation:${String(mutation.options.mutationKey ?? "unknown")}`,
      });
    },
  }),
});
```

### Real User Core Web Vitals (`web-vitals`)
Report `LCP`, `INP`, `CLS`, and `TTFB` through `telemetry.track("web_vital_measured", ...)`
(or let PostHog Web Vitals autocapture handle it in `core` profile — avoid
sending duplicate Web Vitals from both).

## 2. Better Auth Identity Lifecycle (Zero Cookie/Token Leaks)

- Watch `authClient.useSession()`:
  - When `session?.user?.id` transitions from empty -> present: call
    `telemetry.identify(session.user.id, { role: session.user.role })`.
  - When logging out (`session` transitions to `null`): immediately call
    `telemetry.reset()` so the next user on the same browser does not merge
    identities.
- **Never** log or send Better Auth cookies (`better-auth.session_token`), raw
  session objects, or OAuth tokens into Sentry, PostHog, or server logs.

## 3. Hono + Zod + Drizzle Backend

- Use `hono/request-id` (`app.use("*", requestId())`) and echo `X-Request-Id`
  in responses.
- Centralize error handling in `app.onError((err, c) => ...)`:
  - `ZodError` / `HTTPException` with status `< 500`: log at `warn`/`info`
    with `request_id`; **do NOT flood Sentry**.
  - Unexpected `5xx` errors: log structured JSON error + capture in Sentry with
    `request_id`, route pattern, and opaque `user_id`.
- **Drizzle slow-query visibility**: In development or sampled production,
  wrap Drizzle's custom logger to emit a structured `warn` when a query exceeds
  e.g. `250ms` (log SQL shape/duration only — **never** log bound parameter
  values containing PII/passwords).
- Mount a fast `GET /api/health` route (no DB query) and optional
  `GET /api/health?deep=1` checking `SELECT 1`.

## 4. Oxc (`oxlint`) Facade Enforcement + Vitest / Playwright Hygiene

### Enforce Facade at Lint Time with `oxlint`
Prevent future vibe-coding sessions from bypassing `src/lib/telemetry`:
Add a lint rule (in `.oxlintrc.json`) restricting direct imports of `posthog-js`,
`@sentry/react`, and `@microsoft/clarity` outside `src/lib/telemetry/**`:

```json
{
  "rules": {
    "no-restricted-imports": [
      "error",
      {
        "paths": [
          {
            "name": "posthog-js",
            "message": "Import from '@/lib/telemetry' instead of calling posthog-js directly."
          },
          {
            "name": "@microsoft/clarity",
            "message": "Import from '@/lib/telemetry' instead of calling Clarity directly."
          }
        ]
      }
    ],
    "overrides": [
      {
        "files": ["src/lib/telemetry/**"],
        "rules": { "no-restricted-imports": "off" }
      }
    ]
  }
}
```

### Playwright E2E Isolation
- Keep `VITE_OBSERVABILITY_DEBUG` unset in E2E runs, or abort external tracker
  domains / `/ingest` in Playwright fixtures (`page.route("**/ingest/**", r => r.fulfill({ status: 204 }))`)
  so automated E2E suites never generate fake signups or session replays.
