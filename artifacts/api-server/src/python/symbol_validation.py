"""
symbol_validation.py — Priority 3 (#26): prevent junk symbols from silently
breaking scans.

One central validator used before a symbol enters:
- the watchlist            (main.cmd_watchlist_add)
- the scan universe        (validate_universe — filters, never fails a scan)
- the portfolio            (paper buy path)
- alert / rule surfaces    (any future symbol-keyed rule)

Checks (with a clear rejection reason for each):
- blank / malformed symbols (NSE tickers: A-Z, 0-9, & and -; max 20 chars)
- duplicates (against a caller-supplied existing list)
- unsupported exchanges (only NSE; "BSE:..." etc. are rejected)
- expired / delisted instruments (not present in the Kite instrument master
  when a fresh master is available; falls back to the approved NIFTY 50
  universe when the master is unavailable)
- ambiguous company-name input (e.g. "RELIANCE INDUSTRIES" or "TATA") —
  rejected with candidate suggestions from the instrument master

Every rejection is tracked in a rolling diagnostics log
(symbol_validation_log.json) and mirrored to the audit trail
(phase20_notifications) so junk-symbol attempts are visible.

Advisory / research tooling only — never places live orders.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DIR = os.path.dirname(os.path.abspath(__file__))
DIAG_LOG_FILE = os.path.join(_DIR, "symbol_validation_log.json")
DIAG_LOG_MAX = 500

# NSE trading symbols: letters, digits, & and - (e.g. M&M, BAJAJ-AUTO)
_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9&-]{0,19}$")
_SUPPORTED_EXCHANGES = {"NSE"}


# ── Normalization ────────────────────────────────────────────────────────────

def normalize(raw: Any) -> Tuple[str, Optional[str]]:
    """
    Normalize user input to (symbol, exchange_prefix|None).
    Handles whitespace, case, unicode dashes, and "NSE:SYM" style prefixes.
    """
    s = str(raw or "").strip().upper()
    # Unicode dash/space variants → ASCII
    s = s.replace("\u2013", "-").replace("\u2014", "-").replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s)
    exchange = None
    if ":" in s:
        prefix, rest = s.split(":", 1)
        exchange = prefix.strip() or None
        s = rest.strip()
    return s, exchange


# ── Instrument master access (graceful) ──────────────────────────────────────

# A real Kite NSE equity master has thousands of rows. A tiny cache (e.g. a
# single probed symbol in dev) is partial — treating it as authoritative
# would wrongly reject valid symbols, so it is ignored below this size.
MIN_MASTER_SIZE = 100


def _instrument_master() -> Optional[Dict[str, Dict[str, Any]]]:
    """Return {tradingsymbol: instrument} from the Kite master, or None if
    the master is unavailable or too small to be authoritative. Never raises."""
    try:
        with open(os.path.join(_DIR, "kite_instruments_cache.json")) as f:
            cache = json.load(f)
        instruments = cache.get("instruments") or []
        if len(instruments) < MIN_MASTER_SIZE:
            return None
        return {str(i.get("tradingsymbol", "")).upper(): i for i in instruments}
    except Exception:
        return None


def _name_candidates(query: str, limit: int = 5) -> List[Dict[str, str]]:
    """Company-name lookup against the instrument master (for ambiguity
    detection and helpful suggestions)."""
    master = _instrument_master()
    if not master:
        return []
    q = query.upper()
    out = []
    for sym, inst in master.items():
        name = str(inst.get("name", "")).upper()
        if q == name:
            out.insert(0, {"symbol": sym, "name": inst.get("name", "")})
        elif q in name or name.startswith(q):
            out.append({"symbol": sym, "name": inst.get("name", "")})
        if len(out) >= limit * 3:
            break
    return out[:limit]


# ── Diagnostics / audit tracking ─────────────────────────────────────────────

def _track(symbol_raw: Any, context: str, ok: bool, reason: str) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "input": str(symbol_raw)[:80],
        "context": context,
        "accepted": ok,
        "reason": reason,
    }
    try:
        items: List[Dict[str, Any]] = []
        if os.path.exists(DIAG_LOG_FILE):
            with open(DIAG_LOG_FILE) as f:
                items = json.load(f)
        items.append(entry)
        items = items[-DIAG_LOG_MAX:]
        tmp = DIAG_LOG_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(items, f, indent=1)
        os.replace(tmp, DIAG_LOG_FILE)
    except Exception:
        logger.warning("could not write symbol validation log")
    if not ok:
        try:
            import phase20_store
            phase20_store.add_notification(
                "symbol_rejected", "Symbol rejected",
                f"'{entry['input']}' rejected for {context}: {reason}",
                severity="INFO",
                context={"input": entry["input"], "context": context, "reason": reason},
            )
        except Exception:
            pass


def get_validation_log(limit: int = 100) -> List[Dict[str, Any]]:
    try:
        with open(DIAG_LOG_FILE) as f:
            return list(reversed(json.load(f)))[:limit]
    except Exception:
        return []


# ── Core validation ──────────────────────────────────────────────────────────

def validate_symbol(raw: Any, *, context: str = "generic",
                    existing: Optional[List[str]] = None,
                    require_universe: bool = True) -> Dict[str, Any]:
    """
    Validate one symbol. Returns:
      {valid: True,  symbol: <normalized>}
      {valid: False, reason: <clear reason>, suggestions?: [...]}
    Rejections are tracked in diagnostics + audit logs.

    require_universe: when True (watchlist / scan universe / portfolio), the
    symbol must be in the approved NIFTY 50 research universe. The instrument
    master additionally screens delisted/expired instruments when available.
    """
    import config

    sym, exchange = normalize(raw)

    if not sym:
        reason = "Blank symbol"
        _track(raw, context, False, reason)
        return {"valid": False, "reason": reason}

    if exchange and exchange not in _SUPPORTED_EXCHANGES:
        reason = f"Unsupported exchange '{exchange}' — only NSE is supported"
        _track(raw, context, False, reason)
        return {"valid": False, "reason": reason}

    if not _SYMBOL_RE.match(sym):
        # Company-name style input? Offer suggestions instead of failing mute.
        candidates = _name_candidates(sym) if (" " in sym or len(sym) > 12) else []
        if candidates:
            reason = (f"'{sym}' looks like a company name, not a ticker. "
                      f"Did you mean: {', '.join(c['symbol'] for c in candidates)}?")
            _track(raw, context, False, "ambiguous company-name input")
            return {"valid": False, "reason": reason, "suggestions": candidates}
        reason = (f"Malformed symbol '{sym}' — NSE tickers use letters, digits, "
                  "'&' and '-' only (e.g. RELIANCE, M&M, BAJAJ-AUTO)")
        _track(raw, context, False, reason)
        return {"valid": False, "reason": reason}

    if existing is not None and sym in {str(e).upper() for e in existing}:
        reason = f"Duplicate — {sym} is already present"
        _track(raw, context, False, reason)
        return {"valid": False, "reason": reason}

    master = _instrument_master()
    if master is not None and sym not in master:
        candidates = _name_candidates(sym)
        reason = (f"'{sym}' is not an active NSE instrument (expired, delisted "
                  "or never listed)")
        _track(raw, context, False, reason)
        out: Dict[str, Any] = {"valid": False, "reason": reason}
        if candidates:
            out["suggestions"] = candidates
            out["reason"] += f". Similar: {', '.join(c['symbol'] for c in candidates)}"
        return out

    if require_universe and sym not in config.NIFTY_50:
        reason = (f"'{sym}' is outside the approved NIFTY 50 research universe")
        _track(raw, context, False, reason)
        return {"valid": False, "reason": reason}

    _track(raw, context, True, "ok")
    return {"valid": True, "symbol": sym}


# ── Company-name search (Priority 9 / #34) ──────────────────────────────────
# Built-in company names + common aliases for the approved NIFTY 50 research
# universe. Used when the Kite instrument master is unavailable; when the
# master IS available, its official names are overlaid on top.

COMPANY_NAMES: Dict[str, str] = {
    "TCS": "Tata Consultancy Services", "INFY": "Infosys", "WIPRO": "Wipro",
    "HCLTECH": "HCL Technologies", "TECHM": "Tech Mahindra", "LTIM": "LTIMindtree",
    "HDFCBANK": "HDFC Bank", "ICICIBANK": "ICICI Bank", "SBIN": "State Bank of India",
    "AXISBANK": "Axis Bank", "KOTAKBANK": "Kotak Mahindra Bank",
    "INDUSINDBK": "IndusInd Bank",
    "BAJFINANCE": "Bajaj Finance", "BAJAJFINSV": "Bajaj Finserv",
    "HDFCLIFE": "HDFC Life Insurance", "SBILIFE": "SBI Life Insurance",
    "SHRIRAMFIN": "Shriram Finance",
    "RELIANCE": "Reliance Industries", "ONGC": "Oil & Natural Gas Corporation",
    "POWERGRID": "Power Grid Corporation of India", "NTPC": "NTPC",
    "COALINDIA": "Coal India",
    "LT": "Larsen & Toubro", "ULTRACEMCO": "UltraTech Cement", "GRASIM": "Grasim Industries",
    "ADANIPORTS": "Adani Ports & SEZ",
    "MARUTI": "Maruti Suzuki India", "TATAMOTORS": "Tata Motors",
    "BAJAJ-AUTO": "Bajaj Auto", "EICHERMOT": "Eicher Motors",
    "M&M": "Mahindra & Mahindra", "HEROMOTOCO": "Hero MotoCorp",
    "HINDUNILVR": "Hindustan Unilever", "NESTLEIND": "Nestle India",
    "BRITANNIA": "Britannia Industries", "ITC": "ITC",
    "TATACONSUM": "Tata Consumer Products",
    "SUNPHARMA": "Sun Pharmaceutical Industries", "CIPLA": "Cipla",
    "DRREDDY": "Dr. Reddy's Laboratories", "DIVISLAB": "Divi's Laboratories",
    "APOLLOHOSP": "Apollo Hospitals Enterprise",
    "TATASTEEL": "Tata Steel", "HINDALCO": "Hindalco Industries",
    "JSWSTEEL": "JSW Steel", "ADANIENT": "Adani Enterprises",
    "TITAN": "Titan Company", "ASIANPAINT": "Asian Paints", "TRENT": "Trent",
    "BHARTIARTL": "Bharti Airtel",
}

# Common shorthand aliases people actually type → ticker.
ALIASES: Dict[str, str] = {
    "AIRTEL": "BHARTIARTL", "SBI": "SBIN", "HUL": "HINDUNILVR",
    "L&T": "LT", "LNT": "LT", "MAHINDRA": "M&M", "KOTAK": "KOTAKBANK",
    "NESTLE": "NESTLEIND", "ULTRATECH": "ULTRACEMCO", "APOLLO": "APOLLOHOSP",
    "HERO": "HEROMOTOCO", "SUZUKI": "MARUTI", "DRL": "DRREDDY",
    "TATA CONSULTANCY": "TCS", "UNILEVER": "HINDUNILVR",
}


def search_symbols(query: Any, limit: int = 8) -> Dict[str, Any]:
    """
    Search the APPROVED research universe by ticker, company name or alias.
    Returns {results: [{symbol, name, exchange, type, sector, match}]}.
    Only approved (NIFTY 50) instruments are ever returned — fuzzy matches
    outside the universe are excluded by construction. Never raises.
    """
    import config

    q = str(query or "").strip().upper()
    if not q:
        return {"results": [], "query": q}

    sector_of = {s: sec for sec, syms in config.SECTOR_MAP.items() for s in syms}
    master = _instrument_master()

    def entry(sym: str, match: str) -> Dict[str, Any]:
        inst = (master or {}).get(sym) or {}
        name = str(inst.get("name") or "").strip().title() or COMPANY_NAMES.get(sym, sym)
        return {
            "symbol": sym,
            "name": name,
            "exchange": str(inst.get("exchange") or "NSE"),
            "type": str(inst.get("instrument_type") or "EQ"),
            "sector": sector_of.get(sym, ""),
            "match": match,
        }

    exact: List[Dict[str, Any]] = []
    prefix: List[Dict[str, Any]] = []
    partial: List[Dict[str, Any]] = []
    seen = set()

    def add(sym: str, match: str, bucket: List[Dict[str, Any]]) -> None:
        if sym in seen or sym not in config.NIFTY_50:
            return
        seen.add(sym)
        bucket.append(entry(sym, match))

    # 1. Ticker matches
    for sym in config.NIFTY_50:
        if sym == q:
            add(sym, "ticker", exact)
        elif sym.startswith(q):
            add(sym, "ticker", prefix)
        elif q in sym:
            add(sym, "ticker", partial)

    # 2. Alias matches
    for alias, sym in ALIASES.items():
        if alias == q:
            add(sym, "alias", exact)
        elif alias.startswith(q) or q in alias:
            add(sym, "alias", partial)

    # 3. Company-name matches (built-in map + live master overlay)
    names: Dict[str, str] = {s: n.upper() for s, n in COMPANY_NAMES.items()}
    if master:
        for sym in config.NIFTY_50:
            inst = master.get(sym)
            if inst and inst.get("name"):
                names[sym] = str(inst["name"]).upper()
    for sym, name in names.items():
        if name == q:
            add(sym, "name", exact)
        elif name.startswith(q):
            add(sym, "name", prefix)
        elif q in name:
            add(sym, "name", partial)

    results = (exact + prefix + partial)[:max(1, int(limit))]
    return {
        "results": results,
        "query": q,
        # Multiple hits mean the input is ambiguous — the caller must ask the
        # user to pick; it must NEVER auto-add the first fuzzy match.
        "ambiguous": len(results) > 1,
    }


def validate_universe(symbols: List[Any], *, context: str = "scan") -> Dict[str, Any]:
    """
    Filter a scan universe: invalid entries are dropped and reported, valid
    ones are deduplicated and returned. One junk symbol can NEVER fail the
    full scan — this function never raises.
    """
    valid: List[str] = []
    rejected: List[Dict[str, Any]] = []
    seen = set()
    for raw in symbols or []:
        try:
            r = validate_symbol(raw, context=context, require_universe=True)
        except Exception as exc:  # absolute belt-and-braces
            rejected.append({"input": str(raw)[:80], "reason": f"validator error: {exc}"})
            continue
        if r.get("valid"):
            s = r["symbol"]
            if s not in seen:
                seen.add(s)
                valid.append(s)
        else:
            rejected.append({"input": str(raw)[:80], "reason": r.get("reason", "invalid")})
    return {"valid": valid, "rejected": rejected}
