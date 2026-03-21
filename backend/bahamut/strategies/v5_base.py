"""
v5_base — EMA20×50 golden cross in bull regime.

SL: 8% | TP: 16% | Max hold: 30 bars
Validated profitable on realistic BTC data (5/5 seeds positive).
"""
from typing import Optional
from bahamut.strategies.base import BaseStrategy, StrategyMeta, Signal


class V5Base(BaseStrategy):
    meta = StrategyMeta(
        name="v5_base",
        version="5.0",
        description="EMA20x50 golden cross, bull regime, SL 8%, TP 16%",
        sl_pct=0.08,
        tp_pct=0.16,
        max_hold_bars=30,
        risk_pct=0.02,
    )

    def evaluate(self, candles: list, indicators: dict,
                 prev_indicators: dict = None) -> Optional[Signal]:
        close = indicators.get("close", 0)
        ema_20 = indicators.get("ema_20", 0)
        ema_50 = indicators.get("ema_50", 0)
        ema_200 = indicators.get("ema_200", 0)

        if close <= 0 or ema_20 <= 0 or ema_50 <= 0 or ema_200 <= 0:
            return None
        if prev_indicators is None:
            return None

        prev_20 = prev_indicators.get("ema_20", 0)
        prev_50 = prev_indicators.get("ema_50", 0)
        if prev_20 <= 0 or prev_50 <= 0:
            return None

        # Bull regime: price above EMA200
        if close <= ema_200:
            return None

        # Golden cross: EMA20 crosses above EMA50
        if prev_20 <= prev_50 and ema_20 > ema_50:
            return Signal(
                strategy=self.meta.name,
                asset="BTCUSD",
                direction="LONG",
                sl_pct=self.meta.sl_pct,
                tp_pct=self.meta.tp_pct,
                max_hold_bars=self.meta.max_hold_bars,
                quality=0.7,
                reason="EMA20x50 golden cross, bull regime",
            )
        return None
