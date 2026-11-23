# Stack Adapter: SSR Meta-Frameworks (Next.js, Nuxt, SvelteKit, Astro)

SSR frameworks share three recurring traps: hydrating client-only SDKs on the
server, blocking reverse-proxy routes in auth middleware, and accidentally
shipping `.js.map` files publicly.

## 1. Universal SSR Rules

1. **Client-Only Initialization**: Never call `posthog.init()`, `Clarity.init()`,
   or `gtag()` during server rendering. Gate behind `typeof window !== "undefined"`
   and client lifecycle hooks (`useEffect`, `onMounted`, `onMount`).
2. **Exclude Reverse Proxy & Tunnel Paths from Auth Middleware (Critical!)**:
   If you proxy PostHog at `/ingest` or Sentry at `/monitoring`, your auth
   middleware **must** bypass those paths — otherwise anonymous traffic and
   login-page crashes get 302/307-redirected to `/login` and vanish silently.
3. **Delete Source Maps After Upload**: Upload maps to Sentry in CI/build, then
   delete `.map` artifacts from public output directories.

---

## 2. Next.js (App Router)

- **Instrumentation**: Register server & edge Sentry configs in
  `src/instrumentation.ts` and export `onRequestError = Sentry.captureRequestError`.
- **Fatal UI Boundary**: Add `src/app/global-error.tsx` calling
  `Sentry.captureException(error)` inside `useEffect`.
- **Reverse Proxy + Tunnel**: Configure `/ingest/*` in `next.config.ts`
  `rewrites()` (`skipTrailingSlashRedirect: true`) and `tunnelRoute: "/monitoring"`
  plus `sourcemaps: { deleteSourcemapsAfterUpload: true }` in `withSentryConfig`.
- **Middleware Exclusion**:
  ```ts
  export const config = {
    matcher: ["/((?!_next/static|_next/image|favicon.ico|ingest|monitoring|api/health).*)"],
  };
  ```
- See [examples/nextjs-app-router/](./examples/nextjs-app-router/) for starter
  files (`telemetry.ts`, `next.config.snippet.ts`, `.env.example`).

## 3. Nuxt 3 / 4

- Use `@sentry/nuxt` module (`sentry.client.config.ts` & `sentry.server.config.ts`).
- Initialize PostHog inside a `*.client.ts` plugin (`plugins/telemetry.client.ts`).
- Configure `/ingest/**` proxy via Nitro `routeRules` in `nuxt.config.ts`.

## 4. SvelteKit

- Use `@sentry/sveltekit` (`hooks.client.ts` + `hooks.server.ts` with
  `handleErrorWithSentry`).
- Initialize PostHog inside `+layout.ts` / `onMount` (`browser` guard from
  `$app/environment`) and listen to `afterNavigate` for SPA pageviews if needed.

## 5. Astro

- Load lightweight telemetry via a client island or inline script guarded by
  `import.meta.env.PROD`; for content/marketing Astro sites, prefer the
  **`marketing`** profile (Sentry + GA4 + Clarity) or lightweight `core` without
  bloating static HTML pages.
