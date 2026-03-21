"""
Bahamut v8 — Defensive Strategy

CRASH regime behavior: NO TRADE.
Capital preservation is the priority.

This strategy never generates signals. Its purpose is to:
  1. Be the active sleeve in CRASH regime (accounting placeholder)
  2. Keep capital idle and safe
  3. Show in dashboard that the system is deliberately not trading

No defensive shorts — the research showed shorting BTC is negative EV
even in crashes when using a trend-following system.
"""
from typing import Optional
from bahamut.strategies.base import BaseStrategy, StrategyMeta, Signal


class V8Defensive(BaseStrategy):
    meta = StrategyMeta(
        name="v8_defensive",
        version="8.0",
        description="Capital preservation — no trading in CRASH regime",
        sl_pct=0.0,
        tp_pct=0.0,
        max_hold_bars=0,
        risk_pct=0.0,
    )

    def evaluate(self, candles: list, indicators: dict,
                 prev_indicators: dict = None, asset: str = "BTCUSD") -> Optional[Signal]:
        """Always returns None. Capital stays idle in CRASH."""
        return None
