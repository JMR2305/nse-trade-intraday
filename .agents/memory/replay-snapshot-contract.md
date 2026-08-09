---
name: Unified replay snapshot field contract
description: Field names UI code must use when consuming /replay/sessions/latest
---
The unified replay snapshot (`/api/replay/sessions/latest`) exposes stages as
`{id, stocks_in, stocks_out, rejected, pending, cancelled, ...}` — NOT
`stage/in/out` — and decisions as `{symbol, final_action, confidence, ...}`
(`final_action` includes "STRONG BUY" with a space; match with /BUY/i).

Stage ids are lowercase and differ from pipeline-summary stage names in one
place: replay `market_data` ↔ summary `SCANNER`. Alias when joining the two.

**Why:** a Command Center enrichment silently rendered empty stage counts and
zero candidates because it guessed `stage/in/out/action`; the endpoint
returned 200 with valid data throughout.

**How to apply:** curl the endpoint (60s+ timeout) and check real keys before
typing any interface against it; never trust remembered shapes.
