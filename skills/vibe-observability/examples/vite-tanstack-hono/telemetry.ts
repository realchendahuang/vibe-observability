/**
 * Unified, type-safe telemetry facade for Vite (incl. Vite 8) + React +
 * TanStack Router / Query + Better Auth + Hono.
 *
 * Guardrails built in:
 * - Disabled in dev and test (Vitest / Playwright) unless VITE_OBSERVABILITY_DEBUG=true
 * - Strict PII scrubbing & client burst guard (neutralizes infinite useEffect loops)
 * - Automatic replay deduplication (disables PostHog replay if Clarity ID is set)
 * - Sentry <-> PostHog cross-linking (jump straight from crash to replay)
 * - Ready-to-wire TanStack Query error handler (ignores 4xx noise, captures 5xx)
 */

import posthog from "posthog-js";
import * as Sentry from "@sentry/react";

export type TelemetryEventMap = {
  signup_started: { method: "google" | "github" | "email" };
  signup_completed: { method: "google" | "github" | "email" };
  activation_achieved: { time_since_signup_s?: number };
  feature_used: { feature_name: string; entry_point?: string };
  web_vital_measured: { name: "LCP" | "INP" | "CLS" | "TTFB"; value: number; rating: string };
  action_failed: { action_name: string; error_code?: string; request_id?: string };
};

export type TelemetryEventName = keyof TelemetryEventMap;

export interface SafeUserTraits {
  plan?: string;
  role?: string;
  locale?: string;
}

const SENSITIVE_KEY_RE = /pass(word)?|secret|token|cookie|api[-_]?key|credit|card|ssn|cvv/i;
const GA4_PII_KEY_RE = /email|phone|full_?name|address/i;

const BURST_WINDOW_MS = 10_000;
const BURST_MAX_COUNT = 20;
const burstLedger = new Map<string, number[]>();

let initialized = false;

function isTelemetryEnabled(): boolean {
  if (typeof window === "undefined") return false;
  if (import.meta.env.MODE === "test") return false;
  return (
    Boolean(import.meta.env.PROD) ||
    import.meta.env.VITE_OBSERVABILITY_DEBUG === "true"
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

function allowBurst(eventName: string): boolean {
  const now = Date.now();
  const recent = (burstLedger.get(eventName) ?? []).filter(
    (ts) => now - ts < BURST_WINDOW_MS
  );
  if (recent.length >= BURST_MAX_COUNT) {
    if (import.meta.env.DEV) {
      console.warn(`[telemetry] Burst guard tripped for "${eventName}". Check effect dependencies.`);
    }
    burstLedger.set(eventName, recent);
    return false;
  }
  recent.push(now);
  burstLedger.set(eventName, recent);
  return true;
}

export const telemetry = {
  init(options?: { routerIntegration?: ReturnType<typeof Sentry.browserTracingIntegration> }): void {
    if (initialized || typeof window === "undefined") return;
    initialized = true;

    const enabled = isTelemetryEnabled();
    const sentryDsn = import.meta.env.VITE_SENTRY_DSN;

    if (sentryDsn) {
      Sentry.init({
        dsn: sentryDsn,
        enabled,
        environment: import.meta.env.MODE,
        release: import.meta.env.VITE_GIT_SHA,
        integrations: options?.routerIntegration ? [options.routerIntegration] : [],
        tracesSampleRate: import.meta.env.PROD ? 0.1 : 0,
        replaysSessionSampleRate: 0,
        replaysOnErrorSampleRate: 0,
        sendDefaultPii: false,
        beforeSend(event) {
          if (event.request?.headers) {
            delete event.request.headers.authorization;
            delete event.request.headers.cookie;
          }
          return event;
        },
      });
    }

    const posthogKey = import.meta.env.VITE_POSTHOG_KEY;
    const useClarityForReplay = Boolean(import.meta.env.VITE_CLARITY_PROJECT_ID);

    if (posthogKey) {
      posthog.init(posthogKey, {
        api_host: import.meta.env.VITE_POSTHOG_PROXY || "/ingest",
        ui_host: import.meta.env.VITE_POSTHOG_HOST || "https://us.posthog.com",
        person_profiles: "identified_only",
        capture_pageview: "history_change",
        capture_pageleave: true,
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

  /** Call from Better Auth session observer when user logs in. */
  identify(userId: string, traits?: SafeUserTraits): void {
    if (!isTelemetryEnabled()) return;
    const safeTraits = traits ? sanitizeProps(traits as Record<string, unknown>, true) : undefined;
    if (posthog.__loaded) posthog.identify(userId, safeTraits);
    Sentry.setUser({ id: userId });
  },

  /** Call immediately on Better Auth signOut(). */
  reset(): void {
    if (posthog.__loaded) posthog.reset();
    Sentry.setUser(null);
  },

  track<K extends TelemetryEventName>(event: K, props: TelemetryEventMap[K]): void {
    if (!allowBurst(event)) return;
    const safe = sanitizeProps(props as Record<string, unknown>, false);
    if (!isTelemetryEnabled()) {
      if (import.meta.env.DEV) console.debug("[telemetry:dev]", event, safe);
      return;
    }
    if (posthog.__loaded) posthog.capture(event, safe);
    const gtagFn = (window as unknown as { gtag?: (...args: unknown[]) => void }).gtag;
    if (gtagFn) gtagFn("event", event, sanitizeProps(safe, true));
  },

  captureError(
    error: unknown,
    context?: { action?: string; requestId?: string; status?: number }
  ): void {
    // Filter expected client validation / auth states
    if (context?.status && context.status >= 400 && context.status < 500) return;

    Sentry.withScope((scope) => {
      if (context?.action) scope.setTag("action", context.action);
      if (context?.requestId) scope.setTag("request_id", context.requestId);
      if (posthog.__loaded) {
        const distinctId = posthog.get_distinct_id?.();
        const replayUrl = posthog.get_session_replay_url?.({ withTimestamp: true });
        if (distinctId) scope.setTag("posthog_distinct_id", distinctId);
        if (replayUrl) scope.setContext("posthog", { session_replay_url: replayUrl });
      }
      Sentry.captureException(error);
    });
  },
};
