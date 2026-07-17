"""
email_alerts.py — opt-in email delivery for critical trading notifications.

When a PERFORMANCE_ALERT or CIRCUIT_BREAKER_TRIPPED notification is created,
this module (best-effort) also emails the configured address so the user is
reached even when they are not looking at the dashboard.

Design rules:
  * OPT-IN: disabled unless email_alerts_enabled is True AND an address is set
    (both configured in Phase 20 settings).
  * NEVER RAISES upstream: any failure is logged to stderr and returned as a
    status dict — a broken email provider must never break the scheduler tick
    or notification storage.
  * Transport is pluggable, resolved at send time from the environment:
      1. RESEND_API_KEY            → Resend HTTP API (https://resend.com)
      2. SMTP_HOST (+SMTP_USER...) → standard SMTP (STARTTLS on port 587)
      3. neither                   → NOT_CONFIGURED (logged, no email sent)

PAPER TRADING / RESEARCH ONLY — emails are advisory notifications only.
"""

from __future__ import annotations

import json
import os
import re
import smtplib
import sys
import urllib.request
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape as _esc
from typing import Any, Dict, Optional

# Notification kinds that trigger an email (critical, user-must-know alerts).
EMAIL_KINDS = ("PERFORMANCE_ALERT", "CIRCUIT_BREAKER_TRIPPED")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_RESEND_URL = "https://api.resend.com/emails"
_DEFAULT_FROM = "NSE Trading Alerts <onboarding@resend.dev>"
_TIMEOUT_S = 10


def _log(msg: str) -> None:
    print(f"[email_alerts] {msg}", file=sys.stderr)


def valid_address(address: Any) -> bool:
    return isinstance(address, str) and bool(_EMAIL_RE.match(address.strip()))


def provider_status() -> Dict[str, Any]:
    """Which transport would be used right now (no secrets exposed)."""
    if os.environ.get("RESEND_API_KEY"):
        return {"configured": True, "provider": "RESEND"}
    if os.environ.get("SMTP_HOST"):
        return {"configured": True, "provider": "SMTP"}
    return {
        "configured": False,
        "provider": None,
        "hint": ("Add a RESEND_API_KEY secret (recommended) or SMTP_HOST / "
                 "SMTP_PORT / SMTP_USER / SMTP_PASS / SMTP_FROM secrets to "
                 "enable email delivery."),
    }


def _from_address() -> str:
    return (os.environ.get("ALERT_EMAIL_FROM")
            or os.environ.get("SMTP_FROM")
            or _DEFAULT_FROM)


def _send_via_resend(to: str, subject: str, text: str,
                     html: Optional[str] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "from": _from_address(),
        "to": [to],
        "subject": subject,
        "text": text,
    }
    if html:
        body["html"] = html
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        _RESEND_URL, data=payload, method="POST",
        headers={
            "Authorization": f"Bearer {os.environ['RESEND_API_KEY']}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
        body = resp.read().decode()[:500]
        if resp.status >= 300:
            raise RuntimeError(f"Resend HTTP {resp.status}: {body}")
    return {"sent": True, "provider": "RESEND"}


def _send_via_smtp(to: str, subject: str, text: str,
                   html: Optional[str] = None) -> Dict[str, Any]:
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587") or 587)
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    if html:
        msg: Any = MIMEMultipart("alternative")
        msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))
    else:
        msg = MIMEText(text, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = _from_address()
    msg["To"] = to
    with smtplib.SMTP(host, port, timeout=_TIMEOUT_S) as server:
        server.ehlo()
        try:
            server.starttls()
            server.ehlo()
        except smtplib.SMTPNotSupportedError:
            pass
        if user and password:
            server.login(user, password)
        server.sendmail(msg["From"], [to], msg.as_string())
    return {"sent": True, "provider": "SMTP"}


def _deliver(to: str, subject: str, text: str,
             html: Optional[str] = None) -> Dict[str, Any]:
    """Send via the first configured transport (multipart when html given).

    May raise."""
    if os.environ.get("RESEND_API_KEY"):
        return _send_via_resend(to, subject, text, html)
    if os.environ.get("SMTP_HOST"):
        return _send_via_smtp(to, subject, text, html)
    return {"sent": False, "reason": "NOT_CONFIGURED", **provider_status()}


def _compose(kind: str, title: str, body: str, severity: str) -> Dict[str, str]:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    subject = f"[NSE Trading {severity}] {title}"[:180]
    text = (
        f"{title}\n\n{body}\n\n"
        f"Alert type: {kind}\nSeverity: {severity}\nTime: {ts}\n\n"
        "This is an advisory alert from your NSE paper-trading dashboard. "
        "Paper trading / research only — no real orders are ever placed.\n"
        "Open the dashboard Notifications page for full details."
    )
    html = _render_alert_html(kind=kind, title=title, body=body,
                              severity=severity, ts=ts)
    return {"subject": subject, "text": text, "html": html}


def maybe_send_alert_email(kind: str, title: str, body: str = "",
                           severity: str = "INFO",
                           settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Send an email for a critical notification if the feature is enabled and
    configured. Never raises; failures are logged and reported in the result.
    """
    try:
        if kind not in EMAIL_KINDS:
            return {"sent": False, "reason": "KIND_NOT_EMAILED"}
        if settings is None:
            import phase20_store as store
            settings = store.get_settings()
        if not settings.get("email_alerts_enabled"):
            return {"sent": False, "reason": "DISABLED"}
        to = str(settings.get("email_alert_address") or "").strip()
        if not valid_address(to):
            _log(f"skipped {kind}: no valid alert address configured")
            return {"sent": False, "reason": "NO_ADDRESS"}
        parts = _compose(kind, title, body, severity)
        result = _deliver(to, parts["subject"], parts["text"],
                          parts.get("html"))
        if result.get("sent"):
            _log(f"sent {kind} alert email via {result.get('provider')}")
        else:
            _log(f"skipped {kind}: {result.get('reason')}")
        return result
    except Exception as exc:  # noqa: BLE001 — must never break the caller
        _log(f"delivery failed for {kind}: {str(exc)[:300]}")
        return {"sent": False, "reason": "ERROR", "error": str(exc)[:300]}


def _fmt_inr(value: Any) -> str:
    try:
        num = float(value or 0)
    except (TypeError, ValueError):
        num = 0.0
    sign = "-" if num < 0 else ""
    return f"{sign}Rs {abs(num):,.2f}"


def _compose_daily_summary(report: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Compose the daily performance summary email body.

    Uses the Phase 22 daily report when available; win rate and open
    positions are derived from the paper-trade ledger / portfolio directly.
    Any sub-source failure degrades to 'unavailable' — never raises.
    """
    report = report or {}
    day = str(report.get("report_date") or
              datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    exits_today = []
    try:
        from phase20_executor import get_ledger
        ledger = get_ledger(500)
        exits_today = [t for t in ledger if t.get("status") == "CLOSED"
                       and str(t.get("exit_ts") or "").startswith(day)]
    except Exception as exc:  # noqa: BLE001
        _log(f"daily summary: ledger unavailable: {str(exc)[:200]}")

    wins = sum(1 for t in exits_today
               if float(t.get("realized_pnl") or 0) > 0)
    win_rate = (f"{wins}/{len(exits_today)} "
                f"({100.0 * wins / len(exits_today):.0f}%)"
                if exits_today else "n/a (no closed trades today)")

    positions_lines = []
    positions: list = []
    unrealized_total = None
    try:
        from paper_trader import get_portfolio
        pf = get_portfolio()
        positions = pf.get("positions", []) or []
        unrealized_total = round(sum(float(p.get("pnl") or 0)
                                     for p in positions), 2)
        for p in positions[:20]:
            positions_lines.append(
                f"  - {p.get('symbol', '?')}: qty {p.get('quantity', '?')}, "
                f"unrealized P&L {_fmt_inr(p.get('pnl'))}")
        if len(positions) > 20:
            positions_lines.append(f"  ... and {len(positions) - 20} more")
        if not positions:
            positions_lines.append("  (none)")
    except Exception as exc:  # noqa: BLE001
        _log(f"daily summary: portfolio unavailable: {str(exc)[:200]}")
        positions_lines.append("  (unavailable)")

    realized = report.get("realized_pnl")
    unrealized = report.get("unrealized_pnl", unrealized_total)
    positions_rows = positions[:20]
    positions_overflow = max(0, len(positions) - 20)
    lines = [
        f"Daily performance summary — {day}",
        "",
        "Trades",
        f"  Paper entries opened: {report.get('paper_entries_opened', 'n/a')}",
        f"  Exits completed:      {report.get('exits_completed', len(exits_today))}",
        f"  Entries blocked:      {report.get('entries_blocked', 'n/a')}",
        "",
        "Performance",
        f"  Realized P&L (today): {_fmt_inr(realized) if realized is not None else 'n/a'}",
        f"  Unrealized P&L:       {_fmt_inr(unrealized) if unrealized is not None else 'n/a'}",
        f"  Win rate (today):     {win_rate}",
        "",
        "Open positions",
        *positions_lines,
        "",
        f"Scheduled scans completed: {report.get('scheduled_scans_completed', 'n/a')}",
        f"Failed scans: {report.get('failed_scans', 'n/a')}",
        "",
        "PAPER TRADING / RESEARCH ONLY — no real orders are ever placed.",
        "Open the dashboard for the full daily report and exports.",
    ]
    subject = f"[NSE Trading] Daily summary — {day}"[:180]
    html = _render_daily_summary_html(
        day=day,
        entries_opened=report.get("paper_entries_opened", "n/a"),
        exits_completed=report.get("exits_completed", len(exits_today)),
        entries_blocked=report.get("entries_blocked", "n/a"),
        realized=realized,
        unrealized=unrealized,
        win_rate=win_rate,
        positions=positions_rows,
        positions_overflow=positions_overflow,
        positions_unavailable=(positions_lines == ["  (unavailable)"]),
        scans_completed=report.get("scheduled_scans_completed", "n/a"),
        failed_scans=report.get("failed_scans", "n/a"),
    )
    return {"subject": subject, "text": "\n".join(lines), "html": html}


_GREEN = "#15803d"
_RED = "#b91c1c"
_MUTED = "#64748b"


def _pnl_html(value: Any) -> str:
    """Colored INR amount span (green >= 0, red < 0)."""
    try:
        num = float(value or 0)
    except (TypeError, ValueError):
        num = 0.0
    color = _RED if num < 0 else _GREEN
    return (f'<span style="color:{color};font-weight:600;">'
            f"{_esc(_fmt_inr(value))}</span>")


_AMBER = "#b45309"

_SEVERITY_COLORS = {
    "CRITICAL": _RED,
    "ERROR": _RED,
    "WARN": _AMBER,
    "WARNING": _AMBER,
    "INFO": _GREEN,
}


def _render_alert_html(*, kind: str, title: str, body: str,
                       severity: str, ts: str) -> str:
    """Render a critical alert as email-client-safe inline-styled HTML,
    matching the daily-summary layout (dark header, tables, advisory
    footer)."""
    cell = 'padding:6px 12px;border-bottom:1px solid #e2e8f0;font-size:13px;'
    section = ('margin:20px 0 8px;font-size:14px;font-weight:700;'
               'color:#0f172a;')
    sev = severity.upper()
    sev_color = _SEVERITY_COLORS.get(sev, _MUTED)
    badge = (f'<span style="display:inline-block;padding:2px 10px;'
             f'border-radius:9999px;background:{sev_color};color:#ffffff;'
             f'font-size:11px;font-weight:700;letter-spacing:0.04em;">'
             f'{_esc(sev)}</span>')

    def row(label: str, value_html: str) -> str:
        return (f'<tr><td style="{cell}color:{_MUTED};">{_esc(label)}</td>'
                f'<td style="{cell}text-align:right;">{value_html}</td></tr>')

    body_html = (
        f'<p style="font-size:13px;line-height:1.6;color:#0f172a;'
        f'margin:8px 0 0;white-space:pre-line;">{_esc(body)}</p>'
        if body else "")

    return f"""\
<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f1f5f9;">
  <div style="max-width:560px;margin:0 auto;padding:24px 16px;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#0f172a;">
    <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;">
      <div style="background:#0f172a;padding:16px 20px;">
        <div style="color:#ffffff;font-size:16px;font-weight:700;">{_esc(title)}</div>
        <div style="color:#94a3b8;font-size:12px;margin-top:2px;">{_esc(ts)} &middot; NSE Paper Trading</div>
      </div>
      <div style="padding:4px 20px 20px;">
        <div style="{section}">Alert</div>
        {body_html}
        <div style="{section}">Details</div>
        <table style="border-collapse:collapse;width:100%;" cellpadding="0" cellspacing="0">
          {row("Alert type", _esc(kind))}
          {row("Severity", badge)}
          {row("Time", _esc(ts))}
        </table>
        <div style="margin-top:20px;padding:10px 12px;background:#fffbeb;border:1px solid #fde68a;border-radius:6px;color:#92400e;font-size:12px;">
          PAPER TRADING / RESEARCH ONLY &mdash; no real orders are ever placed.
        </div>
        <p style="color:{_MUTED};font-size:12px;margin:14px 0 0;">
          This is an advisory alert from your NSE paper-trading dashboard.
          Open the dashboard Notifications page for full details.
        </p>
      </div>
    </div>
  </div>
</body>
</html>"""


def _render_daily_summary_html(*, day: str, entries_opened: Any,
                               exits_completed: Any, entries_blocked: Any,
                               realized: Any, unrealized: Any, win_rate: str,
                               positions: list, positions_overflow: int,
                               positions_unavailable: bool,
                               scans_completed: Any,
                               failed_scans: Any) -> str:
    """Render the daily summary as email-client-safe inline-styled HTML."""
    cell = 'padding:6px 12px;border-bottom:1px solid #e2e8f0;font-size:13px;'
    th = (f'{cell}text-align:left;color:{_MUTED};font-weight:600;'
          'text-transform:uppercase;font-size:11px;letter-spacing:0.04em;')
    section = ('margin:20px 0 8px;font-size:14px;font-weight:700;'
               'color:#0f172a;')

    def row(label: str, value_html: str) -> str:
        return (f'<tr><td style="{cell}color:{_MUTED};">{_esc(label)}</td>'
                f'<td style="{cell}text-align:right;">{value_html}</td></tr>')

    if positions_unavailable:
        pos_html = f'<p style="color:{_MUTED};font-size:13px;">(unavailable)</p>'
    elif not positions:
        pos_html = f'<p style="color:{_MUTED};font-size:13px;">(none)</p>'
    else:
        pos_rows = "".join(
            f'<tr><td style="{cell}font-weight:600;">'
            f'{_esc(str(p.get("symbol", "?")))}</td>'
            f'<td style="{cell}text-align:right;">'
            f'{_esc(str(p.get("quantity", "?")))}</td>'
            f'<td style="{cell}text-align:right;">{_pnl_html(p.get("pnl"))}'
            "</td></tr>"
            for p in positions)
        overflow = (
            f'<tr><td colspan="3" style="{cell}color:{_MUTED};">'
            f"... and {positions_overflow} more</td></tr>"
            if positions_overflow else "")
        pos_html = (
            '<table style="border-collapse:collapse;width:100%;" '
            'cellpadding="0" cellspacing="0">'
            f'<tr><th style="{th}">Symbol</th>'
            f'<th style="{th}text-align:right;">Qty</th>'
            f'<th style="{th}text-align:right;">Unrealized P&amp;L</th></tr>'
            f"{pos_rows}{overflow}</table>")

    def plain(value: Any) -> str:
        return _esc(str(value))

    realized_html = _pnl_html(realized) if realized is not None else plain("n/a")
    unrealized_html = (_pnl_html(unrealized) if unrealized is not None
                       else plain("n/a"))

    return f"""\
<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f1f5f9;">
  <div style="max-width:560px;margin:0 auto;padding:24px 16px;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#0f172a;">
    <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;">
      <div style="background:#0f172a;padding:16px 20px;">
        <div style="color:#ffffff;font-size:16px;font-weight:700;">Daily performance summary</div>
        <div style="color:#94a3b8;font-size:12px;margin-top:2px;">{_esc(day)} &middot; NSE Paper Trading</div>
      </div>
      <div style="padding:4px 20px 20px;">
        <div style="{section}">Trades</div>
        <table style="border-collapse:collapse;width:100%;" cellpadding="0" cellspacing="0">
          {row("Paper entries opened", plain(entries_opened))}
          {row("Exits completed", plain(exits_completed))}
          {row("Entries blocked", plain(entries_blocked))}
        </table>
        <div style="{section}">Performance</div>
        <table style="border-collapse:collapse;width:100%;" cellpadding="0" cellspacing="0">
          {row("Realized P&L (today)", realized_html)}
          {row("Unrealized P&L", unrealized_html)}
          {row("Win rate (today)", plain(win_rate))}
        </table>
        <div style="{section}">Open positions</div>
        {pos_html}
        <div style="{section}">Scans</div>
        <table style="border-collapse:collapse;width:100%;" cellpadding="0" cellspacing="0">
          {row("Scheduled scans completed", plain(scans_completed))}
          {row("Failed scans", plain(failed_scans))}
        </table>
        <div style="margin-top:20px;padding:10px 12px;background:#fffbeb;border:1px solid #fde68a;border-radius:6px;color:#92400e;font-size:12px;">
          PAPER TRADING / RESEARCH ONLY &mdash; no real orders are ever placed.
        </div>
        <p style="color:{_MUTED};font-size:12px;margin:14px 0 0;">
          Open the dashboard for the full daily report and exports.
        </p>
      </div>
    </div>
  </div>
</body>
</html>"""


def maybe_send_daily_summary_email(report: Optional[Dict[str, Any]] = None,
                                   settings: Optional[Dict[str, Any]] = None
                                   ) -> Dict[str, Any]:
    """
    Send the market-close daily performance summary email if the feature is
    enabled and configured. Opt-in via daily_summary_email_enabled and the
    shared email_alert_address. Never raises.
    """
    try:
        if settings is None:
            import phase20_store as store
            settings = store.get_settings()
        if not settings.get("daily_summary_email_enabled"):
            return {"sent": False, "reason": "DISABLED"}
        to = str(settings.get("email_alert_address") or "").strip()
        if not valid_address(to):
            _log("skipped daily summary: no valid alert address configured")
            return {"sent": False, "reason": "NO_ADDRESS"}
        parts = _compose_daily_summary(report)
        result = _deliver(to, parts["subject"], parts["text"],
                          parts.get("html"))
        if result.get("sent"):
            _log(f"sent daily summary email via {result.get('provider')}")
        else:
            _log(f"skipped daily summary: {result.get('reason')}")
        return result
    except Exception as exc:  # noqa: BLE001 — must never break the caller
        _log(f"daily summary delivery failed: {str(exc)[:300]}")
        return {"sent": False, "reason": "ERROR", "error": str(exc)[:300]}


def send_test_email(address: Optional[str] = None) -> Dict[str, Any]:
    """Send a test email to verify configuration. Never raises."""
    try:
        import phase20_store as store
        settings = store.get_settings()
        to = str(address or settings.get("email_alert_address") or "").strip()
        if not valid_address(to):
            return {"success": False, "sent": False,
                    "error": "No valid email address provided or configured."}
        status = provider_status()
        if not status["configured"]:
            return {"success": False, "sent": False,
                    "error": status["hint"], **status}
        parts = _compose(
            "TEST", "Test alert email",
            "This is a test of your losing-streak / circuit-breaker email "
            "alerts. If you received this, email delivery is working.",
            "INFO",
        )
        result = _deliver(to, parts["subject"], parts["text"],
                          parts.get("html"))
        return {"success": bool(result.get("sent")), **result}
    except Exception as exc:  # noqa: BLE001
        _log(f"test email failed: {str(exc)[:300]}")
        return {"success": False, "sent": False, "error": str(exc)[:300]}
