"""Structured telemetry & silent-failure guard for Python + uv scrapers/jobs.

Features:
- Structured JSON logs via stdlib logging (swap in `structlog` seamlessly)
- Mandatory end-of-run `job_run_summary` persisted to local JSONL history
- Silent volume-drop anomaly detector (catches DOM changes / anti-bot gates
  that exit 0 with 0 items)
- Optional Sentry exception + Sentry Crons heartbeat check-in with flush on exit
"""

from __future__ import annotations

import json
import os
import statistics
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

try:
    import sentry_sdk  # type: ignore
except ImportError:  # pragma: no cover
    sentry_sdk = None


@dataclass
class RunMetrics:
    job: str
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = "ok"
    duration_s: float = 0.0
    pages_visited: int = 0
    items_fetched: int = 0
    items_new: int = 0
    empty_page_count: int = 0
    auth_expired: bool = False
    challenge_hit: bool = False
    error_count: int = 0
    anomaly_reason: Optional[str] = None


def init_job_sentry(env: str | None = None) -> None:
    app_env = env or os.getenv("APP_ENV", "development")
    dsn = os.getenv("SENTRY_DSN")
    if not sentry_sdk or not dsn or app_env != "production":
        return
    sentry_sdk.init(
        dsn=dsn,
        environment=app_env,
        traces_sample_rate=0.1 if app_env == "production" else 0.0,
        send_default_pii=False,
    )


def log_json(level: str, event: str, **fields: object) -> None:
    payload = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "level": level, "event": event, **fields}
    print(json.dumps(payload, ensure_ascii=False))


class JobRunTracker:
    """Context manager emitting run summaries and detecting silent volume drops."""

    def __init__(self, job_name: str, history_file: Path, min_drop_ratio: float = 0.5) -> None:
        self.metrics = RunMetrics(job=job_name)
        self.history_file = history_file
        self.min_drop_ratio = min_drop_ratio
        self._started = 0.0

    def __enter__(self) -> RunMetrics:
        self._started = time.monotonic()
        log_json("info", "job_started", job=self.metrics.job, run_id=self.metrics.run_id)
        return self.metrics

    def _trailing_median_items(self) -> Optional[float]:
        if not self.history_file.is_file():
            return None
        counts: list[int] = []
        for line in self.history_file.read_text(encoding="utf-8", errors="ignore").splitlines()[-20:]:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("job") == self.metrics.job and row.get("status") == "ok" and not row.get("anomaly_reason"):
                counts.append(int(row.get("items_fetched", 0)))
        recent = counts[-7:]
        return statistics.median(recent) if len(recent) >= 3 else None

    def _detect_anomaly(self) -> Optional[str]:
        if self.metrics.auth_expired:
            return "auth_expired: login session requires manual refresh"
        if self.metrics.challenge_hit:
            return "challenge_hit: anti-bot gate encountered; backed off"
        if self.metrics.status == "ok" and self.metrics.items_fetched == 0:
            return "zero_items_fetched: possible DOM selector drift or empty response"
        baseline = self._trailing_median_items()
        if baseline and baseline >= 10 and self.metrics.items_fetched < baseline * self.min_drop_ratio:
            return f"volume_drop: fetched {self.metrics.items_fetched} vs trailing median {baseline:.1f}"
        return None

    def __exit__(self, exc_type, exc_val, _exc_tb) -> None:
        self.metrics.duration_s = round(time.monotonic() - self._started, 2)
        if exc_type is not None:
            self.metrics.status = "failed"
            self.metrics.error_count += 1
            if sentry_sdk:
                sentry_sdk.capture_exception(exc_val)
        else:
            anomaly = self._detect_anomaly()
            if anomaly:
                self.metrics.anomaly_reason = anomaly
                self.metrics.status = "degraded"
                if sentry_sdk:
                    sentry_sdk.capture_message(f"[{self.metrics.job}] {anomaly}", level="warning")

        record = asdict(self.metrics)
        log_json("error" if self.metrics.status == "failed" else "info", "job_run_summary", **record)

        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        with self.history_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

        if sentry_sdk:
            sentry_sdk.flush(timeout=5.0)
