"""RC-10C1: Portfolio Core package.

FROZEN INVARIANTS (enforced at architecture level):
- RC-8 remains the final risk authority for all orders.
- RC-7 remains the execution authority; portfolio never places orders.
- RC-10D remains the only broker integration layer.
- No portfolio component may call Zerodha directly.
- No portfolio component may place, modify, or cancel orders.
- RC-10B remains advisory-only; portfolio does not drive autonomous AI trades.
- Paper trading is the default; live trading remains structurally disabled.

Signal flow (required):
  Strategy → SignalRouter → Portfolio Pre-Check → RC-8 → RC-7 → RC-10D

Feedback flow:
  RC-10D Broker State → Portfolio Reconciliation → Portfolio State
  → Exposure / P&L / Buying Power → Strategy & Risk Context
"""
