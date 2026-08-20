# ApexQuant Inventory Review — Inconsistency Findings

**Reviewed document:** `APEXQUANT_FULL_SYSTEM_PHASE_AGENT_UI_ARCHITECTURE_INVENTORY.md` (dated 21 Aug 2026, 506 lines, 15 sections)
**What I checked:** cross-referenced facts, labels, and status values against each other across the whole document to find contradictions, undefined terminology, and gaps.

## Summary
The document is internally consistent on the facts it repeats — the 15:15 / 15:20 / 15:30 IST safety timings, the "cache is live" status, and the NIFTY 50-vs-custom-universe framing all agree everywhere they appear. The real issues are (1) the evidence-status labeling system it defines up front isn't actually followed, and (2) a handful of unexplained numbering gaps. There are also known production-vs-documentation conflicts — the report already flags these itself, but they're consolidated below since they're the highest-stakes items.

## 1. The evidence-status taxonomy isn't consistently applied
Section 1.1 defines exactly **7** canonical status labels (PRODUCTION-OBSERVED, DEV-SCHEMA-OBSERVED, CODE-PROVEN, IMPLEMENTED-RUNTIME-UNKNOWN, PARTIAL/CONFLICTING, OBSOLETE/LEGACY, UNKNOWN). In practice, the "Status" columns in Sections 3, 4, 7, and 9 use well over a dozen variants outside that list:
- **"IMPLEMENTED, PARTIAL"** appears ~16 times in Section 3's Phase table alone — making it the single most-used status label in the whole report, despite not being one of the 7 defined terms.
- Hybrids not in the glossary: "CODE-PROVEN / PRODUCTION-OBSERVED," "CODE-PROVEN / TEST-PROVEN," "CODE-PROVEN / PARTIAL PRODUCTION," "CODE-PROVEN documentation."
- Section 9's safety matrix invents its own separate set: "PROVEN," "PARTIALLY PROVEN," "DB-PROVEN," "NOT PROVEN," "CODE/TEST-PROVEN."
- The low-price-universe row (Section 3) uses **"DB-SCHEMA-OBSERVED,"** which is close to, but not, the glossary's **"DEV-SCHEMA-OBSERVED."**
- RC/Batch 9 is "LEGACY / FROZEN" and RC/Batch 10 is "LEGACY / REVIEWED" — two different labels for what the glossary calls "OBSOLETE / LEGACY."

Only ~4 of the ~35 rows in Section 3 use an exact glossary term. **Why it matters:** if anyone (human or script) filters this document by the Section 1.1 definitions — e.g. "show everything still UNKNOWN" — the undefined variants will silently fall through the cracks.

## 2. Unexplained gaps in phase/sub-phase numbering
- **Phase 26** is covered as "26 / 26A / 26C / 26D" — **26B is never mentioned.**
- **Phase 27** is covered as "27 / 27C–27F" — **27A and 27B are never mentioned.**
- **Phase 23** is covered as "23 / 23.8 / 23.9" — **23.1–23.7 are never mentioned.**

Nothing in the document says whether these numbers don't exist, were merged into neighboring phases, or were simply out of scope for this pass. Given the report positions itself as the "consistency baseline" (line 6), that ambiguity should be closed explicitly rather than left implicit.

## 3. Production configuration contradicts the system's own prior documentation
The report already surfaces these (Sections 2.3 and 13) — grouped here because they share one root cause and are the highest-stakes items to resolve first:

| Topic | Documented / expected elsewhere | Currently observed in production |
|---|---|---|
| Paper capital | ₹100,000 (per migration report) | **₹500,000** |
| Active universe | Low-price IT/Infra/Bank custom universe implemented | **NIFTY 50** is actually active |
| Auto paper entry / bootstrap | Implied "disabled by default" in older material | **Enabled**, with no note distinguishing default vs. live state |
| LTIM removal | Reported as removed from universe | **Not re-confirmed**; earlier evidence still showed it unavailable |

## 4. A scope claim is undercut by an unresolved fact elsewhere in the same document
Section 2.2 reports a `TRENT` position still `OPEN` after market close, and Section 9 marks "Completed trade cannot mutate" as **NOT PROVEN**. Yet Section 5's end-to-end flow map calls the same ledger "canonical" without a caveat at that point in the text. The caveat does exist elsewhere (Sections 2.3, 9, 10, 14), but a reader who only sees Section 5 could come away trusting the ledger more than the report's own evidence supports.

## 5. Minor / cosmetic
- Section 2.2's pipeline stage names (`SCANNER`, `MONITORING`) don't exactly match the Section 4.2 agent names they apparently map to (`Market Data`, `Stock Monitoring`) — likely just a pipeline-stage-vs-agent-class naming difference, not a factual conflict, but worth a footnote if this doc is shared across teams.
- The header cites a "Master brief" (`Pasted-FULL-SYSTEM-ARCHITECTURE-INVENTORY-REVIEW-EVERY-PHASE-U_1787258411558.txt`) that wasn't included in this upload, so I couldn't verify the inventory actually covers everything that brief requested — flagging as unverifiable rather than as a finding.

## Bottom line
No contradictions turned up in the core trading-safety claims (entry cutoff, EOD timings, paper-only execution) — those hold up everywhere they're repeated. The actionable issues are: an inconsistent status vocabulary that weakens the document's own audit framework (#1), unexplained numbering gaps (#2), and the four production-vs-documentation conflicts (#3), which should go to whoever owns Section 13's "Open operator decisions" before this is used as a baseline for new work.
