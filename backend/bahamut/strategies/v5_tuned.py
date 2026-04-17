"""
v5_tuned — Same signal as v5_base with wider SL/TP for better trend capture.

SL: 10% | TP: 25% | Max hold: 60 bars
Higher return per trade, slightly lower Monte Carlo robustness.
"""
from typing import Optional
from bahamut.strategies.base import BaseStrategy, StrategyMeta, Signal


class V5Tuned(BaseStrategy):
    meta = StrategyMeta(
        name="v5_tuned",
        version="5.1",
        description="EMA20x50 golden cross, bull regime, SL 10%, TP 25%",
        sl_pct=0.10,
        tp_pct=0.25,
        max_hold_bars=60,
        risk_pct=0.02,
    )

    def evaluate(self, candles: list, indicators: dict,
                 prev_indicators: dict = None, asset: str = "BTCUSD") -> Optional[Signal]:
        # Canonical suppress check (was missing from v5_tuned)
        from bahamut.config_assets import is_suppressed
        if is_suppressed(asset, self.meta.name):
            return None

        close = indicators.get("close", 0)
        ema_20 = indicators.get("ema_20", 0)
        ema_50 = indicators.get("ema_50", 0)
        ema_200 = indicators.get("ema_200", 0)
        atr = indicators.get("atr_14", 0)
        adx = indicators.get("adx_14", indicators.get("adx", 0))

        if close <= 0 or ema_20 <= 0 or ema_50 <= 0 or ema_200 <= 0:
            return None
        if prev_indicators is None:
            return None

        # ATR minimum volatility filter (was missing from v5_tuned)
        if atr > 0 and close > 0:
            atr_pct = atr / close
            if atr_pct < 0.008:
                return None

        # ADX trend strength filter (was missing from v5_tuned)
        if adx > 0 and adx < 20:
            return None

        # EMA gap filter (was missing from v5_tuned)
        ema_gap_pct = abs(ema_20 - ema_50) / ema_50 if ema_50 > 0 else 0
        if ema_gap_pct < 0.001:
            return None

        prev_20 = prev_indicators.get("ema_20", 0)
        prev_50 = prev_indicators.get("ema_50", 0)
        if prev_20 <= 0 or prev_50 <= 0:
            return None

        if close <= ema_200:
            return None

        if prev_20 <= prev_50 and ema_20 > ema_50:
            return Signal(
                strategy=self.meta.name,
                asset=asset,
                direction="LONG",
                sl_pct=self.meta.sl_pct,
                tp_pct=self.meta.tp_pct,
                max_hold_bars=self.meta.max_hold_bars,
                quality=0.7,
                reason=f"EMA20x50 golden cross, bull regime tuned ({asset})",
                signal_id=f"{self.meta.name}:{asset}:{candles[-1].get('datetime', '') if candles else ''}",
            )
        return None
