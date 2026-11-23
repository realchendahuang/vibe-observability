# GA4 & Microsoft Clarity Setup (Async, Consent-Aware & Deduped)

Use GA4 and Microsoft Clarity in the `marketing` profile (full free-tier stack
for SEO/ads/landing sites) or `full-deduped` profile (alongside PostHog with
PostHog replay disabled).

## 1. Environment Variables

Use your framework's browser prefix (`VITE_`, `NEXT_PUBLIC_`, `PUBLIC_`, etc.):

```env
<PUBLIC_PREFIX>_GA_MEASUREMENT_ID=   # e.g. G-XXXXXXXXXX
<PUBLIC_PREFIX>_CLARITY_PROJECT_ID=  # e.g. abcd1234ef
```

## 2. Google Analytics 4 (GA4) Best Practices

### Non-Blocking Loading
- **Next.js**: Use `@next/third-parties/google` (`<GoogleAnalytics gaId={...} />`)
  or `<Script strategy="afterInteractive">`, rendered **only** in production
  (or when debug opt-in is explicitly enabled).
- **Vite / SPA**: Inject the `gtag.js` script lazily inside `telemetry.init()`
  after checking `isProd` and consent state; avoid putting unguarded `<script>`
  tags in `index.html` that fire on `localhost`.

### Google Consent Mode v2 (Required for EEA/UK Traffic)
When operating in jurisdictions requiring cookie consent, set default denied
state **before** loading `gtag.js`, then call `gtag("consent", "update", ...)`
inside `telemetry.setConsent(true)`:

```ts
gtag("consent", "default", {
  ad_storage: "denied",
  ad_user_data: "denied",
  ad_personalization: "denied",
  analytics_storage: "denied",
  wait_for_update: 500,
});
```

### Strict PII Ban (Account Suspension Risk)
Google's Terms of Service **strictly forbid** sending Personally Identifiable
Information (email, phone number, full name, street address, IP) to GA4 in
event properties, page URLs, or `user_id`.
- Strip query parameters like `?email=...` or `?token=...` before sending
  `page_location`.
- Pass only an opaque database UUID (or SHA-256 hash) as `user_id`.

## 3. Microsoft Clarity Best Practices

Clarity excels at **zero-cost heatmaps**, **scroll depth**, **Rage Clicks**,
and **Dead Clicks** — signals that quickly reveal broken mobile layouts or
unresponsive AI-generated UI elements.

### Deduplication Rule (Critical)
- If Clarity is active **and** PostHog is active (`full-deduped`), PostHog
  **must** set `disable_session_recording: true`.
- Keep Sentry Session Replay disabled (`replaysSessionSampleRate: 0`).

### Safe Initialization & Masking
- Load via `@microsoft/clarity` (`Clarity.init(projectId)`) or async script
  injection inside `telemetry.init()`, guarded by `isProd`.
- **Masking sensitive UI**: Clarity masks password inputs automatically, and
  supports strict DOM attributes:
  - Add `data-clarity-mask="true"` to containers holding emails, API keys,
    billing numbers, or private user content.
  - Set masking mode to **Strict** in the Clarity project dashboard for SaaS
    apps with user-generated private data.
- **Cross-linking & Custom Tags**:
  - Call `Clarity.identify(opaqueUserId)` on login (Clarity hashes IDs client-side,
    still avoid passing raw emails).
  - Tag key states (`Clarity.setTag("plan", plan)`, `Clarity.setTag("app_version", sha)`)
    so you can filter Rage Clicks by release version or user tier.
  - Forward consent changes with `Clarity.consent(granted)` when consent gating
    is enabled.
