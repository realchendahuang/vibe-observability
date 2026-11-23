# Privacy, Compliance & Cost-Explosion Guardrails

Rapid AI-generated apps frequently trip over two hidden landmines: leaking
sensitive user data into third-party trackers, and blowing through SaaS quotas
overnight due to an accidental client render loop.

## 1. Environment Isolation (Keep Production Clean)

- **Default OFF in `development` and `test`**: Browser and server telemetry
  must remain disabled on `localhost` / CI unless explicitly opted in via
  `OBSERVABILITY_DEBUG=true` (or your framework's public prefix such as
  `VITE_OBSERVABILITY_DEBUG=true` / `NEXT_PUBLIC_OBSERVABILITY_DEBUG=true`).
- **Separate Staging vs Production**: Always tag `environment` (`production`,
  `preview`, `staging`) and prefer separate Sentry/PostHog projects or explicit
  environment filters so PR previews never pollute conversion funnels.

## 2. PII & Secret Scrubbing Rules

| Data Type | Sentry | PostHog | GA4 | Clarity |
| :--- | :--- | :--- | :--- | :--- |
| Passwords, OTPs, Credit Cards, API Keys | **NEVER** | **NEVER** | **NEVER** | **NEVER** |
| Raw `Authorization` / `Cookie` Headers | Strip in `beforeSend` | Never send | Never send | Never send |
| Email / Phone / Full Name | Off (`sendDefaultPii: false`) | Opt-in only if policy permits | **STRICTLY FORBIDDEN** | **Avoid / Mask** |
| Opaque Database `user_id` (UUID) | Allowed | Allowed | Allowed | Allowed |

### Mandatory Recording Masks
- PostHog Session Replay: `maskAllInputs: true` + `maskTextSelector: "[data-ph-mask]"` + `blockSelector: "[data-ph-no-capture]"`.
- Microsoft Clarity: Add `data-clarity-mask="true"` on sensitive widgets (billing,
  API keys, personal dashboards) and enable **Strict** masking in dashboard.
- Telemetry Facade: Run a shallow key sanitizer before sending properties to
  strip keys matching `/pass(word)?|secret|token|api[-_]?key|credit|card|ssn|cvv/i`
  (and additionally `email|phone|name` before GA4 dispatch).

## 3. Consent Management (GDPR / ePrivacy Ready)

If the product targets EEA/UK users or commercial B2B customers:
- Expose `telemetry.setConsent(granted: boolean)` in the facade.
- Support a simple config flag (`REQUIRE_CONSENT=true`):
  - PostHog: `opt_out_capturing_by_default: true` until `opt_in_capturing()`.
  - GA4: Google Consent Mode v2 (`denied` by default, `update` on accept).
  - Clarity: `Clarity.consent(granted)`.
- Note: Essential error monitoring (Sentry with `sendDefaultPii: false`, no
  replay, no tracking cookies) generally falls under legitimate interest /
  strictly necessary security diagnostics, while behavioral analytics & replay
  require consent in strict regions. (Remind users to verify with legal counsel
  for regulated domains like HIPAA/FinTech.)

## 4. Cost-Explosion & Quota Guardrails

Vibe-coded apps are uniquely vulnerable to runaway event volume:

1. **Client Burst Guard**: Cap identical `track()` calls per tab (e.g. max 20
   occurrences of the same event per 10 seconds) to neutralize broken React
   `useEffect` dependency loops.
2. **PostHog `person_profiles: "identified_only"`**: Prevents paying for full
   person profiles on anonymous bounce traffic (often cuts bill by 60–80%).
3. **Sentry Sampling Budgets**:
   - `tracesSampleRate`: `0.1` (10%) in production, `0` in dev; never `1.0`
     unless low-volume and explicitly intentional.
   - `ignoreErrors`: Drop noisy browser-extension and ResizeObserver errors.
4. **Provider-Side Hard Caps (Include in User Handoff)**:
   - **Sentry**: Enable *Spend Allocation / Spike Protection* and set monthly
     quota alerts at 50% and 80%.
   - **PostHog**: Set *Billing Limits* (e.g. `$0` on free tier) so overages
     pause ingestion cleanly instead of charging your card unexpectedly.
