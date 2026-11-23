# Stack Adapter: Cloudflare Workers + Hono + D1 / KV / Queues / R2

Cloudflare Workers run in short-lived V8 isolates, **not** long-lived Node
servers. Standard Node observability setups silently drop events or crash at
runtime on Workers.

## 1. The #1 Rule: Always Flush Inside `ctx.waitUntil(...)`

When a Worker returns a `Response`, background promises are frozen/killed
unless registered with `ExecutionContext.waitUntil()`.

- **PostHog (`posthog-node` / HTTP capture)**:
  Create a lightweight client with `flushAt: 1, flushInterval: 0` (or direct
  `fetch` to `/capture/`) and **always** call:
  ```ts
  c.executionCtx.waitUntil(ph.shutdown());
  ```
- Never hold global mutable per-request state across requests in module scope.

## 2. Sentry on Cloudflare Workers

- **MUST** use **`@sentry/cloudflare`** (`Sentry.withSentry(...)`) — **never**
  `@sentry/node` (fails on missing Node built-ins and loses isolate context).
- Enable `compatibility_flags = ["nodejs_compat"]` in `wrangler.toml` /
  `wrangler.jsonc`.
- Bind `version_metadata` (`[version_metadata]\nbinding = "CF_VERSION_METADATA"`)
  and pass `release: env.CF_VERSION_METADATA?.id` so Sentry pinpoints exact
  Worker deployments.
- Keep `tracesSampleRate: 0.1` and `sendDefaultPii: false`.

## 3. Native Cloudflare Workers Observability (Zero Extra Vendor)

Turn on Cloudflare's built-in structured Workers Logs in `wrangler.toml` /
`wrangler.jsonc`:

```jsonc
{
  "observability": {
    "enabled": true,
    "head_sampling_rate": 1
  }
}
```

Emit **single-line JSON** via `console.log(JSON.stringify({ level, msg, request_id, route, duration_ms, cf_ray }))`
including `c.req.header("cf-ray")` so logs correlate 1:1 with Cloudflare Ray IDs.

## 4. Zero-Cost First-Party Reverse Proxy in Hono (`/ingest` & `/monitoring`)

Workers are ideal for bypassing AdBlockers with negligible latency:

- **PostHog Proxy (`ALL /ingest/*`)**: Forward `/ingest/static/*` to
  `https://us-assets.i.posthog.com/static/*` and `/ingest/*` to
  `https://us.i.posthog.com/*` (or `eu.*`), stripping `cookie` and rewriting
  the `Host` header.
- **Sentry Tunnel (`POST /monitoring`)**: Parse the first JSON line of the
  Sentry envelope, **strictly verify** the `dsn` host and project ID match your
  allowlisted Sentry project (prevent SSRF / open proxy abuse!), then forward
  to `https://<sentry_host>/api/<project_id>/envelope/`.
- Mount these routes **before** Better Auth / JWT auth middleware so anonymous
  visitors' errors and pageviews are never blocked with `401`/`302`.

## 5. Observing D1, KV, Queues, R2 & Email

| Binding | What Actually Breaks in Production | How to Observe It |
| :--- | :--- | :--- |
| **D1 (SQLite)** | Query latency spikes, lock contention, `meta.rows_read` blowups | Log `result.meta.duration` & `rows_read` whenever duration > `100ms` (or via Drizzle wrapper). |
| **Queues** | Silent poison messages retrying and vanishing | Always configure a **Dead Letter Queue (`dead_letter_queue`)** in `wrangler.toml`, and attach a consumer that logs + alerts Sentry on every DLQ message. |
| **KV / R2** | Missing keys, stale eventual consistency, upload failures | Emit structured `warn`/`error` with `bucket`/`namespace`, `op`, `duration_ms`, and `request_id` (never log object body or presigned URLs). |
| **Cloudflare Email** | Bounces, SPF/DKIM failures, silent send errors | Log structured `email_send_failed` + capture exception in Sentry with template name (never log recipient email in plain text if PII-restricted). |
| **Cron Triggers** | Scheduled worker stops running or throws | Wrap `scheduled(event, env, ctx)` with Sentry Cron Monitor check-ins (`in_progress` -> `ok`/`error`) inside `ctx.waitUntil`. |

See [examples/cloudflare-workers-hono/observability.ts](./examples/cloudflare-workers-hono/observability.ts)
for a complete drop-in Hono + Cloudflare Workers implementation.
