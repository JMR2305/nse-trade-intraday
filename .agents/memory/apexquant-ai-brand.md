---
name: ApexQuant AI brand
description: Brand identity, color tokens, SVG mark geometry, component names, and which legacy names are intentionally kept.
---

## Brand identity
- **Brand name:** ApexQuant AI
- **Tagline:** AI-Powered NSE Trading Platform
- **Mode badge:** PAPER TRADING (always visible)
- **AI language:** "AI Advisory Active" — never "live trades"

## Color tokens
| Token | Hex | Use |
|-------|-----|-----|
| Primary navy | `#17395F` | A-frame, bars, headings, active states |
| Accent teal | `#129C8C` | Trend line, arrow, "AI" in wordmark |
| Light teal (dark mode) | `#4ECDC4` | Teal elements on dark/navy backgrounds |
| Cream | `#F7F4ED` | Light mode bg, dark mode logo color |

## SVG mark geometry (viewBox "0 0 60 56")
```
Left leg:   path d="M3,54 L16,54 L30,4 Z"
Right leg:  path d="M57,54 L44,54 L30,4 Z"
Bar 1:      rect x=20 y=44 width=4 height=10
Bar 2:      rect x=26 y=36 width=4 height=18
Bar 3:      rect x=32 y=28 width=4 height=26
Trend line: polyline 20,50 26,38 32,30 43,18
Arrow head: polygon 43,18 42,24 37,20
```
A-frame + bars use `fill="currentColor"`; trend line/arrow use hardcoded `#129C8C`.

## Component architecture
```
src/components/brand/
  BrandMark.tsx          SVG mark only (props: size, color, accentColor)
  BrandLogo.tsx          BrandMark + "ApexQuant AI" wordmark (props: size, showWordmark, white)
  PaperTradingBadge.tsx  Amber PAPER / PAPER TRADING pill (prop: compact)
  BrandHeader.tsx        BrandLogo + badge + optional AI Advisory status (for splash/offline)
  Logo.tsx               Re-exports above as { Logo, ApexSymbol, BrandLogo, BrandMark, ... }
  OfflineScreen.tsx      Branded error screen using BrandHeader
```
Existing imports of `{ Logo }` or `{ ApexSymbol }` from `@/components/brand/Logo` still work unchanged.

## Public assets
```
public/branding/apexquant-ai-logo.png        Approved PNG logo (with cream bg)
public/branding/apexquant-ai-symbol.svg      Mark only, transparent bg
public/branding/apexquant-ai-logo-horizontal.svg  Mark + wordmark, navy
public/branding/apexquant-ai-logo-white.svg  Mark + wordmark, white variant
public/favicon.svg                           Mark on cream rounded tile
public/manifest.webmanifest                  PWA: name "ApexQuant AI", theme #17395F
```

## Intentionally kept legacy names
- `RESEARCH_ENGINE_VERSION = "Research Engine v1.0"` in Python backend — frozen engine internal constant, not user-visible
- `"v2.1 Evidence-Based Research Engine"` in `similarity_engine.py` / `trading.ts` — technical endpoint docstring
- `"NSE Trader (PAPER / RESEARCH ONLY)"` in `phase18_exports.py` — inside downloaded ZIP archive

## Vitest / E2E separation
`e2e/health-card-degraded.spec.ts` is a Playwright spec — excluded from Vitest via `test.exclude: ["**/e2e/**"]` in `vite.config.ts`. Run it with `pnpm test:e2e`.

**Why:** Playwright uses `test.describe()` from `@playwright/test`; Vitest's runner errors when it encounters a Playwright describe block outside of a Playwright context.
