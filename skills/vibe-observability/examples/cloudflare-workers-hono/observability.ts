/**
 * Cloudflare Workers + Hono observability starter:
 * - `@sentry/cloudflare` wrapper with CF_VERSION_METADATA release tagging
 * - Structured JSON request logging correlated with `X-Request-Id` & `cf-ray`
 * - Guaranteed PostHog server-side flush via `ctx.waitUntil(...)`
 * - First-party `/ingest/*` PostHog reverse proxy + SSRF-safe `/monitoring` Sentry tunnel
 * - Fast `/api/health` probe (mounted BEFORE auth middleware!)
 */

import { Hono } from "hono";
import * as Sentry from "@sentry/cloudflare";

export interface Env {
  APP_ENV?: string;
  SENTRY_DSN?: string;
  SENTRY_ALLOWED_HOST?: string; // e.g. "o123456.ingest.us.sentry.io"
  SENTRY_PROJECT_ID?: string;   // e.g. "4500000000000000"
  POSTHOG_KEY?: string;
  POSTHOG_HOST?: string;        // e.g. "https://us.i.posthog.com"
  CF_VERSION_METADATA?: { id: string };
}

type Variables = {
  requestId: string;
};

const app = new Hono<{ Bindings: Env; Variables: Variables }>();

/** Emit one structured JSON log line for Cloudflare Workers Logs. */
function logJson(level: "info" | "warn" | "error", msg: string, fields: Record<string, unknown>) {
  console.log(JSON.stringify({ ts: new Date().toISOString(), level, msg, ...fields }));
}

/** Fire-and-forget server-side PostHog capture safely flushed via ctx.waitUntil(). */
export function trackServerEvent(
  env: Env,
  ctx: ExecutionContext,
  distinctId: string,
  event: string,
  properties: Record<string, unknown> = {}
): void {
  if (!env.POSTHOG_KEY || env.APP_ENV !== "production") return;
  const host = (env.POSTHOG_HOST || "https://us.i.posthog.com").replace(/\/$/, "");

  const req = fetch(`${host}/capture/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      api_key: env.POSTHOG_KEY,
      distinct_id: distinctId,
      event,
      properties,
    }),
  }).catch((err) => {
    logJson("warn", "posthog_capture_failed", { event, error: String(err) });
  });

  ctx.waitUntil(req);
}

// 1. Request correlation & structured access log middleware
app.use("*", async (c, next) => {
  const reqId = c.req.header("x-request-id") || crypto.randomUUID();
  const cfRay = c.req.header("cf-ray") || "";
  const start = Date.now();
  c.set("requestId", reqId);
  Sentry.setTag("request_id", reqId);
  if (cfRay) Sentry.setTag("cf_ray", cfRay);

  await next();

  c.header("X-Request-Id", reqId);
  logJson("info", "http_request", {
    request_id: reqId,
    cf_ray: cfRay,
    method: c.req.method,
    route: c.req.routePath,
    status: c.res.status,
    duration_ms: Date.now() - start,
  });
});

// 2. Fast liveness probe (keep public, zero heavy D1 queries)
app.get("/api/health", (c) =>
  c.json({
    status: "ok",
    version: c.env.CF_VERSION_METADATA?.id || "dev",
  })
);

// 3. First-party PostHog reverse proxy (mount BEFORE auth middleware)
app.all("/ingest/*", async (c) => {
  const posthogHost = (c.env.POSTHOG_HOST || "https://us.i.posthog.com").replace(/\/$/, "");
  const assetHost = posthogHost.includes("eu.")
    ? "https://eu-assets.i.posthog.com"
    : "https://us-assets.i.posthog.com";

  const url = new URL(c.req.url);
  const subPath = url.pathname.replace(/^\/ingest/, "");
  const targetOrigin = subPath.startsWith("/static/") ? assetHost : posthogHost;
  const targetUrl = `${targetOrigin}${subPath}${url.search}`;

  const headers = new Headers(c.req.raw.headers);
  headers.delete("cookie");
  headers.set("host", new URL(targetOrigin).host);

  return fetch(targetUrl, {
    method: c.req.method,
    headers,
    body: c.req.method === "GET" || c.req.method === "HEAD" ? undefined : c.req.raw.body,
  });
});

// 4. SSRF-safe Sentry tunnel (strictly validates DSN host & project ID)
app.post("/monitoring", async (c) => {
  const allowedHost = c.env.SENTRY_ALLOWED_HOST;
  const allowedProjectId = c.env.SENTRY_PROJECT_ID;
  if (!allowedHost || !allowedProjectId) {
    return c.json({ error: "Sentry tunnel not configured" }, 503);
  }

  const envelopeBytes = await c.req.arrayBuffer();
  const firstNewline = new Uint8Array(envelopeBytes).indexOf(10);
  const headerSlice = firstNewline >= 0 ? envelopeBytes.slice(0, firstNewline) : envelopeBytes;

  let dsnUrl: URL;
  try {
    const header = JSON.parse(new TextDecoder().decode(headerSlice)) as { dsn?: string };
    if (!header.dsn) return c.json({ error: "Missing DSN" }, 400);
    dsnUrl = new URL(header.dsn);
  } catch {
    return c.json({ error: "Invalid envelope header" }, 400);
  }

  const projectId = dsnUrl.pathname.replace(/^\/+/, "");
  if (dsnUrl.hostname !== allowedHost || projectId !== allowedProjectId) {
    return c.json({ error: "Disallowed Sentry DSN" }, 403);
  }

  return fetch(`https://${allowedHost}/api/${allowedProjectId}/envelope/`, {
    method: "POST",
    body: envelopeBytes,
    headers: { "Content-Type": "application/x-sentry-envelope" },
  });
});

// 5. Centralized error handler: log 4xx softly, report 5xx to Sentry
app.onError((err, c) => {
  const reqId = c.get("requestId");
  logJson("error", "unhandled_exception", {
    request_id: reqId,
    route: c.req.routePath,
    error: err.message,
  });
  Sentry.captureException(err);
  return c.json({ error: "Internal Server Error", request_id: reqId }, 500);
});

export default Sentry.withSentry(
  (env: Env) => ({
    dsn: env.SENTRY_DSN,
    enabled: env.APP_ENV === "production",
    environment: env.APP_ENV || "development",
    release: env.CF_VERSION_METADATA?.id,
    tracesSampleRate: env.APP_ENV === "production" ? 0.1 : 0,
    sendDefaultPii: false,
  }),
  app
);
