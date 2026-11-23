# Security Policy

`vibe-observability` audits source code, probes live deployments, and pulls
read-only telemetry summaries. Security and privacy boundaries are first-class
invariants of this project:

## Security Guarantees of Bundled CLI Tools

1. **Zero external runtime dependencies**: All CLI scripts (`audit_observability.py`,
   `verify_live.py`, `pull_signals.py`, and `vibe-obs`) run on Python 3.9+
   standard library only.
2. **Local-only static auditing**: `audit_observability.py` inspects local
   files only and makes **zero** network requests.
3. **Strictly read-only signal pulling**: `pull_signals.py` calls read-only
   endpoints (`GET` for Sentry/Clarity/Prometheus, `SELECT` HogQL for PostHog),
   never persists credentials to disk, and never prints API tokens to stdout or
   stderr.
4. **No secret exfiltration**: Examples and references enforce
   `sendDefaultPii: false`, input masking (`maskAllInputs: true`), header
   redaction (`Authorization`, `Cookie`), and SSRF-safe Sentry tunnel DSN
   allowlisting.

## Reporting a Vulnerability

If you discover a security issue (for example, token leakage in CLI output,
command injection in `install.sh`, or an SSRF flaw in a starter proxy example):

- Please **do not** open a public issue with exploit details.
- Report it privately via GitHub Security Advisories:
  https://github.com/realchendahuang/vibe-observability/security/advisories/new
- Include reproduction steps and affected file(s). Reports are acknowledged
  within 72 hours.
