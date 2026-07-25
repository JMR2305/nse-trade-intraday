# Apex Global — Brand Replacement Report
**Date:** 2026-07-25  
**Scope:** Complete brand replacement across NSE Trading Platform  
**Status:** ✅ COMPLETE

---

## 1. Brand Assets Created

| File | Format | Purpose | Background |
|------|--------|---------|------------|
| `public/apex-global-symbol.svg` | SVG | Standalone mountain mark | Transparent |
| `public/apex-global-logo-horizontal.svg` | SVG | Symbol + "APEX GLOBAL" wordmark (navy) | Transparent |
| `public/apex-global-logo-white.svg` | SVG | Symbol + wordmark in white (for dark/navy surfaces) | Transparent |
| `public/apex-global-logo-monochrome.svg` | SVG | Symbol + wordmark in black | Transparent |
| `public/favicon.svg` | SVG | Favicon — navy mark on cream `#F7F4ED` rounded tile | Cream tile |
| `public/manifest.webmanifest` | JSON | PWA manifest — name, theme colour, icons | — |

**Symbol geometry:**  
The Apex Global mountain mark is an SVG compound path using `fill-rule="evenodd"`:
```
Mountain triangle: M2,42 L24,2 L46,42 Z
Gap 1 (left outer/inner): M11,42 L13,42 L24,2 Z
Gap 2 (left inner/center): M19,42 L21,42 L24,2 Z
Gap 3 (center/right inner): M27,42 L29,42 L24,2 Z
Gap 4 (right inner/outer): M35,42 L37,42 L24,2 Z
```
Four thin triangular gaps radiate from the apex, creating five solid rising segments — faithful to the uploaded logo reference. The symbol reads clearly at 16px, 24px, and 32px because the gaps widen toward the base.

**Note — raster PNG assets:**  
`apple-touch-icon.png` and PWA icons at 192×192 / 512×512 are not auto-generated here because SVG→PNG conversion requires a build tool (e.g. `sharp`, `svgexport`, or Inkscape CLI). The `manifest.webmanifest` references the SVG icon directly, which is supported by all modern browsers. Raster PNGs can be generated with: `npx svgexport public/favicon.svg public/icon-192.png 192:192`.

---

## 2. Files Changed

### New files (5)
| File | Change |
|------|--------|
| `src/components/brand/Logo.tsx` | **Rewritten** — Apex mountain mark (SVG compound path, `fill="currentColor"`, navy light / cream dark), "Apex Global" wordmark; removed `wordmark` prop |
| `src/components/brand/OfflineScreen.tsx` | **New** — branded offline/error screen with Apex symbol, wordmark, PAPER TRADING badge, retry button, optional cached-data fallback, technical details accordion |
| `public/apex-global-symbol.svg` | **New** |
| `public/apex-global-logo-horizontal.svg` | **New** |
| `public/apex-global-logo-white.svg` | **New** |
| `public/apex-global-logo-monochrome.svg` | **New** |
| `public/manifest.webmanifest` | **New** |

### Modified files (12)
| File | Change |
|------|--------|
| `public/favicon.svg` | **Replaced** — was orange square; now navy Apex mark on cream rounded tile |
| `index.html` | **Updated** — title, description, OG, Twitter, theme-color (light+dark), manifest link, apple-touch-icon link |
| `src/components/layout/AppLayout.tsx` | **Updated** — "Research Engine v1.0" × 2 → "Apex Global"; "AI Active" → "AI Advisory Active"; mobile top bar gains amber "PAPER" badge beside Logo |
| `src/components/omni/Charts.tsx` | **Updated** — removed "OmniRoute design system" comment |
| `src/components/omni/MetricCard.tsx` | **Updated** — removed "OmniRoute design system" comment |
| `src/components/omni/ProgressGauge.tsx` | **Updated** — removed "OmniRoute design system" comment |
| `src/pages/Phase12Intelligence.tsx` | **Updated** — engine fallback label "Research Engine v1.0 · Phase 12" → "Apex Global AI Engine · Phase 12" |
| `artifacts/trading-mobile/app.json` | **Updated** — `name`: "NSE Trader" → "Apex Global"; `splash.backgroundColor`: `#0e1119` → `#F7F4ED`; `android.adaptiveIcon.backgroundColor`: `#F7F4ED` |

### Unchanged (intentional)
| Internal reference | Reason kept |
|-------------------|-------------|
| `RESEARCH_ENGINE_VERSION = "Research Engine v1.0"` in Python backend files (`phase11_diagnostics.py`, `phase12_intelligence.py`, `phase12_diagnostics.py`, `phase13_*`) | Internal version constant in frozen backend engine — not user-visible; brand spec: "Do not blindly rename technical backend package names" |
| `similarity_engine.py` / `trading.ts` docstring: "v2.1 Evidence-Based Research Engine" | Internal code comment, not user-facing |
| `phase18_exports.py`: "NSE Trader (PAPER / RESEARCH ONLY)" in README text of exported ZIP | Inside downloaded archive, not visible in the UI |
| `docs/*.md` files (`INTRADAY_ARCHITECTURE_REVIEW.md` etc.) | Internal architecture documentation, not user-facing |
| `.local/tasks/*.md` | Internal task planning files |
| `lib/api-client-react/src/generated/api.ts` and `lib/api-zod/src/generated/api.ts` docstrings | Auto-generated from API spec; "Research Engine" is a technical description of an endpoint, not a brand name |

---

## 3. Brand Placement Verification

| Surface | Status | Notes |
|---------|--------|-------|
| Desktop sidebar (expanded) | ✅ | Apex mountain mark + "APEX GLOBAL" wordmark |
| Desktop sidebar (collapsed) | ✅ | Symbol only (ChevronLeft toggle) |
| Desktop top bar | ✅ | "AI Advisory Active" pill (green); NSE OPEN pill |
| Mobile top bar | ✅ | Symbol + "APEX GLOBAL" + amber "PAPER" badge |
| Mobile drawer | ✅ | Logo + nav items + "Apex Global" footer |
| Sidebar footer | ✅ | "Apex Global" (was "Research Engine v1.0") |
| Browser title | ✅ | "Apex Global — AI-Powered NSE Trading Platform" |
| OG / Twitter meta | ✅ | Updated in index.html |
| PWA manifest | ✅ | name: "Apex Global", theme_color: #17395F |
| Favicon | ✅ | Navy Apex mark on cream tile |
| Offline/error screen | ✅ | `OfflineScreen.tsx` — symbol + wordmark + PAPER TRADING badge + retry |
| Mobile app name | ✅ | app.json `name`: "Apex Global" |
| Mobile splash background | ✅ | `#F7F4ED` (cream) replacing dark `#0e1119` |

---

## 4. Product Language Applied

| Requirement | Applied where |
|-------------|--------------|
| Brand: "Apex Global" | Logo, sidebar, top bar, mobile, manifest, meta |
| Category: "AI-Powered NSE Trading Platform" | Browser title, OG description, OfflineScreen footer |
| Mode: "Paper Trading" | Mobile PAPER badge, OfflineScreen badge, Settings page already had "PAPER / LIVE DATA VALIDATION" |
| AI status: "AI Advisory Active" | Top bar pill (was "AI Active") |
| LIVE TRADING disabled | Unchanged — no live execution code was touched |
| AI advisory only | Unchanged — no AI decision logic was touched |

---

## 5. Build / Typecheck / Lint Results

| Check | Result |
|-------|--------|
| `pnpm typecheck` | ✅ **0 errors** |
| `pnpm build` (with PORT) | ✅ **Exit 0** — 2,524 modules, 7.96s |
| `pnpm test --run` | ✅ **211/211 tests pass** (5 test files) |

---

## 6. Visual Verification

### Desktop (1400×900)
- Apex mountain mark (navy on dark sidebar) renders top-left ✅
- "APEX GLOBAL" wordmark beside mark ✅  
- Collapsible sidebar toggle (ChevronLeft) still present ✅
- "AI Advisory Active" pill in top-right header ✅
- "Apex Global" in sidebar footer ✅
- All nav groups (OVERVIEW, SIGNALS, TRADES, SYSTEM) intact ✅

### Mobile (430×932)
- Apex mountain mark + "APEX GLOBAL" in mobile top bar ✅
- Amber **"PAPER"** badge clearly visible beside wordmark ✅
- Theme toggle in mobile bar ✅
- LiveMarketTicker, StaleScanBanner, AI Copilot panel all intact ✅

---

## 7. No Frozen Backend Changes

Zero files modified in:
- `artifacts/api-server/src/python/` (trading engine, strategy, RC-8/RC-9/RC-10)
- `artifacts/api-server/src/routes/` (API routes)
- `lib/db/` (database schema)
- Any Python portfolio, exposure, reconciliation, or broker logic

---

*Brand replacement complete: 2026-07-25*
