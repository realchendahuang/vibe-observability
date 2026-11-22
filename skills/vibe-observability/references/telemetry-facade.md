# Unified Telemetry Facade & Cross-Tool Correlation

Application code must never import vendor SDKs directly across pages and
components. Route every event, identity change, and handled error through a
single typed facade.

## Why a Facade Matters in Vibe Coding

- AI coding sessions drift in naming (`click_cta`, `ctaClicked`, `CTA_Click`). A
  TypeScript event map forces compile-time consistency.
- Switching profiles (`core` -> `full-deduped`) or dropping a vendor changes one
  file instead of 60 components.
- Dev opt-out, PII scrubbing, client-side rate limiting, and cross-tool ID
  linking live in one auditable place.

## Minimal Public Interface

Implement this surface in `src/lib/telemetry/index.ts` (or equivalent for the
stack):

```ts
export interface TelemetryClient {
  init(): void;
  identify(userId: string, traits?: SafeUserTraits): void;
  reset(): void;
  track<K extends EventName>(event: K, props: EventPayloads[K]): void;
  pageView(path?: string): void;
  captureError(error: unknown, context?: ErrorContext): void;
  setConsent(granted: boolean): void;
}
```

### Rules for `SafeUserTraits`
- Allow only non-sensitive product traits (e.g. `plan`, `role`, `workspace_tier`,
  `created_at`, `locale`).
- **Never** forward `email`, `phone`, `full_name`, `password`, or `token` to GA4
  or Clarity. If email is intentionally needed in PostHog/Sentry for internal
  support, guard it explicitly and strip it before GA4/Clarity fan-out.

## Cross-Linking Sentry ↔ PostHog ↔ Clarity (The Superpower)

When an error happens in production, the fastest way to debug it is jumping
straight from the Sentry issue into the exact user session replay.

### 1. Share the Same Stable `userId`
Inside `identify(userId, traits)`:
- `posthog.identify(userId, safeTraits)`
- `Sentry.setUser({ id: userId })` (avoid sending raw PII unless policy permits)
- `clarity("identify", hashedOrOpaqueUserId)` (if Clarity is enabled)

Inside `reset()` (on logout):
- `posthog.reset()`
- `Sentry.setUser(null)`

### 2. Attach PostHog Session Replay Link to Sentry Events
In Sentry's `beforeSend` (or via `@posthog/sentry-integration` / manual scope
enrichment):

```ts
if (typeof window !== "undefined" && posthog.__loaded) {
  const replayUrl = posthog.get_session_replay_url?.({ withTimestamp: true });
  const distinctId = posthog.get_distinct_id?.();
  if (distinctId) event.tags = { ...event.tags, posthog_distinct_id: distinctId };
  if (replayUrl) {
    event.contexts = {
      ...event.contexts,
      posthog: { session_replay_url: replayUrl },
    };
  }
}
```

### 3. Correlate Frontend Requests to Backend Logs
Generate a short per-request ID (`crypto.randomUUID()`) in your API client and
pass it as `X-Request-Id`. Include it in:
- Backend structured logs (`req_id`)
- Backend Sentry scope (`Sentry.setTag("request_id", reqId)`)
- Frontend `captureError` context when an API call fails

## Client-Side Anti-Loop Rate Limiter

Vibe-coded React `useEffect` hooks frequently miss dependency arrays and fire
events on every render. Build a simple per-event burst guard inside `track()`:

- Track `(eventName + serializedKey)` in an in-memory sliding window (e.g. max 20
  identical events per 10 seconds per tab).
- In `development`, log a loud console warning when the burst limit trips so the
  developer catches the infinite loop immediately before deploying.
- In `production`, drop excess duplicates and emit a single internal diagnostic
  warning (`telemetry_burst_dropped`).
