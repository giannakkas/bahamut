"""
Bahamut v8 — Range Strategy

Mean reversion in sideways markets:
  - Long near lower Bollinger Band
  - Short near upper Bollinger Band
  - Target: mid-band (EMA20)
  - Tighter SL, smaller TP, shorter hold than v5

Only active when regime == RANGE.
"""
from typing import Optional
from bahamut.strategies.base import BaseStrategy, StrategyMeta, Signal


class V8Range(BaseStrategy):
    meta = StrategyMeta(
        name="v8_range",
        version="8.0",
        description="Bollinger Band mean reversion, RANGE regime only",
        sl_pct=0.04,       # 4% SL (tighter than v5)
        tp_pct=0.06,       # 6% TP (smaller target — revert to mean)
        max_hold_bars=15,   # 2.5 days max (shorter hold)
        risk_pct=0.015,     # 1.5% risk (smaller than v5's 2%)
    )

    def evaluate(self, candles: list, indicators: dict,
                 prev_indicators: dict = None) -> Optional[Signal]:
        close = indicators.get("close", 0)
        bb_upper = indicators.get("bollinger_upper", 0)
        bb_lower = indicators.get("bollinger_lower", 0)
        bb_mid = indicators.get("bollinger_mid", close)
        rsi = indicators.get("rsi_14", 50)
        ema_200 = indicators.get("ema_200", 0)
        atr = indicators.get("atr_14", 0)

        if close <= 0 or bb_upper <= 0 or bb_lower <= 0 or atr <= 0:
            return None

        bb_width = (bb_upper - bb_lower) / close if close > 0 else 0

        # Don't trade if bands are very wide (volatile, not ranging)
        if bb_width > 0.12:
            return None

        # Don't trade if bands are extremely narrow (about to break out)
        if bb_width < 0.02:
            return None

        # Candle context
        if not candles or len(candles) < 3:
            return None
        curr = candles[-1]

        # ── LONG: price near lower band, RSI oversold-ish ──
        lower_dist = (close - bb_lower) / atr if atr > 0 else 999
        if lower_dist < 0.5 and rsi < 40:
            # Confirm: bullish close (bounce signal)
            if curr["close"] > curr["open"]:
                return Signal(
                    strategy=self.meta.name,
                    asset="BTCUSD",
                    direction="LONG",
                    sl_pct=self.meta.sl_pct,
                    tp_pct=self.meta.tp_pct,
                    max_hold_bars=self.meta.max_hold_bars,
                    quality=min(1.0, 0.5 + (40 - rsi) * 0.01 + max(0, -lower_dist) * 0.1),
                    reason=f"BB lower touch, RSI={rsi:.0f}, range mean-reversion",
                )

        # ── SHORT: price near upper band, RSI overbought-ish ──
        upper_dist = (bb_upper - close) / atr if atr > 0 else 999
        if upper_dist < 0.5 and rsi > 60:
            # Confirm: bearish close
            if curr["close"] < curr["open"]:
                return Signal(
                    strategy=self.meta.name,
                    asset="BTCUSD",
                    direction="SHORT",
                    sl_pct=self.meta.sl_pct,
                    tp_pct=self.meta.tp_pct,
                    max_hold_bars=self.meta.max_hold_bars,
                    quality=min(1.0, 0.5 + (rsi - 60) * 0.01 + max(0, -upper_dist) * 0.1),
                    reason=f"BB upper touch, RSI={rsi:.0f}, range mean-reversion",
                )

        return None
