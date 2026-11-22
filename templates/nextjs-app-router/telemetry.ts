"use client";

/**
 * Unified, type-safe telemetry facade for Next.js (App Router).
 *
 * Features built-in:
 * - Single typed event taxonomy (prevents naming drift across AI sessions)
 * - Automatic dev-environment opt-out (keeps prod funnels clean)
 * - PII scrubbing before dispatch (especially strict for GA4)
 * - Client-side burst limiter (neutralizes infinite useEffect loops)
 * - Cross-linking: Sentry <-> PostHog (jump from error straight to replay)
 * - Replay deduplication: disables PostHog replay if Clarity is configured
 */

import posthog from "posthog-js";
import * as Sentry from "@sentry/nextjs";

export type TelemetryEventMap = {
  signup_started: { method: "google" | "github" | "email" };
  signup_completed: { method: "google" | "github" | "email" };
  activation_achieved: { time_since_signup_s?: number };
  pricing_viewed: { source?: string; current_plan?: string };
  checkout_started: {
    plan: string;
    billing_cycle: "monthly" | "annual";
    amount_cents: number;
    currency: string;
  };
  feature_used: { feature_name: string; entry_point?: string };
  action_failed: { action_name: string; error_code?: string; request_id?: string };
};

export type TelemetryEventName = keyof TelemetryEventMap;

export interface SafeUserTraits {
  plan?: string;
  role?: string;
  workspace_tier?: string;
  locale?: string;
}

const SENSITIVE_KEY_RE = /pass(word)?|secret|token|api[-_]?key|credit|card|ssn|cvv/i;
const GA4_PII_KEY_RE = /email|phone|full_?name|address/i;

const BURST_WINDOW_MS = 10_000;
const BURST_MAX_COUNT = 20;
const burstLedger = new Map<string, number[]>();

let initialized = false;

function isTelemetryEnabled(): boolean {
  if (typeof window === "undefined") return false;
  return (
    process.env.NODE_ENV === "production" ||
    process.env.NEXT_PUBLIC_OBSERVABILITY_DEBUG === "true"
  );
}

function sanitizeProps(
  props: Record<string, unknown>,
  stripPii = false
): Record<string, unknown> {
  const clean: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(props)) {
    if (SENSITIVE_KEY_RE.test(key)) continue;
    if (stripPii && GA4_PII_KEY_RE.test(key)) continue;
    clean[key] = value;
  }
  return clean;
}

function allowEventBurst(eventName: string): boolean {
  const now = Date.now();
  const timestamps = (burstLedger.get(eventName) ?? []).filter(
    (t) => now - t < BURST_WINDOW_MS
  );
  if (timestamps.length >= BURST_MAX_COUNT) {
    if (process.env.NODE_ENV !== "production") {
      console.warn(
        `[telemetry] Burst guard tripped for "${eventName}" (>${BURST_MAX_COUNT} calls in ${BURST_WINDOW_MS}ms). Check React useEffect dependencies.`
      );
    }
    burstLedger.set(eventName, timestamps);
    return false;
  }
  timestamps.push(now);
  burstLedger.set(eventName, timestamps);
  return true;
}

export const telemetry = {
  init(): void {
    if (initialized || typeof window === "undefined") return;
    initialized = true;

    const enabled = isTelemetryEnabled();
    const posthogKey = process.env.NEXT_PUBLIC_POSTHOG_KEY;
    const clarityId = process.env.NEXT_PUBLIC_CLARITY_PROJECT_ID;
    const useClarityForReplay = Boolean(clarityId);

    if (posthogKey) {
      posthog.init(posthogKey, {
        api_host: "/ingest",
        ui_host: process.env.NEXT_PUBLIC_POSTHOG_HOST || "https://us.posthog.com",
        person_profiles: "identified_only",
        capture_pageview: "history_change",
        capture_pageleave: true,
        // Never double-record DOM mutations when Clarity is active
        disable_session_recording: useClarityForReplay,
        session_recording: {
          maskAllInputs: true,
          maskTextSelector: "[data-ph-mask]",
          blockSelector: "[data-ph-no-capture]",
        },
        loaded: (ph) => {
          if (!enabled) ph.opt_out_capturing();
        },
      });
    }
  },

  identify(userId: string, traits?: SafeUserTraits): void {
    if (!isTelemetryEnabled()) return;
    const safeTraits = traits ? sanitizeProps(traits as Record<string, unknown>, true) : undefined;

    if (posthog.__loaded) {
      posthog.identify(userId, safeTraits);
    }
    Sentry.setUser({ id: userId });

    const clarityFn = (window as unknown as { clarity?: (...args: unknown[]) => void }).clarity;
    clarityFn?.("identify", userId);
  },

  reset(): void {
    if (typeof window === "undefined") return;
    if (posthog.__loaded) {
      posthog.reset();
    }
    Sentry.setUser(null);
  },

  track<K extends TelemetryEventName>(event: K, props: TelemetryEventMap[K]): void {
    if (!allowEventBurst(event)) return;

    const safeProps = sanitizeProps(props as Record<string, unknown>, false);
    if (!isTelemetryEnabled()) {
      if (process.env.NODE_ENV !== "production") {
        console.debug("[telemetry:dev]", event, safeProps);
      }
      return;
    }

    if (posthog.__loaded) {
      posthog.capture(event, safeProps);
    }

    const gtagFn = (window as unknown as { gtag?: (...args: unknown[]) => void }).gtag;
    if (gtagFn) {
      gtagFn("event", event, sanitizeProps(safeProps, true));
    }
  },

  captureError(error: unknown, context?: { action?: string; requestId?: string; extra?: Record<string, unknown> }): void {
    Sentry.withScope((scope) => {
      if (context?.action) scope.setTag("action", context.action);
      if (context?.requestId) scope.setTag("request_id", context.requestId);

      // Cross-link Sentry crash -> PostHog Session Replay
      if (typeof window !== "undefined" && posthog.__loaded) {
        const distinctId = posthog.get_distinct_id?.();
        const replayUrl = posthog.get_session_replay_url?.({ withTimestamp: true });
        if (distinctId) scope.setTag("posthog_distinct_id", distinctId);
        if (replayUrl) scope.setContext("posthog", { session_replay_url: replayUrl });
      }

      if (context?.extra) {
        scope.setExtras(sanitizeProps(context.extra, false));
      }
      Sentry.captureException(error);
    });
  },

  setConsent(granted: boolean): void {
    if (typeof window === "undefined") return;
    if (posthog.__loaded) {
      if (granted) posthog.opt_in_capturing();
      else posthog.opt_out_capturing();
    }
    const gtagFn = (window as unknown as { gtag?: (...args: unknown[]) => void }).gtag;
    gtagFn?.("consent", "update", {
      ad_storage: granted ? "granted" : "denied",
      ad_user_data: granted ? "granted" : "denied",
      ad_personalization: granted ? "granted" : "denied",
      analytics_storage: granted ? "granted" : "denied",
    });
    const clarityFn = (window as unknown as { clarity?: (...args: unknown[]) => void }).clarity;
    clarityFn?.("consent", granted);
  },
};
