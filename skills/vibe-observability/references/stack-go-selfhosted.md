# Stack Adapter: Go + Gin + Caddy + Pigsty (PG / pgmq / Valkey / RustFS) & OpenTelemetry

When you run dedicated servers with **Go + Gin + Docker Compose + Caddy** and
self-hosted infrastructure managed by **Pigsty** (PostgreSQL HA, `pgmq`,
Redis/Valkey, RustFS), you already possess a world-class observability backbone.
Do **not** pay twice for heavy hosted APM/log SaaS — integrate cleanly with
Pigsty's Prometheus + Grafana + Loki stack while letting Sentry/PostHog handle
crash grouping and product funnels.

## 1. Go + Gin Application Telemetry

### Structured Logging with Stdlib `log/slog` (Zero Dependencies)
- Use `slog.New(slog.NewJSONHandler(os.Stdout, ...))` in production (Docker
  captures stdout cleanly for Promtail/Alloy -> Pigsty Loki).
- Attach `request_id` (`X-Request-Id`), `method`, `route` (`c.FullPath()`, NOT
  raw URL with IDs), `status`, `latency_ms`, and opaque `user_id` via Gin
  middleware.
- Redact `Authorization`, `Cookie`, and secret fields before logging.

### Sentry (`sentry-go` + `sentry-go/gin`)
- Initialize `sentry.Init(...)` once in `main()` with `defer sentry.Flush(2 * time.Second)`.
- Use `sentrygin.New(sentrygin.Options{ Repanic: true })` **before** Gin's
  `Recovery()` middleware, and copy `request_id` into `hub.Scope().SetTag("request_id", reqID)`.
- Keep `TracesSampleRate: 0.1` in production (`0.0` in dev) and
  `SendDefaultPII: false`.
- Only report unexpected `5xx` errors and panics to Sentry; log `4xx` client
  validation errors as structured `warn`/`info`.

### Liveness vs Readiness Probes
- `GET /healthz`: Fast in-memory `200 OK` (`status`, `version`, `uptime_s`) for
  Docker healthchecks and external uptime pings.
- `GET /readyz`: Verifies PostgreSQL `PingContext` + Valkey `PING` with a tight
  `1s` timeout; returns `503` if dependencies are degraded (protect or keep
  internal if exposed behind Caddy).

## 2. Caddy Reverse Proxy for PostHog & Sentry (Zero App Code)

Caddy handles TLS automatically and lets you bypass AdBlockers at the gateway
layer in ~12 lines inside `Caddyfile`:

```caddy
handle_path /ingest/static/* {
    reverse_proxy https://us-assets.i.posthog.com {
        header_up Host us-assets.i.posthog.com
        header_up -Cookie
    }
}

handle_path /ingest/* {
    reverse_proxy https://us.i.posthog.com {
        header_up Host us.i.posthog.com
        header_up -Cookie
    }
}
```

See [examples/go-gin-caddy/Caddyfile.snippet](./examples/go-gin-caddy/Caddyfile.snippet)
for the full reverse-proxy + health-routing snippet.

## 3. Integrating with Pigsty (PG + `pgmq` + Valkey + RustFS)

Pigsty ships out-of-the-box with **Prometheus / VictoriaMetrics, Grafana, Loki,
Alertmanager, `pg_exporter`, and `redis_exporter`**.

1. **Expose Go `/metrics`** (via `prometheus/client_golang` on an internal
   bind/port scraped by Pigsty Prometheus — never expose `/metrics` publicly
   through Caddy):
   - HTTP request rate, error rate (`5xx`), and latency histogram (`p50/p95/p99`)
     labeled by `route` (`c.FullPath()`) and `status_class` (never high-cardinality IDs).
   - Go runtime metrics (goroutines, heap alloc, GC pause).
2. **`pgmq` Queue Observability (Critical!)**:
   Errors alone miss silent worker stalls. Export or alert via `pg_exporter`
   custom SQL metrics on `pgmq.metrics_all()`:
   - **`queue_length`**: Alert if pending messages grow continuously.
   - **`oldest_msg_age_sec`**: Most important SLO metric — catches stuck
     consumers immediately even if queue length is small.
   - **Archive / dead-letter count**: Track poison messages moved to archive
     after max retries.
3. **Valkey & RustFS**:
   - Valkey: Watch memory usage (`used_memory / maxmemory`), eviction rate, and
     hit ratio via Pigsty's `redis_exporter`.
   - RustFS (S3-compatible): Expose its built-in Prometheus endpoint + monitor
     disk utilization and S3 API 5xx / p95 PUT/GET latency.

## 4. OpenTelemetry (OTel) Escape Hatch & Evolution Path

Start simple (Sentry + `slog` + Prometheus `/metrics`), and introduce
**OpenTelemetry** when you hit multi-service hops (e.g. Go API -> `pgmq` ->
async worker -> Python service):

1. Propagate W3C `traceparent` header across HTTP requests and into `pgmq`
   message headers JSON.
2. Instrument Gin (`otelgin`) and `pgx`/`database/sql` (`otelpgx`) to emit
   OTLP traces to an OpenTelemetry Collector (or directly to Sentry OTLP /
   Grafana Tempo).
3. Keep the facade pattern so switching trace/metric backends requires only
   exporter config changes, zero business-code rewrites.
