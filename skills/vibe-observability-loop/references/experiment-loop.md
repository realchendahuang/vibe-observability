# Verification & Anti-Fake-Optimization Loop

The biggest risk of an automated "AI reads metrics -> AI edits code" loop is
**cargo-cult optimization**: shipping constant churn based on statistical noise
and never verifying whether the change actually helped.

## 1. Match Verification Rigor to Change Type

| Change Type | How to Verify | Minimum Window |
| :--- | :--- | :--- |
| **Bug Fix / Crash / Broken CTA** | Error count for that fingerprint drops to 0 in the new `release`; Rage Clicks on target selector drop >80% | 24–48 hours (or >= 50 sessions hitting the flow) |
| **Performance Fix (LCP / API p95 / TTFT)** | Before/after p75 & p95 latency comparison across same traffic segment | 24–72 hours |
| **Product / UX / Pricing / Prompt Change** | PostHog Feature Flag A/B split (50/50) measuring primary conversion + guardrail metric | >= 7 days **and** >= 100–200 conversions per variant (for low-traffic MVPs, combine quantitative trend with 10+ session replays) |

## 2. Verification Report Template

After shipping a fix or experiment, record this block in the PR description or
iteration log so the next loop iteration has a baseline:

```markdown
### Observability Verification Contract
- **Release / Flag**: `<git_sha or flag_key>`
- **Hypothesis**: Fixing `<root cause>` will improve `<metric>` because `<evidence from Sentry/PostHog/Clarity>`.
- **Primary Metric**: `<event/ratio>` (Baseline: `X%` over `N` users)
- **Guardrails**: Error rate <= `Y%`, p95 latency <= `Z ms`
- **Check-in Date**: `<YYYY-MM-DD>`
- **Rollback Rule**: Revert / turn off flag immediately if `<condition>`.
```

## 3. Small-Traffic Honesty Rule (Indie / MVP Reality)

Early vibe-coded products often have 20–200 daily visitors — too small for
classical 95% p-value A/B tests on subtle button colors.
- **Do NOT pretend a 12-user lift from 2 to 4 signups is statistically
  significant.**
- At low traffic, focus the loop on **high-signal qualitative + deterministic
  wins**: zero crashes, zero broken mobile flows, zero dead clicks, fast load
  times, and watching 10 real onboarding replays.
- Reserve split A/B experiments for bold changes (pricing model, onboarding
  entry, core prompt architecture) once weekly volume supports them.

## 4. Close the Loop into Engineering Memory

Whenever a production incident reveals a recurring coding mistake (for example:
"Safari fails on `YYYY-MM-DD HH:mm` date strings" or "Next.js server actions
need explicit error capture"), propose adding a concise one-line rule to the
project's `AGENTS.md` / `GEMINI.md` so future vibe-coding sessions never
reintroduce the same class of bug.
