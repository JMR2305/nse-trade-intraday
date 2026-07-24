"""RC-10C1: Portfolio Core.

Authoritative portfolio state, capital allocation, position sizing,
exposure control, P&L accounting, persistence, and reconciliation.

Frozen invariants:
- RC-8 remains the final risk authority.
- RC-7 remains the execution authority.
- RC-10D remains the only broker integration layer.
- No portfolio component calls Zerodha directly.
- No portfolio component places, modifies, or cancels orders.
- Paper trading remains the default; live trading remains disabled.
"""
