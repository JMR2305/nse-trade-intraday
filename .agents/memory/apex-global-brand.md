---
name: Apex Global brand
description: Brand identity, color tokens, and which legacy names are intentionally kept in the backend.
---

## Brand identity
- **Brand name:** Apex Global
- **Tagline:** AI-Powered NSE Trading Platform
- **Mode badge:** Paper Trading (always visible)
- **AI language:** "AI Advisory Active" — never "AI Active" or "live trades"

## Color tokens
| Token | Hex | Use |
|-------|-----|-----|
| Primary navy | `#17395F` | Logo mark, headings, nav active states |
| Cream | `#F7F4ED` | Light mode background, dark mode logo color |
| Dark text | `#243142` | Body text on light |
| Teal accent | `#129C8C` | Controlled accent only (not primary) |

## Logo component
`src/components/brand/Logo.tsx` — SVG compound path with `fill-rule="evenodd"`:
- Mountain triangle minus 4 thin radial gaps → 5 solid rising segments
- Uses `fill="currentColor"`; wrapper: `text-[#17395F] dark:text-[#F7F4ED]`
- Props: `showWordmark` (default true), `size` (default 28)
- No `wordmark` prop — "Apex Global" is hardcoded

## Assets in `artifacts/trading-dashboard/public/`
- `apex-global-symbol.svg` — mark only, transparent bg
- `apex-global-logo-horizontal.svg` — mark + wordmark, navy
- `apex-global-logo-white.svg` — mark + wordmark, white
- `apex-global-logo-monochrome.svg` — mark + wordmark, black
- `favicon.svg` — mark on cream rounded tile
- `manifest.webmanifest` — PWA manifest, theme_color #17395F

## Intentionally kept legacy names (do NOT rename)
- `RESEARCH_ENGINE_VERSION = "Research Engine v1.0"` in Python backend files — internal version constant in frozen engine, not user-visible
- `"v2.1 Evidence-Based Research Engine"` docstrings in `similarity_engine.py` and `trading.ts` — technical description of endpoint behavior
- `"NSE Trader (PAPER / RESEARCH ONLY)"` in `phase18_exports.py` README text — inside downloaded archive ZIP, not UI

**Why:** Brand spec: "Do not blindly rename technical backend package names or database identifiers unless they are strictly frontend branding fields."
