# Backend Observability Starters (Node / FastAPI)

Minimal snippets covering structured JSON logging, `X-Request-Id` correlation,
Sentry server capture, and a fast `/api/health` liveness endpoint.

---

## Node / TypeScript (Express / Fastify / Hono)

```ts
import crypto from "node:crypto";
import pino from "pino";
import * as Sentry from "@sentry/node";

Sentry.init({
  dsn: process.env.SENTRY_DSN,
  enabled: process.env.NODE_ENV === "production",
  tracesSampleRate: process.env.NODE_ENV === "production" ? 0.1 : 0,
  sendDefaultPii: false,
});

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

// Express-style request ID middleware
export function requestIdMiddleware(req: any, res: any, next: () => void) {
  const reqId = (req.headers["x-request-id"] as string) || crypto.randomUUID();
  req.requestId = reqId;
  res.setHeader("X-Request-Id", reqId);
  Sentry.getIsolationScope().setTag("request_id", reqId);
  next();
}

// Fast liveness route (zero heavy DB calls)
export function healthHandler(_req: any, res: any) {
  res.status(200).json({
    status: "ok",
    version: process.env.GIT_SHA || "dev",
    uptime_s: Math.floor(process.uptime()),
  });
}
```

---

## Python (FastAPI + structlog + Sentry)

```python
import os
import time
import uuid
import sentry_sdk
import structlog
from fastapi import FastAPI, Request, Response

IS_PROD = os.getenv("APP_ENV", "development") == "production"

sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    environment=os.getenv("APP_ENV", "development"),
    traces_sample_rate=0.1 if IS_PROD else 0.0,
    send_default_pii=False,
)

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer() if IS_PROD else structlog.dev.ConsoleRenderer(),
    ]
)
log = structlog.get_logger()

app = FastAPI()
STARTED_AT = time.monotonic()


@app.middleware("http")
async def correlate_requests(request: Request, call_next):
    req_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=req_id, path=request.url.path)
    sentry_sdk.set_tag("request_id", req_id)

    start = time.perf_counter()
    response: Response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    response.headers["X-Request-Id"] = req_id
    log.info("http_request", method=request.method, status=response.status_code, duration_ms=duration_ms)
    return response


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "version": os.getenv("GIT_SHA", "dev"),
        "uptime_s": int(time.monotonic() - STARTED_AT),
    }
```
