#!/usr/bin/env python3
"""Read-only production signal puller for `vibe-observability-loop`.

Zero external dependencies (Python 3.9+ stdlib only).
Safely fetches compact, AI-ready summaries from whichever sources are configured:
  - Sentry REST API (top unresolved issues sorted by affected users)
  - PostHog HogQL API (top event volumes + recent AI generation latency/tokens)
  - Local Python/cron job JSONL run summaries (status counts + anomalies)

Security rules:
  - Strictly read-only endpoints (Sentry GET issues, PostHog HogQL SELECT)
  - Never prints API tokens to stdout or stderr
  - Gracefully skips unconfigured sources without crashing
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

USER_AGENT = "vibe-observability-loop/0.2"


def _http_json(
    url: str,
    headers: Dict[str, str],
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
    timeout: float = 12.0,
) -> Any:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req_headers = {"User-Agent": USER_AGENT, "Accept": "application/json", **headers}
    if body is not None:
        req_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def pull_sentry_issues(days: int, limit: int, timeout: float = 12.0) -> Dict[str, Any]:
    token = os.getenv("SENTRY_AUTH_TOKEN", "").strip()
    org = os.getenv("SENTRY_ORG", "").strip()
    project = os.getenv("SENTRY_PROJECT", "").strip()
    base_url = os.getenv("SENTRY_BASE_URL", "https://sentry.io").rstrip("/")

    if not (token and org and project):
        return {
            "status": "skipped",
            "reason": "Set SENTRY_AUTH_TOKEN, SENTRY_ORG, and SENTRY_PROJECT (read-only token) to enable Sentry pull.",
            "issues": [],
        }

    params = urllib.parse.urlencode(
        {
            "query": "is:unresolved",
            "statsPeriod": f"{days}d",
            "sort": "user",
            "limit": str(limit),
        }
    )
    url = f"{base_url}/api/0/projects/{urllib.parse.quote(org)}/{urllib.parse.quote(project)}/issues/?{params}"

    try:
        raw = _http_json(url, headers={"Authorization": f"Bearer {token}"}, timeout=timeout)
    except urllib.error.HTTPError as exc:
        return {"status": "error", "reason": f"Sentry API HTTP {exc.code}", "issues": []}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "reason": f"Sentry request failed: {exc}", "issues": []}

    issues: List[Dict[str, Any]] = []
    for item in raw[:limit]:
        issues.append(
            {
                "short_id": item.get("shortId"),
                "title": item.get("title"),
                "culprit": item.get("culprit"),
                "level": item.get("level"),
                "events": int(item.get("count", 0) or 0),
                "users": int(item.get("userCount", 0) or 0),
                "first_seen": item.get("firstSeen"),
                "last_seen": item.get("lastSeen"),
                "permalink": item.get("permalink"),
            }
        )

    return {"status": "ok", "count": len(issues), "issues": issues}


def pull_posthog_signals(days: int, limit: int, timeout: float = 12.0) -> Dict[str, Any]:
    api_key = os.getenv("POSTHOG_PERSONAL_API_KEY", "").strip()
    project_id = os.getenv("POSTHOG_PROJECT_ID", "").strip()
    host = os.getenv("POSTHOG_HOST", "https://us.posthog.com").rstrip("/")

    if not (api_key and project_id):
        return {
            "status": "skipped",
            "reason": "Set POSTHOG_PERSONAL_API_KEY and POSTHOG_PROJECT_ID (read-only key) to enable PostHog pull.",
            "top_events": [],
            "ai_generations": None,
        }

    url = f"{host}/api/projects/{urllib.parse.quote(project_id)}/query/"
    headers = {"Authorization": f"Bearer {api_key}"}

    top_events_query = {
        "query": {
            "kind": "HogQLQuery",
            "query": (
                "SELECT event, count() AS total, count(DISTINCT distinct_id) AS unique_users "
                f"FROM events WHERE timestamp >= now() - INTERVAL {int(days)} DAY "
                f"GROUP BY event ORDER BY total DESC LIMIT {int(limit)}"
            ),
        }
    }

    try:
        ev_resp = _http_json(url, headers=headers, method="POST", payload=top_events_query, timeout=timeout)
    except urllib.error.HTTPError as exc:
        return {"status": "error", "reason": f"PostHog API HTTP {exc.code}", "top_events": [], "ai_generations": None}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "reason": f"PostHog request failed: {exc}", "top_events": [], "ai_generations": None}

    top_events = [
        {"event": row[0], "total": row[1], "unique_users": row[2]}
        for row in ev_resp.get("results", [])
        if isinstance(row, list) and len(row) >= 3
    ]

    # Optional LLM generation summary if $ai_generation exists
    ai_summary = None
    if any(e["event"] == "$ai_generation" for e in top_events):
        ai_query = {
            "query": {
                "kind": "HogQLQuery",
                "query": (
                    "SELECT properties.$ai_model AS model, count() AS calls, "
                    "round(avg(toFloat(properties.$ai_latency)), 3) AS avg_latency_s, "
                    "sum(toInt(properties.$ai_input_tokens)) AS input_tokens, "
                    "sum(toInt(properties.$ai_output_tokens)) AS output_tokens "
                    f"FROM events WHERE event = '$ai_generation' AND timestamp >= now() - INTERVAL {int(days)} DAY "
                    "GROUP BY model ORDER BY calls DESC LIMIT 10"
                ),
            }
        }
        try:
            ai_resp = _http_json(url, headers=headers, method="POST", payload=ai_query, timeout=timeout)
            ai_summary = [
                {
                    "model": row[0],
                    "calls": row[1],
                    "avg_latency_s": row[2],
                    "input_tokens": row[3],
                    "output_tokens": row[4],
                }
                for row in ai_resp.get("results", [])
                if isinstance(row, list) and len(row) >= 5
            ]
        except Exception:  # noqa: BLE001
            ai_summary = None

    return {"status": "ok", "top_events": top_events, "ai_generations": ai_summary}


def pull_job_history(history_path: Optional[Path], limit: int) -> Dict[str, Any]:
    if history_path is None:
        return {"status": "skipped", "reason": "Pass --job-history <path.jsonl> to inspect local scraper/job runs.", "jobs": {}}
    if not history_path.is_file():
        return {"status": "error", "reason": f"Job history file not found: {history_path}", "jobs": {}}

    jobs: Dict[str, Dict[str, Any]] = {}
    for line in history_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-500:]:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        job = str(row.get("job", "unknown"))
        bucket = jobs.setdefault(
            job,
            {"runs": 0, "ok": 0, "degraded": 0, "failed": 0, "anomalies": [], "recent_items": []},
        )
        bucket["runs"] += 1
        st = str(row.get("status", "ok"))
        if st in {"ok", "degraded", "failed"}:
            bucket[st] += 1
        if row.get("anomaly_reason"):
            bucket["anomalies"].append({"run_id": row.get("run_id"), "reason": row.get("anomaly_reason")})
        if "items_fetched" in row:
            bucket["recent_items"].append(int(row["items_fetched"]))

    for bucket in jobs.values():
        bucket["anomalies"] = bucket["anomalies"][-limit:]
        bucket["recent_items"] = bucket["recent_items"][-10:]

    return {"status": "ok", "file": str(history_path), "jobs": jobs}


def render_markdown(bundle: Dict[str, Any]) -> str:
    lines: List[str] = [
        f"# Production Signals Brief (last {bundle['window_days']}d)",
        "",
    ]

    sentry = bundle["sentry"]
    lines.append(f"## 1. Sentry Top Issues ({sentry['status']})")
    if sentry["status"] != "ok":
        lines.append(f"- {sentry['reason']}")
    elif not sentry["issues"]:
        lines.append("- No unresolved issues in window.")
    else:
        for i in sentry["issues"]:
            lines.append(
                f"- **{i['short_id']}** ({i['users']} users / {i['events']} events) — {i['title']} "
                f"(`{i['culprit']}`)"
            )
    lines.append("")

    ph = bundle["posthog"]
    lines.append(f"## 2. PostHog Top Events ({ph['status']})")
    if ph["status"] != "ok":
        lines.append(f"- {ph['reason']}")
    elif not ph["top_events"]:
        lines.append("- No events returned in window.")
    else:
        for e in ph["top_events"]:
            lines.append(f"- `{e['event']}`: {e['total']} events ({e['unique_users']} unique users)")
        if ph.get("ai_generations"):
            lines.append("\n### LLM Generation Summary (`$ai_generation`)")
            for m in ph["ai_generations"]:
                lines.append(
                    f"- `{m['model']}`: {m['calls']} calls, avg {m['avg_latency_s']}s, "
                    f"in={m['input_tokens']} / out={m['output_tokens']} tokens"
                )
    lines.append("")

    jobs = bundle["jobs"]
    if jobs["status"] != "skipped":
        lines.append(f"## 3. Local Automation / Scraper Jobs ({jobs['status']})")
        if jobs["status"] != "ok":
            lines.append(f"- {jobs['reason']}")
        else:
            for name, stats in jobs["jobs"].items():
                lines.append(
                    f"- **{name}**: runs={stats['runs']} (ok={stats['ok']}, degraded={stats['degraded']}, failed={stats['failed']}), "
                    f"recent items={stats['recent_items']}"
                )
                for a in stats["anomalies"]:
                    lines.append(f"  - Anomaly ({a['run_id']}): {a['reason']}")
        lines.append("")

    return "\n".join(lines).rstrip()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pull compact read-only production signals from Sentry, PostHog, and local job logs for AI diagnosis."
    )
    parser.add_argument("--days", type=int, default=7, help="Lookback window in days (default: 7)")
    parser.add_argument("--limit", type=int, default=15, help="Max items per source (default: 15)")
    parser.add_argument("--job-history", type=Path, default=None, help="Optional path to local job_run_summary JSONL")
    parser.add_argument("--timeout", type=float, default=12.0, help="HTTP timeout in seconds (default: 12)")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON instead of Markdown")
    args = parser.parse_args(argv)

    bundle = {
        "window_days": args.days,
        "sentry": pull_sentry_issues(days=args.days, limit=args.limit, timeout=args.timeout),
        "posthog": pull_posthog_signals(days=args.days, limit=args.limit, timeout=args.timeout),
        "jobs": pull_job_history(args.job_history, limit=args.limit),
    }

    if args.as_json:
        print(json.dumps(bundle, indent=2, ensure_ascii=False))
    else:
        print(render_markdown(bundle))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
