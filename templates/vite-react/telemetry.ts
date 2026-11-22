/**
 * Unified, type-safe telemetry facade for Vite + React SPAs.
 *
 * Uses `import.meta.env.PROD` for automatic local dev isolation, enforces
 * `maskAllInputs: true`, `person_profiles: "identified_only"`, and links
 * Sentry crashes to PostHog session replays.
 */

import posthog from "posthog-js";
import * as Sentry from "@sentry/react";

export type EventMap = {
  signup_started: { method: "google" | "github" | "email" };
  signup_completed: { method: "google" | "github" | "email" };
  feature_used: { feature_name: string };
  action_failed: { action_name: string; error_code?: string; request_id?: string };
};

export type EventName = keyof EventMap;

const SENSITIVE_KEY_RE = /pass(word)?|secret|token|api[-_]?key|credit|card|ssn|cvv/i;

function isEnabled(): boolean {
  return (
    Boolean(import.meta.env.PROD) ||
    import.meta.env.VITE_OBSERVABILITY_DEBUG === "true"
  );
}

function scrub(props: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(props).filter(([key]) => !SENSITIVE_KEY_RE.test(key))
  );
}

export const telemetry = {
  init(): void {
    const enabled = isEnabled();

    const sentryDsn = import.meta.env.VITE_SENTRY_DSN;
    if (sentryDsn) {
      Sentry.init({
        dsn: sentryDsn,
        enabled,
        environment: import.meta.env.MODE,
        release: import.meta.env.VITE_GIT_SHA,
        tracesSampleRate: import.meta.env.PROD ? 0.1 : 0,
        replaysSessionSampleRate: 0,
        replaysOnErrorSampleRate: 0,
        sendDefaultPii: false,
      });
    }

    const posthogKey = import.meta.env.VITE_POSTHOG_KEY;
    if (posthogKey) {
      posthog.init(posthogKey, {
        api_host: import.meta.env.VITE_POSTHOG_PROXY || "/ingest",
        ui_host: import.meta.env.VITE_POSTHOG_HOST || "https://us.posthog.com",
        person_profiles: "identified_only",
        capture_pageview: "history_change",
        capture_pageleave: true,
        disable_session_recording: Boolean(import.meta.env.VITE_CLARITY_PROJECT_ID),
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

  identify(userId: string, traits?: Record<string, string | number | boolean>): void {
    if (!isEnabled()) return;
    if (posthog.__loaded) posthog.identify(userId, traits ? scrub(traits) : undefined);
    Sentry.setUser({ id: userId });
  },

  reset(): void {
    if (posthog.__loaded) posthog.reset();
    Sentry.setUser(null);
  },

  track<K extends EventName>(event: K, props: EventMap[K]): void {
    const safe = scrub(props as Record<string, unknown>);
    if (!isEnabled()) {
      console.debug("[telemetry:dev]", event, safe);
      return;
    }
    if (posthog.__loaded) posthog.capture(event, safe);
  },

  captureError(error: unknown, requestId?: string): void {
    Sentry.withScope((scope) => {
      if (requestId) scope.setTag("request_id", requestId);
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
