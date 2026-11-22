# Standardized Event Taxonomy

Consistent event naming is what makes AI-driven analysis (`vibe-observability-loop`)
accurate. Without a schema, an AI coding session will invent five names for the
same button across five PRs.

## Naming Rules

1. **Format**: `snake_case`, strictly **`<object>_<past_tense_action>`**
   - Good: `signup_completed`, `checkout_started`, `project_created`,
     `generation_failed`, `upgrade_cta_clicked`
   - Bad: `clickBuy`, `User Signed Up`, `handleSubmit`, `button_click`
2. **Keep cardinality low in event names**: Put variants in properties, not in
   the event name.
   - Good: `cta_clicked` with `{ location: "hero", variant: "try_free" }`
   - Bad: `hero_try_free_cta_clicked_v2`
3. **Standard property types**:
   - Booleans start with `is_` or `has_` (`is_annual`, `has_promo_code`).
   - Durations end with `_ms` or `_s` (`latency_ms`, `duration_s`).
   - Monetary amounts use integer minor units or explicit currency
     (`amount_cents`, `currency`).

## Core Starter Catalogs

### Universal SaaS Funnel (Start Here)

| Event Name | Trigger | Key Safe Properties |
| :--- | :--- | :--- |
| `landing_viewed` | Hero rendered (if custom beyond `$pageview`) | `utm_source`, `referrer_domain` |
| `signup_started` | Auth modal/page opened or OAuth clicked | `method` (`google`/`github`/`email`) |
| `signup_completed` | Account created (prefer server-side too) | `method` |
| `onboarding_step_completed` | User finishes an onboarding step | `step_index`, `step_name` |
| `activation_achieved` | User hits the product's "Aha!" moment | `time_since_signup_s` |
| `pricing_viewed` | Pricing page or paywall displayed | `source`, `current_plan` |
| `checkout_started` | Checkout session initiated | `plan`, `billing_cycle`, `amount_cents`, `currency` |
| `subscription_activated` | **Server-side webhook** confirms payment | `plan`, `billing_cycle`, `amount_cents`, `currency` |
| `feature_used` | High-value core action performed | `feature_name`, `entry_point` |
| `action_failed` | User-facing recoverable failure | `action_name`, `error_code`, `request_id` |

### AI / LLM Product Extensions (`ai-app` Profile)

| Event Name | Trigger | Key Safe Properties |
| :--- | :--- | :--- |
| `generation_requested` | User submits a prompt / runs an agent | `feature`, `model`, `prompt_version` |
| `generation_completed` | Response finishes streaming | `model`, `latency_ms`, `ttft_ms`, `input_tokens`, `output_tokens`, `estimated_cost_usd` |
| `generation_failed` | Model timeout, rate limit, or parse error | `model`, `error_type`, `retry_count`, `request_id` |
| `generation_feedback_given` | User clicks thumbs up/down, copy, or regenerate | `feedback` (`positive`/`negative`/`copied`/`regenerated`), `model`, `prompt_version` |

## Minimalist Rule (Avoid Tracking Noise)

Instrument **8–15 high-signal events** covering Acquisition -> Activation ->
Retention -> Revenue -> Errors first. Do not manually instrument every hover or
minor toggle — PostHog autocapture and Clarity heatmaps already cover micro
interactions without cluttering your codebase.
