# RTV-2C Safety Authority Map

## Canonical authority

`phase20_store` is the only persistence authority for Phase 20 settings.
Its PostgreSQL row is authoritative; the checked-in JSON file is a warm cache
and release default only.

### Automatic-entry state rules

| Situation | Result |
| --- | --- |
| Default settings | Automatic entries disabled |
| `auto_paper_entries=true` without confirmation | Normalized to disabled |
| Durable settings unavailable, missing, unreadable, or malformed | Disabled |
| Explicit disable | Disabled and confirmation cleared |
| Explicit enable | Requires the exact Phase 20 confirmation |

The executor performs the final defense-in-depth check: it requires enabled
and confirmed settings and a durable database admission path before it can
create a paper entry.

## Explicit activation path

The sole remaining production activation authority is
`phase22_activation.enable_paper_automation`:

1. Caller supplies the exact Phase 22 typed acknowledgement.
2. Phase 22 readiness checklist must pass.
3. It invokes the guarded shared settings update.
4. It records Phase 22 activation evidence and notification.

The legacy `daily_session_enable_autonomous` command now delegates to this
path and forwards a caller-supplied confirmation; it no longer supplies a
confirmation internally.

## Non-authorities

- `daily_session_manager` reads and reports automatic-entry state but never
  writes it.
- `phase20_scheduler` consumes the state and skips entries when disabled or
  unconfirmed.
- `phase20_executor` consumes and revalidates the state; it cannot enable it.
- Bootstrap additionally requires `bootstrap_paper_enabled`, an enabled and
  confirmed automatic-entry state, and its own entry safeguards.
- Reporting, dashboard, readiness, and simulation modules do not write the
  shared Phase 20 settings authority.

## Release guards

The Phase 20 test suite now asserts:

- checked-in settings keep automatic entries and bootstrap disabled;
- missing/unavailable durable settings fail closed;
- malformed durable settings fail closed;
- daily initialization cannot call the settings write path;
- the daily-session activation command delegates to Phase 22 rather than
  embedding the Phase 20 confirmation.