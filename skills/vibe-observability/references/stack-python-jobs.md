# Stack Adapter: Python + `uv` Scrapers & Automation Jobs

Data-collection scripts (e.g. Ego Lite authenticated scrapers, Python + `uv` ETL
pipelines, scheduled syncs) fail very differently from web apps. The deadliest
bug is **not** a crash — it is **exiting `0` with 0 items scraped** because the
target website changed its DOM or triggered anti-bot throttling.

## 1. The 4 Signals Every Automation Job Must Emit

1. **Heartbeat / Dead-Man's Switch (Did it actually run?)**:
   - Wrap every scheduled run with **Sentry Crons** (`sentry_sdk.monitor`) or a
     heartbeat ping (Better Stack / Healthchecks.io). If the cron machine dies,
     auth expires, or `uv` breaks, you get alerted when the check-in is missed.
2. **Structured JSON Run Logs (`structlog`)**:
   - Emit machine-parseable JSON lines containing `job_name`, `run_id` (UUID),
     `stage`, `target`, `duration_ms`, and `error_type`.
   - **Never** log raw session cookies, auth tokens, proxy credentials, or full
     HTML pages containing private account info.
3. **Mandatory End-of-Run Summary (`job_run_summary`)**:
   Every single run — success or failure — must emit one final structured record:
   ```json
   {
     "event": "job_run_summary",
     "job": "xhs_bookmarks_sync",
     "run_id": "a1b2c3d4",
     "status": "ok",
     "duration_s": 42.8,
     "pages_visited": 12,
     "items_fetched": 184,
     "items_new": 19,
     "empty_page_count": 0,
     "auth_expired": false,
     "challenge_hit": false,
     "error_count": 0
   }
   ```
4. **Volume-Drop & Silent-Failure Anomaly Detection**:
   - Persist lightweight run metrics (e.g. append to a local JSONL / SQLite table).
   - Compare `items_fetched` against the trailing median of the last 7 healthy
     runs. If `items_fetched == 0` or drops `> 50%` (or `auth_expired` /
     `challenge_hit` is true), emit a `warning`/`error` to Sentry or webhook
     **even if no Python exception was thrown**.

## 2. Authenticated Browser Scraping (Ego Lite / Playwright) Specifics

- **Separate Failure Categories**:
  - `auth_expired`: Redirected to login page or missing session indicator ->
    alert the operator to refresh login; do **not** retry in a tight loop.
  - `selector_drift`: Page loaded `200`, logged in, but expected CSS selector
    returned `0` elements -> save a compact DOM outline / screenshot locally
    (redacted) and raise a high-signal Sentry issue tagged `selector_drift`.
  - `rate_limited` / `challenge_hit`: HTTP 429 or anti-bot gate -> stop cleanly,
    record `challenge_hit: true`, and back off (never attempt to bypass).
- **Bounded Artifacts**: If saving failure screenshots/HTML locally for
  debugging, cap retention (e.g. keep latest 20 runs or 7 days) so disk never
  fills up.

## 3. Packaging & Execution (`uv`)

- Keep observability dependencies minimal in `pyproject.toml`:
  `structlog` + `sentry-sdk` (and `posthog` only if sending business funnel
  events).
- Always call `sentry_sdk.flush(timeout=5.0)` before script exit so short-lived
  CLI runs do not exit before sending the final event.

See [examples/python-uv-job/job_telemetry.py](./examples/python-uv-job/job_telemetry.py)
for a drop-in starter module with Run Summary, volume-drop detection, and
Sentry Cron check-in hooks.
