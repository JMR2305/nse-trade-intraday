"""
alert_queue.py — Priority 4 (#41): durable email alert delivery queue.

Email alerts are no longer fire-and-forget: every critical alert email is
first written to the shared alert_deliveries Postgres table (the same table
the Node side uses for push), then delivered by process_email_queue() with
bounded exponential backoff. A briefly-down email provider no longer loses
an alert.

Lifecycle: QUEUED → SENDING → DELIVERED | RETRY_SCHEDULED | FAILED | EXPIRED
- Idempotency keys prevent duplicate delivery (unique index, ON CONFLICT
  DO NOTHING).
- Transient failures (network, 5xx, timeouts) retry with backoff
  [1m, 5m, 15m, 1h, 3h, 6h]; exhaustion → FAILED + dead_letter.
- Permanent failures (invalid address, not configured) fail immediately.
- Critical alerts (severity CRITICAL) never auto-expire and get more
  attempts; non-critical rows expire after 24 h.
- provider response / attempt count / last error / timestamps recorded.
- No API secrets in payloads or logs. Recipient addresses are stored
  masked (u***@domain) in `destination`; the actual address is resolved
  from settings at send time.

Paper trading / research only — alerts are advisory, never place orders.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

BACKOFF_SECONDS = [60, 300, 900, 3600, 10800, 21600]
DEFAULT_MAX_ATTEMPTS = 6
CRITICAL_MAX_ATTEMPTS = 10
DEFAULT_TTL_HOURS = 24

_ENSURE_SQL = """
CREATE TABLE IF NOT EXISTS alert_deliveries (
  id bigserial PRIMARY KEY,
  idempotency_key text NOT NULL UNIQUE,
  channel text NOT NULL,
  kind text NOT NULL,
  severity text NOT NULL DEFAULT 'INFO',
  title text NOT NULL,
  body text NOT NULL DEFAULT '',
  destination text NOT NULL,
  payload jsonb,
  status text NOT NULL DEFAULT 'QUEUED',
  attempts integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 6,
  critical boolean NOT NULL DEFAULT false,
  dead_letter boolean NOT NULL DEFAULT false,
  next_attempt_at timestamptz DEFAULT now(),
  expires_at timestamptz,
  last_error text,
  provider_id text,
  provider_response jsonb,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now(),
  delivered_at timestamptz
)
"""


def _connect():
    import phase20_store
    conn = phase20_store._connect()
    with conn.cursor() as cur:
        cur.execute(_ENSURE_SQL)
    conn.commit()
    return conn


def _db_available() -> bool:
    try:
        import phase20_store
        return phase20_store.db_available()
    except Exception:
        return False


def mask_email(address: str) -> str:
    """u***@domain — never store or log the full recipient address."""
    addr = str(address or "").strip()
    if "@" not in addr:
        return "***"
    local, domain = addr.split("@", 1)
    return (local[:1] + "***@" + domain) if local else "***@" + domain


def _now() -> datetime:
    return datetime.now(timezone.utc)


def backoff_seconds(attempts: int) -> int:
    idx = min(max(attempts - 1, 0), len(BACKOFF_SECONDS) - 1)
    return BACKOFF_SECONDS[idx]


# ── Enqueue ──────────────────────────────────────────────────────────────────

def enqueue_email_alert(kind: str, title: str, body: str = "",
                        severity: str = "INFO") -> Dict[str, Any]:
    """
    Queue a critical alert email for durable delivery. Gating (feature
    enabled, address configured, alert kind is emailable) happens here so
    the queue only ever contains genuinely deliverable work.

    Never raises. Returns {queued: bool, reason?: str}.
    """
    try:
        import email_alerts
        import phase20_store
        if kind not in email_alerts.EMAIL_KINDS:
            return {"queued": False, "reason": "KIND_NOT_EMAILED"}
        settings = phase20_store.get_settings()
        if not settings.get("email_alerts_enabled"):
            return {"queued": False, "reason": "DISABLED"}
        to = str(settings.get("email_alert_address") or "").strip()
        if not email_alerts.valid_address(to):
            return {"queued": False, "reason": "NO_ADDRESS"}
        if not _db_available():
            # No durable store — deliver directly (legacy path) rather than
            # dropping the alert.
            result = email_alerts.maybe_send_alert_email(kind, title, body,
                                                         severity, settings)
            return {"queued": False, "reason": "NO_DB_DIRECT_SEND",
                    "direct_result": {k: result.get(k) for k in ("sent", "reason")}}

        critical = str(severity).upper() == "CRITICAL"
        digest = hashlib.sha1(
            f"{kind}|{title[:300]}|{body[:1000]}".encode()).hexdigest()[:16]
        idem = f"email:{kind}:{digest}"
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO alert_deliveries
                      (idempotency_key, channel, kind, severity, title, body,
                       destination, payload, critical, max_attempts, expires_at)
                    VALUES (%s, 'email', %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (idempotency_key) DO NOTHING
                    RETURNING id
                    """,
                    (idem, kind, severity, title[:300], body[:2000],
                     mask_email(to),
                     json.dumps({"kind": kind, "severity": severity}),
                     critical,
                     CRITICAL_MAX_ATTEMPTS if critical else DEFAULT_MAX_ATTEMPTS,
                     None if critical else _now() + timedelta(hours=DEFAULT_TTL_HOURS)),
                )
                row = cur.fetchone()
            conn.commit()
            return {"queued": row is not None,
                    "reason": None if row else "DUPLICATE",
                    "idempotency_key": idem}
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 — must never break the caller
        logger.warning("enqueue_email_alert failed: %s", str(exc)[:200])
        return {"queued": False, "reason": f"ERROR: {str(exc)[:200]}"}


# ── Processing ───────────────────────────────────────────────────────────────

def _attempt_email(row: Dict[str, Any]) -> Dict[str, Any]:
    """One delivery attempt. Returns {ok, permanent?, provider_response?, error?}."""
    import email_alerts
    import phase20_store
    settings = phase20_store.get_settings()
    if not settings.get("email_alerts_enabled"):
        return {"ok": False, "permanent": True, "error": "Email alerts disabled"}
    to = str(settings.get("email_alert_address") or "").strip()
    if not email_alerts.valid_address(to):
        return {"ok": False, "permanent": True, "error": "No valid alert address"}
    parts = email_alerts._compose(row["kind"], row["title"], row["body"],
                                  row["severity"])
    started = _now()
    try:
        result = email_alerts._deliver(to, parts["subject"], parts["text"],
                                       parts.get("html"))
    except Exception as exc:  # transient (network/provider)
        return {"ok": False, "error": str(exc)[:300]}
    latency_ms = int((_now() - started).total_seconds() * 1000)
    response = {k: v for k, v in (result or {}).items()
                if k in ("sent", "provider", "id", "message_id", "reason", "status")}
    response["latency_ms"] = latency_ms
    if result.get("sent"):
        return {"ok": True,
                "provider_id": str(result.get("message_id") or result.get("id") or ""),
                "provider_response": response}
    reason = str(result.get("reason") or "UNKNOWN")
    permanent = reason in ("NOT_CONFIGURED",)
    return {"ok": False, "permanent": permanent,
            "provider_response": response, "error": reason}


def process_email_queue(limit: int = 25) -> Dict[str, Any]:
    """Deliver due queued email alerts. Never raises."""
    counters = {"delivered": 0, "retried": 0, "failed": 0, "expired": 0}
    if not _db_available():
        return {**counters, "skipped": "DB_UNAVAILABLE"}
    try:
        conn = _connect()
    except Exception as exc:
        return {**counters, "skipped": f"CONNECT: {str(exc)[:120]}"}
    try:
        with conn.cursor() as cur:
            # Expire overdue non-critical rows (critical never auto-expires).
            cur.execute(
                """
                UPDATE alert_deliveries
                SET status = 'EXPIRED', updated_at = now()
                WHERE channel = 'email' AND status IN ('QUEUED','RETRY_SCHEDULED')
                  AND critical = false AND expires_at IS NOT NULL
                  AND expires_at <= now()
                RETURNING id
                """)
            counters["expired"] = len(cur.fetchall())
            cur.execute(
                """
                SELECT id, kind, severity, title, body, attempts, max_attempts,
                       critical
                FROM alert_deliveries
                WHERE channel = 'email' AND status IN ('QUEUED','RETRY_SCHEDULED')
                  AND (next_attempt_at IS NULL OR next_attempt_at <= now())
                ORDER BY created_at ASC
                LIMIT %s
                """, (limit,))
            due = [{"id": r[0], "kind": r[1], "severity": r[2], "title": r[3],
                    "body": r[4], "attempts": r[5], "max_attempts": r[6],
                    "critical": r[7]} for r in cur.fetchall()]
        conn.commit()

        for row in due:
            with conn.cursor() as cur:
                # Claim (guards double-send across processes).
                cur.execute(
                    """
                    UPDATE alert_deliveries SET status='SENDING', updated_at=now()
                    WHERE id=%s AND status IN ('QUEUED','RETRY_SCHEDULED')
                    RETURNING id
                    """, (row["id"],))
                claimed = cur.fetchone()
            conn.commit()
            if not claimed:
                continue

            attempts = row["attempts"] + 1
            outcome = _attempt_email(row)
            resp = json.dumps(outcome.get("provider_response") or {}, default=str)
            err = None if outcome.get("ok") else str(outcome.get("error") or "unknown")[:500]

            with conn.cursor() as cur:
                if outcome.get("ok"):
                    cur.execute(
                        """
                        UPDATE alert_deliveries
                        SET status='DELIVERED', attempts=%s, last_error=NULL,
                            provider_id=%s, provider_response=%s,
                            delivered_at=now(), updated_at=now()
                        WHERE id=%s
                        """, (attempts, outcome.get("provider_id"), resp, row["id"]))
                    counters["delivered"] += 1
                elif outcome.get("permanent"):
                    cur.execute(
                        """
                        UPDATE alert_deliveries
                        SET status='FAILED', attempts=%s, last_error=%s,
                            provider_response=%s, updated_at=now()
                        WHERE id=%s
                        """, (attempts, err, resp, row["id"]))
                    counters["failed"] += 1
                elif attempts >= row["max_attempts"]:
                    cur.execute(
                        """
                        UPDATE alert_deliveries
                        SET status='FAILED', dead_letter=true, attempts=%s,
                            last_error=%s, provider_response=%s, updated_at=now()
                        WHERE id=%s
                        """, (attempts, err, resp, row["id"]))
                    counters["failed"] += 1
                    logger.warning("email alert %s dead-lettered after %s attempts",
                                   row["id"], attempts)
                else:
                    delay = backoff_seconds(attempts)
                    cur.execute(
                        """
                        UPDATE alert_deliveries
                        SET status='RETRY_SCHEDULED', attempts=%s, last_error=%s,
                            provider_response=%s,
                            next_attempt_at=now() + %s * interval '1 second',
                            updated_at=now()
                        WHERE id=%s
                        """, (attempts, err, resp, delay, row["id"]))
                    counters["retried"] += 1
            conn.commit()
        return counters
    except Exception as exc:  # noqa: BLE001
        logger.warning("process_email_queue failed: %s", str(exc)[:200])
        return {**counters, "error": str(exc)[:200]}
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ── Read-only views (used by dashboard / P5, P8) ─────────────────────────────

def list_deliveries(channel: Optional[str] = None, status: Optional[str] = None,
                    limit: int = 100) -> Dict[str, Any]:
    """Recent delivery records (masked destinations; no secrets)."""
    if not _db_available():
        return {"deliveries": [], "available": False}
    try:
        conn = _connect()
    except Exception:
        return {"deliveries": [], "available": False}
    try:
        q = """
            SELECT id, idempotency_key, channel, kind, severity, title,
                   destination, status, attempts, max_attempts, critical,
                   dead_letter, next_attempt_at, expires_at, last_error,
                   provider_id, provider_response, created_at, updated_at,
                   delivered_at
            FROM alert_deliveries
            WHERE (%s::text IS NULL OR channel = %s)
              AND (%s::text IS NULL OR status = %s)
            ORDER BY created_at DESC
            LIMIT %s
        """
        with conn.cursor() as cur:
            cur.execute(q, (channel, channel, status, status, limit))
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for r in rows:
            for k in ("next_attempt_at", "expires_at", "created_at",
                      "updated_at", "delivered_at"):
                if r.get(k) is not None:
                    r[k] = r[k].isoformat()
            # Push tokens are device addresses, not secrets, but keep API
            # output truncated anyway.
            if r["channel"] == "push" and len(str(r["destination"])) > 24:
                r["destination"] = str(r["destination"])[:24] + "…"
        return {"deliveries": rows, "available": True}
    finally:
        conn.close()


def queue_stats() -> Dict[str, Any]:
    """Aggregate counts by channel/status + last delivery/failure times."""
    if not _db_available():
        return {"available": False}
    try:
        conn = _connect()
    except Exception:
        return {"available": False}
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT channel, status, count(*)
                FROM alert_deliveries GROUP BY channel, status
                """)
            counts: Dict[str, Dict[str, int]] = {}
            for ch, st, n in cur.fetchall():
                counts.setdefault(ch, {})[st] = n
            cur.execute(
                """
                SELECT channel, max(delivered_at) FROM alert_deliveries
                WHERE delivered_at IS NOT NULL GROUP BY channel
                """)
            last_delivered = {ch: ts.isoformat() for ch, ts in cur.fetchall() if ts}
            cur.execute(
                """
                SELECT channel, max(updated_at) FROM alert_deliveries
                WHERE status = 'FAILED' GROUP BY channel
                """)
            last_failed = {ch: ts.isoformat() for ch, ts in cur.fetchall() if ts}
            cur.execute(
                "SELECT count(*) FROM alert_deliveries WHERE dead_letter = true")
            dead = cur.fetchone()[0]
        return {"available": True, "counts": counts,
                "last_delivered": last_delivered, "last_failed": last_failed,
                "dead_letter_count": dead}
    finally:
        conn.close()
