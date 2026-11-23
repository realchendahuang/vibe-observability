#!/usr/bin/env python3
"""Post-deploy live observability smoke verifier (zero external dependencies).

Catches the runtime deployment traps static code audits cannot see:
  - LIVE-001: Homepage unreachable or non-HTTPS in production
  - LIVE-002: Missing, failing, or slow health endpoint (/api/health or /healthz)
  - LIVE-003: PostHog /ingest reverse proxy intercepted by auth redirect (302/307) or SPA HTML fallback
  - LIVE-004: Sentry /monitoring tunnel intercepted by auth redirect
  - LIVE-005 (CRITICAL): Publicly exposed `.js.map` source maps leaking original source code
  - LIVE-006: Strict CSP header review notice for telemetry endpoints
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple

SEVERITY_RANK = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0, "PASS": -1}
USER_AGENT = "vibe-observability-verify/0.2"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


class _ScriptSrcParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() != "script":
            return
        attr_map = dict(attrs)
        src = attr_map.get("src")
        if src:
            self.scripts.append(src)


@dataclass
class CheckResult:
    id: str
    status: str  # PASS, INFO, LOW, MEDIUM, HIGH, CRITICAL
    title: str
    detail: str
    url: str = ""
    latency_ms: Optional[int] = None


def _http_request(
    url: str,
    method: str = "GET",
    timeout: float = 8.0,
    follow_redirects: bool = False,
    body: Optional[bytes] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[Optional[int], Dict[str, str], bytes, int, Optional[str]]:
    req_headers = {"User-Agent": USER_AGENT}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    opener = urllib.request.build_opener() if follow_redirects else urllib.request.build_opener(_NoRedirectHandler())
    start = time.monotonic()
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read(256_000)
            elapsed = int((time.monotonic() - start) * 1000)
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, hdrs, raw, elapsed, None
    except urllib.error.HTTPError as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        hdrs = {k.lower(): v for k, v in exc.headers.items()} if exc.headers else {}
        try:
            raw = exc.read(64_000)
        except OSError:
            raw = b""
        finally:
            exc.close()
        return exc.code, hdrs, raw, elapsed, None
    except Exception as exc:  # noqa: BLE001
        elapsed = int((time.monotonic() - start) * 1000)
        return None, {}, b"", elapsed, str(exc)


def verify_live(
    base_url: str,
    health_paths: List[str],
    ingest_path: Optional[str] = "/ingest",
    monitoring_path: Optional[str] = "/monitoring",
    max_scripts: int = 5,
    timeout: float = 8.0,
) -> Dict[str, object]:
    normalized = base_url.rstrip("/")
    parsed = urllib.parse.urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Invalid base URL: {base_url}")

    checks: List[CheckResult] = []
    origin = f"{parsed.scheme}://{parsed.netloc}"

    # 1. Homepage reachability, HTTPS & CSP
    status, headers, body, latency_ms, err = _http_request(normalized + "/", follow_redirects=True, timeout=timeout)
    if err or status is None:
        checks.append(
            CheckResult(
                id="LIVE-001",
                status="CRITICAL",
                title="Target site unreachable",
                detail=f"Failed to fetch homepage: {err}",
                url=normalized + "/",
                latency_ms=latency_ms,
            )
        )
        return _finalize_report(normalized, checks)

    if status >= 400:
        checks.append(
            CheckResult(
                id="LIVE-001",
                status="HIGH",
                title=f"Homepage returned HTTP {status}",
                detail="Expected 2xx response on root URL.",
                url=normalized + "/",
                latency_ms=latency_ms,
            )
        )
    else:
        checks.append(
            CheckResult(
                id="LIVE-001",
                status="PASS",
                title=f"Homepage healthy (HTTP {status})",
                detail=f"Responded in {latency_ms}ms.",
                url=normalized + "/",
                latency_ms=latency_ms,
            )
        )

    is_local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not is_local:
        checks.append(
            CheckResult(
                id="LIVE-001B",
                status="HIGH",
                title="Production URL is not using HTTPS",
                detail="Non-HTTPS deployments break secure cookies, Service Workers, and `crypto.randomUUID()`.",
                url=normalized,
            )
        )

    # 2. Health endpoint check
    health_ok = False
    last_health_detail = ""
    last_health_url = ""
    for hp in health_paths:
        url = f"{normalized}/{hp.lstrip('/')}"
        h_status, _, _, h_ms, h_err = _http_request(url, follow_redirects=False, timeout=timeout)
        last_health_url = url
        if h_status == 200:
            health_ok = True
            if h_ms > 1500:
                checks.append(
                    CheckResult(
                        id="LIVE-002",
                        status="MEDIUM",
                        title=f"Health probe is slow ({h_ms}ms)",
                        detail="Liveness probes should return in <100ms without heavy DB queries.",
                        url=url,
                        latency_ms=h_ms,
                    )
                )
            else:
                checks.append(
                    CheckResult(
                        id="LIVE-002",
                        status="PASS",
                        title=f"Health probe healthy (HTTP 200 in {h_ms}ms)",
                        detail="Ready for external uptime polling (Better Stack / UptimeRobot / Checkly).",
                        url=url,
                        latency_ms=h_ms,
                    )
                )
            break
        last_health_detail = f"{url} -> {h_err or f'HTTP {h_status}'}"

    if not health_ok:
        checks.append(
            CheckResult(
                id="LIVE-002",
                status="MEDIUM",
                title="No working health probe found",
                detail=f"Checked {', '.join(health_paths)}; last result: {last_health_detail}",
                url=last_health_url,
            )
        )

    # 3. PostHog /ingest reverse proxy check (no redirect following!)
    if ingest_path:
        ingest_url = f"{normalized}/{ingest_path.strip('/')}/static/array.js"
        i_status, i_hdrs, i_body, i_ms, i_err = _http_request(ingest_url, follow_redirects=False, timeout=timeout)
        ctype = i_hdrs.get("content-type", "")
        loc = i_hdrs.get("location", "")
        if i_err or i_status is None:
            checks.append(
                CheckResult(
                    id="LIVE-003",
                    status="MEDIUM",
                    title="PostHog reverse proxy probe failed",
                    detail=f"Connection error: {i_err}",
                    url=ingest_url,
                    latency_ms=i_ms,
                )
            )
        elif i_status in {301, 302, 303, 307, 308}:
            checks.append(
                CheckResult(
                    id="LIVE-003",
                    status="HIGH",
                    title=f"PostHog proxy redirected (HTTP {i_status} -> {loc or 'unknown'})",
                    detail="Auth or locale middleware is intercepting `/ingest`! Browser analytics will silently fail for unauthenticated users.",
                    url=ingest_url,
                    latency_ms=i_ms,
                )
            )
        elif i_status == 200 and "text/html" in ctype.lower():
            checks.append(
                CheckResult(
                    id="LIVE-003",
                    status="HIGH",
                    title="PostHog proxy returned HTML instead of JavaScript",
                    detail="Your SPA fallback or router swallowed `/ingest/static/array.js` instead of proxying to PostHog.",
                    url=ingest_url,
                    latency_ms=i_ms,
                )
            )
        elif i_status == 200:
            checks.append(
                CheckResult(
                    id="LIVE-003",
                    status="PASS",
                    title="PostHog first-party reverse proxy is live",
                    detail=f"Served `{ctype or 'asset'}` ({len(i_body)} bytes) without redirect.",
                    url=ingest_url,
                    latency_ms=i_ms,
                )
            )
        elif i_status == 404:
            checks.append(
                CheckResult(
                    id="LIVE-003",
                    status="INFO",
                    title="No PostHog `/ingest` reverse proxy detected (HTTP 404)",
                    detail="Expected if this site does not use PostHog; otherwise configure a first-party `/ingest` proxy to bypass AdBlockers.",
                    url=ingest_url,
                    latency_ms=i_ms,
                )
            )
        else:
            checks.append(
                CheckResult(
                    id="LIVE-003",
                    status="MEDIUM",
                    title=f"Unexpected HTTP {i_status} from PostHog proxy",
                    detail=f"Content-Type: {ctype or 'unknown'}",
                    url=ingest_url,
                    latency_ms=i_ms,
                )
            )

    # 4. Sentry /monitoring tunnel check
    if monitoring_path:
        mon_url = f"{normalized}/{monitoring_path.strip('/')}"
        m_status, m_hdrs, _, m_ms, m_err = _http_request(
            mon_url,
            method="POST",
            body=b"{}\n",
            headers={"Content-Type": "application/x-sentry-envelope"},
            follow_redirects=False,
            timeout=timeout,
        )
        m_loc = m_hdrs.get("location", "")
        if m_err or m_status is None:
            checks.append(
                CheckResult(
                    id="LIVE-004",
                    status="INFO",
                    title="Sentry tunnel probe could not connect",
                    detail=str(m_err),
                    url=mon_url,
                    latency_ms=m_ms,
                )
            )
        elif m_status in {301, 302, 303, 307, 308}:
            checks.append(
                CheckResult(
                    id="LIVE-004",
                    status="HIGH",
                    title=f"Sentry tunnel redirected (HTTP {m_status} -> {m_loc or 'unknown'})",
                    detail="Auth middleware is intercepting `/monitoring`; unauthenticated browser crashes will never reach Sentry.",
                    url=mon_url,
                    latency_ms=m_ms,
                )
            )
        elif m_status in {200, 400, 403, 422}:
            checks.append(
                CheckResult(
                    id="LIVE-004",
                    status="PASS",
                    title=f"Sentry tunnel endpoint reachable and validating payloads (HTTP {m_status})",
                    detail="Endpoint responded without auth redirect.",
                    url=mon_url,
                    latency_ms=m_ms,
                )
            )
        else:
            checks.append(
                CheckResult(
                    id="LIVE-004",
                    status="INFO",
                    title=f"No Sentry tunnel detected at `{monitoring_path}` (HTTP {m_status})",
                    detail="Optional; enable `/monitoring` tunnel to prevent AdBlockers from dropping Sentry errors.",
                    url=mon_url,
                    latency_ms=m_ms,
                )
            )

    # 5. Public Source Map leak check on same-origin JS bundles
    parser = _ScriptSrcParser()
    try:
        parser.feed(body.decode("utf-8", errors="ignore"))
    except Exception:  # noqa: BLE001
        pass

    same_origin_scripts: List[str] = []
    for src in parser.scripts:
        abs_url = urllib.parse.urljoin(normalized + "/", src)
        p = urllib.parse.urlparse(abs_url)
        if f"{p.scheme}://{p.netloc}" == origin and p.path.endswith(".js") and not p.path.startswith("/ingest/"):
            if abs_url not in same_origin_scripts:
                same_origin_scripts.append(abs_url)
        if len(same_origin_scripts) >= max_scripts:
            break

    leaked_maps: List[str] = []
    for js_url in same_origin_scripts:
        map_url = js_url + ".map"
        s_status, s_hdrs, s_body, _, _ = _http_request(map_url, method="GET", follow_redirects=False, timeout=timeout)
        if s_status == 200:
            s_ctype = s_hdrs.get("content-type", "").lower()
            if "text/html" not in s_ctype and (b'"mappings"' in s_body or b'"sources"' in s_body or "json" in s_ctype):
                leaked_maps.append(map_url)

    if leaked_maps:
        checks.append(
            CheckResult(
                id="LIVE-005",
                status="CRITICAL",
                title=f"Public source maps exposed ({len(leaked_maps)} file(s))",
                detail=f"Anyone can download original source code at: {', '.join(leaked_maps)}",
                url=leaked_maps[0],
            )
        )
    else:
        checks.append(
            CheckResult(
                id="LIVE-005",
                status="PASS",
                title=f"No public source maps exposed ({len(same_origin_scripts)} bundle(s) checked)",
                detail="No `.js.map` files returned source map JSON.",
                url=normalized,
            )
        )

    # 6. CSP telemetry review
    csp = headers.get("content-security-policy", "")
    if csp:
        connect_match = re.search(r"connect-src\s+([^;]+)", csp, re.IGNORECASE)
        if connect_match and "'self'" not in connect_match.group(1) and "*" not in connect_match.group(1):
            checks.append(
                CheckResult(
                    id="LIVE-006",
                    status="MEDIUM",
                    title="CSP `connect-src` does not include `'self'`",
                    detail=f"First-party `/ingest` and `/monitoring` requests may be blocked by CSP: `connect-src {connect_match.group(1)}`.",
                    url=normalized,
                )
            )
        else:
            checks.append(
                CheckResult(
                    id="LIVE-006",
                    status="PASS",
                    title="CSP header compatible with first-party telemetry proxies",
                    detail="Content-Security-Policy present without blocking `'self'`.",
                    url=normalized,
                )
            )

    return _finalize_report(normalized, checks)


def _finalize_report(target: str, checks: List[CheckResult]) -> Dict[str, object]:
    summary = {
        sev: sum(1 for c in checks if c.status == sev)
        for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO", "PASS")
    }
    return {
        "target_url": target,
        "summary": summary,
        "checks": [asdict(c) for c in checks],
    }


def render_text(report: Dict[str, object]) -> str:
    s = report["summary"]
    lines = [
        f"Vibe Observability Live Smoke Check — {report['target_url']}",
        "=" * 68,
        f"Summary: PASS={s['PASS']} CRITICAL={s['CRITICAL']} HIGH={s['HIGH']} MEDIUM={s['MEDIUM']} LOW={s['LOW']} INFO={s['INFO']}",
        "",
    ]
    for c in report["checks"]:
        lat = f" ({c['latency_ms']}ms)" if c["latency_ms"] is not None else ""
        lines.append(f"[{c['status']}] {c['id']}: {c['title']}{lat}")
        lines.append(f"  Detail : {c['detail']}")
        if c["url"]:
            lines.append(f"  URL    : {c['url']}")
    return "\n".join(lines)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run post-deploy live smoke checks on health probes, /ingest proxy, /monitoring tunnel, and .js.map leaks."
    )
    parser.add_argument("url", help="Base URL of your deployed app (e.g. https://app.example.com)")
    parser.add_argument(
        "--health-path",
        action="append",
        dest="health_paths",
        help="Health check path(s) to probe (default: /api/health, /healthz)",
    )
    parser.add_argument("--ingest-path", default="/ingest", help="PostHog proxy prefix (default: /ingest)")
    parser.add_argument("--skip-ingest", action="store_true", help="Skip PostHog /ingest proxy check")
    parser.add_argument("--monitoring-path", default="/monitoring", help="Sentry tunnel path (default: /monitoring)")
    parser.add_argument("--skip-monitoring", action="store_true", help="Skip Sentry tunnel check")
    parser.add_argument("--max-scripts", type=int, default=5, help="Max same-origin JS bundles to probe for .map leaks")
    parser.add_argument("--timeout", type=float, default=8.0, help="HTTP request timeout in seconds")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Output JSON report")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if any HIGH or CRITICAL finding occurs")
    args = parser.parse_args(argv)

    health_paths = args.health_paths or ["/api/health", "/healthz"]
    try:
        report = verify_live(
            base_url=args.url,
            health_paths=health_paths,
            ingest_path=None if args.skip_ingest else args.ingest_path,
            monitoring_path=None if args.skip_monitoring else args.monitoring_path,
            max_scripts=args.max_scripts,
            timeout=args.timeout,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render_text(report))

    if args.strict:
        if any(SEVERITY_RANK[c["status"]] >= SEVERITY_RANK["HIGH"] for c in report["checks"]):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
