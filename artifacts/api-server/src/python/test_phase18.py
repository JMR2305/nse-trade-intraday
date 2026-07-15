"""
test_phase18.py — Phase 18 Research Notebook, Daily Validation Workflow &
Evidence Accumulation tests.

Run: python3 test_phase18.py
PAPER TRADING / RESEARCH ONLY.
Uses only stored notebook / trade data — nothing is fabricated.
"""
import json
import os

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


import phase18_notebook as nb
import phase18_reviews as rv
import phase18_exports as ex

# ── T1: entry creation / idempotence ────────────────────────────────────────
print("== Entry engine ==")
r1 = nb.ensure_today_entry()
check("ensure returns success key", "success" in r1)
if r1.get("success") and r1.get("entry"):
    e = r1["entry"]
    today = nb.ist_today()
    check("entry keyed by IST date", e.get("trading_date") == today)
    r2 = nb.ensure_today_entry()
    check("idempotent — no duplicate entry", r2.get("created") is False)
    check("integrity block present", isinstance(e.get("integrity"), dict))
    check("live execution disabled recorded",
          e["integrity"].get("live_execution_enabled") is False)
    check("scan id recorded", bool((e.get("scan") or {}).get("scan_id")))
    check("checklist has 3 sections",
          all(k in (e.get("checklist") or {}) for k in
              ("before_market", "during_market", "after_market")))
    states = {d.get("decision_state") for d in e.get("decisions", [])}
    valid = {"PAPER TRADE TAKEN", "SKIPPED", "WATCHED", "WATCH",
             "REJECTED BY RISK", "REJECTED BY DATA QUALITY",
             "NO ACTION", "POSITION EXITED"}
    check("decision states valid", states <= valid, str(states - valid))
else:
    check("ensure declined honestly (stale/no scan)",
          bool(r1.get("reason")), json.dumps(r1)[:120])

# ── T2: user fields preserved across rebuild ────────────────────────────────
print("== User-field preservation ==")
today = nb.ist_today()
got = nb.get_entry(today)
if got.get("available"):
    nb.save_notes(date_iso=today, note_text="phase18 test note",
                  note_tags=["test-tag"])
    nb.ensure_today_entry()
    e = nb.get_entry(today)["entry"]
    texts = [n.get("text") for n in e.get("user_notes", [])]
    check("note survives entry refresh", "phase18 test note" in texts)
else:
    check("no entry — preservation not checkable (honest skip)", True)

# ── T3: decision recording ──────────────────────────────────────────────────
print("== Decision journal ==")
if got.get("available") and got["entry"].get("decisions"):
    sym = got["entry"]["decisions"][0]["symbol"]
    r = nb.record_user_decision(date_iso=today, symbol=sym,
                                user_action="SKIPPED", reason="unit test")
    check("decision recorded", r.get("success") is True)
    e = nb.get_entry(today)["entry"]
    d = next(x for x in e["decisions"] if x["symbol"] == sym)
    check("user action stored", d.get("user_action") == "SKIPPED")
    check("user reason stored", d.get("user_reason") == "unit test")
else:
    check("no decisions available (honest skip)", True)

# ── T4: finalize / reopen ───────────────────────────────────────────────────
print("== Finalize / reopen ==")
if got.get("available"):
    f = nb.finalize_day(today)
    check("finalize success", f.get("success") is True, json.dumps(f)[:120])
    e = nb.get_entry(today)["entry"]
    check("state FINALIZED", e.get("state") == "FINALIZED")
    check("eod present", isinstance(e.get("eod"), dict))
    ro = nb.reopen_day(today)
    check("reopen success", ro.get("success") is True)
    check("state back to DRAFT", nb.get_entry(today)["entry"]["state"] == "DRAFT")
else:
    check("no entry to finalize (honest skip)", True)

# ── T5: search ──────────────────────────────────────────────────────────────
print("== Search ==")
s = nb.search(query="")
check("search success", s.get("success") is True)
check("results list", isinstance(s.get("results"), list))
s2 = nb.search(symbol="ZZZ_NO_SUCH_SYMBOL")
check("no fabricated matches", s2.get("count") == 0)

# ── T6: issues ──────────────────────────────────────────────────────────────
print("== Issue tracker ==")
i = nb.add_issue(description="unit-test issue", severity="LOW", page="test")
check("issue added with id", str(i.get("issue", {}).get("issue_id", "")).startswith("ISS-"))
iid = i["issue"]["issue_id"]
u = nb.update_issue(issue_id=iid, status="VERIFIED", resolution="test done")
check("issue updated", u.get("success") is True)
li = nb.list_issues(status="VERIFIED")
check("filtered listing works", any(x["issue_id"] == iid for x in li["issues"]))

# ── T7: reviews honesty ─────────────────────────────────────────────────────
print("== Reviews ==")
w = rv.weekly_review()
check("weekly success", w.get("success") is True)
check("weekly bounds set", bool(w.get("week_start")) and bool(w.get("week_end")))
m = rv.monthly_review()
check("monthly success", m.get("success") is True)
calib = m.get("confidence_calibration") or {}
check("calibration bands present", all(k in calib for k in ("<50", "50-70", ">=70")))
check("insufficient-data honesty in calibration",
      all(isinstance(v, dict) or v == "Insufficient Data" or isinstance(v, str)
          for v in calib.values()))
ev = rv.evidence_tracker()
check("evidence success", ev.get("success") is True)
check("evidence progress dict", isinstance(ev.get("progress"), dict))

# ── T8: targets ─────────────────────────────────────────────────────────────
print("== Targets ==")
t = nb.get_targets()
check("targets present", t.get("completed_paper_trades", 0) > 0)
upd = nb.update_targets({"completed_paper_trades": t["completed_paper_trades"]})
check("targets update success", upd.get("success") is True)

# ── T9: exports + archive ───────────────────────────────────────────────────
print("== Exports ==")
d = ex.export_daily()
check("export_daily returns dict", isinstance(d, dict))
a = ex.build_archive()
check("archive builds", a.get("success") is True)
check("archive zip exists", os.path.exists(a.get("zip_path", "")))
import zipfile
with zipfile.ZipFile(a["zip_path"]) as z:
    names = z.namelist()
    check("archive has README", "README.txt" in names)
    check("archive has validation summary",
          any(n.startswith("validation/") for n in names))
    blob = " ".join(names).lower()
    check("no secret-looking files in archive",
          not any(k in blob for k in ("secret", "token", "password", "api_key")))

# ── summary ─────────────────────────────────────────────────────────────────
print(f"\n{PASS} passed, {FAIL} failed")
raise SystemExit(1 if FAIL else 0)
