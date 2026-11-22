# Backend Logs, Request Tracing & External Uptime

Browser telemetry alone has a fatal blind spot: if your server crashes with 502,
your database runs out of connections, your Stripe webhook returns 400, or your
SSL certificate expires, **browser scripts never execute and your dashboards
stay silently green**.

## 1. Structured JSON Logging

Replace ad-hoc `console.log("err", e)` / `print(...)` with machine-parseable
JSON logs containing consistent fields (`level`, `msg`, `req_id`, `user_id`,
`route`, `duration_ms`, `err`).

- **Node / TypeScript**: Use `pino` (or `pino-http` for Express/Fastify/Hono).
  Configure `redact` to strip secrets automatically:
  ```ts
  export const logger = pino({
    level: process.env.LOG_LEVEL || "info",
    redact: [
      "req.headers.authorization",
      "req.headers.cookie",
      "*.password",
      "*.token",
      "*.apiKey",
    ],
  });
  ```
- **Python / FastAPI**: Use `structlog` with JSON renderer in production and
  console renderer in local dev. Bind `request_id` per request via
  `structlog.contextvars.bind_contextvars(request_id=req_id)`.

## 2. End-to-End Request Correlation (`X-Request-Id`)

1. Accept an incoming `X-Request-Id` header (or generate a UUIDv4 if missing).
2. Echo `X-Request-Id` back in the HTTP response header so the frontend can
   attach it to user-visible error messages ("Something went wrong — Ref:
   `8f3a2c`") and Sentry error tags.
3. Attach `request_id` to every backend log line and backend Sentry scope
   (`Sentry.setTag("request_id", reqId)`).

## 3. Health Check Endpoints (`/api/health` or `/healthz`)

Expose two distinct signals (or a lightweight query flag) so uptime monitors
never trigger cascading DB outages:

- **Liveness (`GET /api/health`)**: Fast (<10ms), zero heavy queries, returns
  `200 { "status": "ok", "version": "<git_sha>", "uptime_s": 1234 }`.
- **Readiness (`GET /api/health?deep=1` or `/api/ready`, optionally protected
  with a lightweight header/token)**: Verifies critical dependencies (DB
  `SELECT 1`, Redis `PING`) with a tight timeout (e.g. 1500ms) and returns
  `503` if degraded.

## 4. External Uptime & Cron/Webhook Monitoring

Include these short setup instructions in the final user handoff whenever a
project deploys to production:

1. **External HTTP Ping** (free tiers on Better Stack, UptimeRobot, or Checkly):
   - Poll `GET https://<domain>/api/health` every 1–5 minutes from multiple
     regions.
   - Enable **SSL certificate expiry alerts** (7 days before expiry).
2. **Critical Background Jobs / Cron**:
   - Wrap scheduled tasks with Sentry Crons (`Sentry.withMonitor`) or a
     dead-man's-switch heartbeat URL so silent cron failures trigger alerts.
3. **Webhooks (Stripe, Auth, External APIs)**:
   - Log every webhook event ID + outcome (`processed`, `duplicate_ignored`,
     `failed`) in structured logs and capture non-2xx handler exceptions in
     Sentry with the webhook event ID as a tag.
