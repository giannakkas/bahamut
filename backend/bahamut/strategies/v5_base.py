"""
v5_base — EMA20×50 cross strategy with regime-aware direction.

LONG: Golden cross (EMA20 crosses above EMA50) in bull regime (above EMA200)
SHORT: Death cross (EMA20 crosses below EMA50) in bear regime (below EMA200)

Dynamic SL/TP by timeframe. Multi-confirmation quality scoring.
"""
from typing import Optional
from bahamut.strategies.base import BaseStrategy, StrategyMeta, Signal


class V5Base(BaseStrategy):
    meta = StrategyMeta(
        name="v5_base",
        version="5.2",
        description="EMA20x50 cross, regime-aware LONG+SHORT, dynamic SL/TP",
        sl_pct=0.03,       # Default (overridden dynamically in evaluate)
        tp_pct=0.06,
        max_hold_bars=20,
        risk_pct=0.02,
    )

    # Expose for debug exploration path (getattr fallback)
    sl_pct = 0.025       # 15m default — overridden per trade
    tp_pct = 0.05
    max_hold = 20

    # Timeframe-proportional SL/TP targets
    SL_TP_BY_INTERVAL = {
        "15m": {"sl": 0.025, "tp": 0.05, "hold": 20},
        "5m":  {"sl": 0.015, "tp": 0.03, "hold": 20},
        "1h":  {"sl": 0.03,  "tp": 0.06, "hold": 20},
        "4h":  {"sl": 0.035, "tp": 0.07, "hold": 30},
    }

    def evaluate(self, candles: list, indicators: dict,
                 prev_indicators: dict = None, asset: str = "BTCUSD") -> Optional[Signal]:
        # Canonical suppress check
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

        # ATR minimum volatility filter — skip low-vol assets
        if atr > 0 and close > 0:
            atr_pct = atr / close
            if atr_pct < 0.008:  # 0.8% minimum ATR required
                return None

        # ADX trend strength filter — skip weak/choppy trends
        if adx > 0 and adx < 20:
            return None

        # EMA gap filter — require meaningful separation after cross
        ema_gap_pct = abs(ema_20 - ema_50) / ema_50 if ema_50 > 0 else 0
        if ema_gap_pct < 0.001:  # 0.1% minimum gap
            return None

        prev_20 = prev_indicators.get("ema_20", 0)
        prev_50 = prev_indicators.get("ema_50", 0)
        if prev_20 <= 0 or prev_50 <= 0:
            return None

        interval = indicators.get("_interval", "4h")
        params = self.SL_TP_BY_INTERVAL.get(interval, self.SL_TP_BY_INTERVAL["4h"])
        bar_ts = candles[-1].get("datetime", "") if candles else ""

        # ═══════════════════════════════════════════
        # LONG: Golden cross in bull regime
        # ═══════════════════════════════════════════
        if close > ema_200 and prev_20 <= prev_50 and ema_20 > ema_50:
            quality = self._score_quality(indicators, direction="LONG")
            confirmations = self._get_confirmations(indicators, direction="LONG")

            reason = f"EMA20x50 golden cross, bull regime ({asset})"
            if confirmations:
                reason += f" [{'+'.join(confirmations)}]"

            return Signal(
                strategy=self.meta.name,
                asset=asset,
                direction="LONG",
                sl_pct=params["sl"],
                tp_pct=params["tp"],
                max_hold_bars=params["hold"],
                quality=quality,
                reason=reason,
                signal_id=f"{self.meta.name}:{asset}:L:{bar_ts}",
            )

        # ═══════════════════════════════════════════
        # SHORT: Death cross in bear regime
        # ═══════════════════════════════════════════
        if close < ema_200 and prev_20 >= prev_50 and ema_20 < ema_50:
            quality = self._score_quality(indicators, direction="SHORT")
            confirmations = self._get_confirmations(indicators, direction="SHORT")

            reason = f"EMA20x50 death cross, bear regime ({asset})"
            if confirmations:
                reason += f" [{'+'.join(confirmations)}]"

            return Signal(
                strategy=self.meta.name,
                asset=asset,
                direction="SHORT",
                sl_pct=params["sl"],
                tp_pct=params["tp"],
                max_hold_bars=params["hold"],
                quality=quality,
                reason=reason,
                signal_id=f"{self.meta.name}:{asset}:S:{bar_ts}",
            )

        return None

    @staticmethod
    def _score_quality(indicators: dict, direction: str = "LONG") -> float:
        """Graduated quality score based on multi-confirmation."""
        quality = 0.5  # base for cross + regime

        volume = indicators.get("volume", 0)
        vol_sma = indicators.get("volume_sma_20", 0)
        macd_hist = indicators.get("macd_histogram", 0)
        rsi = indicators.get("rsi_14", 50)
        ema_20 = indicators.get("ema_20", 0)
        ema_50 = indicators.get("ema_50", 0)
        ema_200 = indicators.get("ema_200", 0)

        # Volume expansion
        if volume > 0 and vol_sma > 0 and volume > vol_sma * 1.3:
            quality += 0.1

        if direction == "LONG":
            if macd_hist > 0:
                quality += 0.1
            if 40 < rsi < 70:
                quality += 0.05
            if ema_20 > ema_50 > ema_200 > 0:
                quality += 0.05
        else:  # SHORT
            if macd_hist < 0:
                quality += 0.1
            if 30 < rsi < 60:
                quality += 0.05
            if 0 < ema_20 < ema_50 < ema_200:
                quality += 0.05

        return round(min(1.0, quality), 3)

    @staticmethod
    def _get_confirmations(indicators: dict, direction: str = "LONG") -> list[str]:
        """Return list of active confirmation labels."""
        confs = []
        volume = indicators.get("volume", 0)
        vol_sma = indicators.get("volume_sma_20", 0)
        macd_hist = indicators.get("macd_histogram", 0)

        if volume > 0 and vol_sma > 0 and volume > vol_sma * 1.3:
            confs.append("vol_expand")
        if direction == "LONG" and macd_hist > 0:
            confs.append("macd_pos")
        elif direction == "SHORT" and macd_hist < 0:
            confs.append("macd_neg")
        return confs
