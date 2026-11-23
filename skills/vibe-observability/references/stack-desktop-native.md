# Stack Adapter: Desktop & Native Apps (Electron, Wails v3, Tauri 2, Swift, Kotlin)

Desktop and native mobile/OS apps have fundamentally different trust boundaries,
networking conditions, and failure modes than websites.

## Non-Negotiable Rules for Desktop & Native

1. **NEVER install GA4 or Microsoft Clarity.**
   - Custom protocols (`wails://`, `tauri://`, `app://`, `file://`) break web
     cookies/referrers and cause silent script errors.
   - Desktop users inspect outbound traffic (Little Snitch, Proxyman) — shipping
     silent session-replay / mouse-tracking SDKs in a local app destroys trust.
2. **Always provide a visible Privacy / Telemetry Opt-Out toggle** in Settings
   (default off or clearly disclosed opt-in for local-first utilities).
3. **Always provide "Export Diagnostic Logs"** (local rotating JSON/text log
   folder with secrets stripped) — offline users and firewall environments
   depend on local logs when cloud crash reporting cannot connect.

---

## 1. Electron + React + Vite

- **Crash & Error Capture**: Use **`@sentry/electron`** (initializes in **both**
  `main` process and `renderer` process, plus captures native C++/V8 crashes
  via Crashpad/minidump).
  - Never use `@sentry/react` alone — you will miss main-process crashes and IPC
    failures.
  - Upload source maps for renderer bundles and delete `.map` files before
    packaging (`electron-builder` / Forge).
- **Local Logs**: Use `electron-log` (or `pino` writing to `app.getPath("logs")`)
  with rotation (e.g. max 5 files × 5MB) and automatic redaction of tokens/paths.
- **IPC Tracing**: Attach a short `ipc_id` on slow/critical `ipcMain.handle`
  calls and log duration + error code (never log full file contents).
- **Product Analytics (Optional)**: PostHog (`posthog-js` or main-process
  `posthog-node`) with **`disable_session_recording: true`**, `autocapture: false`,
  and explicit opt-out persisted in user settings.

## 2. Go + Wails v3 + SQLite

- **Go Backend**:
  - `log/slog` JSON handler writing to a rotating file (`lumberjack`) in the OS
    app-data log dir (`os.UserConfigDir()` / `~/Library/Logs/<AppName>`).
  - `sentry-go` capturing panics (`defer sentry.Recover()`) and unexpected
    errors (respecting the user's opt-out setting).
- **SQLite Specifics**:
  - Explicitly log and count `SQLITE_BUSY` / lock timeouts, migration versions,
    and slow queries (>100ms). Enable WAL mode (`PRAGMA journal_mode=WAL`) and
    `busy_timeout` before chasing phantom lock errors.
- **WebView Frontend**:
  - Forward unhandled `window.onerror` / `unhandledrejection` to Go via a Wails
    binding so frontend and backend errors land in one unified local log file
    and respect one single telemetry opt-out flag.

## 3. Windows / Cross-Platform Rust (Tauri 2 / Win32)

- **Rust Core**:
  - Use `tracing` + `tracing-subscriber` + `tracing-appender` (daily/size-capped
    rolling file in OS app-log directory).
  - Use the `sentry` crate (with `sentry-tracing` layer) or `sentry-tauri` for
    Rust panics + native minidumps (`sentry-minidump` / Crashpad on Windows).
  - Never silently swallow errors with `.unwrap()` in UI commands — convert to
    typed error enums logged with context.
- **Tauri 2 WebView**:
  - Use `tauri-plugin-log` to pipe JS warnings/errors into the same Rust log
    sink; keep GA4/Clarity completely out.

## 4. Apple Native: macOS & iOS (Swift)

- **Structured System Logging (Zero Cost)**: Use Apple's native `OSLog` /
  `Logger(subsystem: "com.yourapp", category: "sync")`.
  - Use `\(userId, privacy: .public)` for opaque IDs and rely on default
    `.private` redaction for user strings/paths so Console/sysdiagnose stays
    privacy-safe.
- **System Diagnostics**: Subscribe to **`MetricKit`** (`MXMetricManager`) to
  receive OS-collected crash payloads, hang diagnostics, memory peaks, and
  battery/launch-time histograms directly from real devices.
- **Crash & Event SDK**: `sentry-cocoa` (configure dSYM upload in Xcode Cloud /
  CI build phase, `sendDefaultPii = false`) + optional `posthog-ios` (no
  unconsented screen replay).

## 5. Android Native (Kotlin)

- **Crash, ANR & Native NDK**: Use **`sentry-android`** (captures Java/Kotlin
  exceptions, ANR deadlocks, and JNI/NDK crashes). Upload ProGuard/R8 mapping
  files via the Sentry Android Gradle plugin.
- **Structured Local Logging**: Wrap `Timber` (or custom logger) to strip PII in
  release builds and route `ERROR` breadcrumbs into Sentry.
- **Analytics (Optional)**: `posthog-android` with explicit user consent /
  opt-out setting and screen-capture masking enabled if replay is ever used.
