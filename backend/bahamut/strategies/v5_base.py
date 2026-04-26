"""
v5_base — EMA20×50 cross strategy with regime-aware direction.

LONG: Golden cross (EMA20 crosses above EMA50) within last 3 bars, bull regime (above EMA200)
SHORT: Death cross (EMA20 crosses below EMA50) within last 3 bars, bear regime (below EMA200)

Signal window: fires on the cross bar AND 2 subsequent bars. This gives a ~45-minute
detection window (3 × 15min bars) instead of a single 15-minute bar, preventing signal
loss from the 10-min cycle / 15-min bar phasing mismatch.

Dedup: signal_id is keyed on the cross bar timestamp, so the same cross produces at most
one trade even though evaluate() fires on bars t, t+1, t+2.

Dynamic SL/TP by timeframe. Multi-confirmation quality scoring.
"""
from typing import Optional
import numpy as np
from bahamut.strategies.base import BaseStrategy, StrategyMeta, Signal


# Cross detection lookback: fire signal if cross occurred within this many bars
_CROSS_WINDOW = 3


def _ema_series(data: np.ndarray, period: int) -> np.ndarray:
    """Compute full EMA series — matches bahamut.features.indicators._ema exactly.

    Canonical implementation seeds with data[0] and applies multiplier
    from data[1] onwards. This must produce identical values to _ema()
    so that cross detection here agrees with ema_20/ema_50 in indicators.
    """
    if len(data) < period:
        return np.full(len(data), np.nan)
    result = np.empty(len(data))
    k = 2.0 / (period + 1)
    result[0] = float(data[0])
    for i in range(1, len(data)):
        result[i] = (float(data[i]) - result[i - 1]) * k + result[i - 1]
    return result


def _find_recent_cross(closes: np.ndarray, window: int = _CROSS_WINDOW) -> dict | None:
    """Find the most recent EMA20×50 crossover within `window` bars.

    Returns dict with cross direction, bars_ago, and cross_bar_index,
    or None if no cross found in the window.

    A LONG cross occurs when EMA20 was <= EMA50 on bar[i-1] and > EMA50 on bar[i].
    A SHORT cross occurs when EMA20 was >= EMA50 on bar[i-1] and < EMA50 on bar[i].
    """
    if len(closes) < 55:  # Need 50+ bars for EMA50 to seed
        return None

    ema20 = _ema_series(closes, 20)
    ema50 = _ema_series(closes, 50)

    # Scan last `window` bars (most recent first)
    for bars_ago in range(window):
        idx = len(closes) - 1 - bars_ago
        prev_idx = idx - 1
        if prev_idx < 50 or np.isnan(ema20[idx]) or np.isnan(ema50[idx]):
            continue
        if np.isnan(ema20[prev_idx]) or np.isnan(ema50[prev_idx]):
            continue

        # LONG cross: prev EMA20 <= EMA50, current EMA20 > EMA50
        if ema20[prev_idx] <= ema50[prev_idx] and ema20[idx] > ema50[idx]:
            return {
                "direction": "LONG",
                "bars_ago": bars_ago,
                "cross_bar_index": idx,
                "ema20_at_cross": float(ema20[idx]),
                "ema50_at_cross": float(ema50[idx]),
            }

        # SHORT cross: prev EMA20 >= EMA50, current EMA20 < EMA50
        if ema20[prev_idx] >= ema50[prev_idx] and ema20[idx] < ema50[idx]:
            return {
                "direction": "SHORT",
                "bars_ago": bars_ago,
                "cross_bar_index": idx,
                "ema20_at_cross": float(ema20[idx]),
                "ema50_at_cross": float(ema50[idx]),
            }

    return None


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

        # Block signals on degraded EMA-200 — v5 relies on EMA-200 trend filter
        if indicators.get("_ema200_degraded"):
            import structlog
            structlog.get_logger().debug("strategy_blocked_ema200_degraded",
                                         strategy="v5_base", asset=asset)
            return None

        close = indicators.get("close", 0)
        ema_20 = indicators.get("ema_20", 0)
        ema_50 = indicators.get("ema_50", 0)
        ema_200 = indicators.get("ema_200", 0)
        atr = indicators.get("atr_14", 0)
        adx = indicators.get("adx_14", indicators.get("adx", 0))

        if close <= 0 or ema_20 <= 0 or ema_50 <= 0 or ema_200 <= 0:
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

        interval = indicators.get("_interval", "4h")
        params = self.SL_TP_BY_INTERVAL.get(interval, self.SL_TP_BY_INTERVAL["4h"])
        bar_ts = candles[-1].get("datetime", "") if candles else ""

        # ═══════════════════════════════════════════
        # WINDOWED CROSS DETECTION
        # Scan last 3 bars for an EMA20×50 crossover. This gives a ~45min
        # detection window instead of exactly 1 bar (15min), preventing
        # signal loss from the 10min-cycle / 15min-bar phasing mismatch.
        # ═══════════════════════════════════════════
        closes = np.array([c.get("close", 0) for c in candles], dtype=float)
        cross = _find_recent_cross(closes, window=_CROSS_WINDOW)

        if cross is None:
            return None

        # Use the cross bar's timestamp for signal_id — ensures dedup:
        # the same cross produces at most one trade across bars t, t+1, t+2.
        cross_bar_ts = candles[cross["cross_bar_index"]].get("datetime", bar_ts)

        # ═══════════════════════════════════════════
        # LONG: Golden cross in bull regime
        # ═══════════════════════════════════════════
        if cross["direction"] == "LONG" and close > ema_200:
            quality = self._score_quality(indicators, direction="LONG")
            confirmations = self._get_confirmations(indicators, direction="LONG")

            reason = f"EMA20x50 golden cross ({cross['bars_ago']}b ago), bull regime ({asset})"
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
                signal_id=f"{self.meta.name}:{asset}:L:{cross_bar_ts}",
            )

        # ═══════════════════════════════════════════
        # SHORT: Death cross in bear regime
        # ═══════════════════════════════════════════
        if cross["direction"] == "SHORT" and close < ema_200:
            quality = self._score_quality(indicators, direction="SHORT")
            confirmations = self._get_confirmations(indicators, direction="SHORT")

            reason = f"EMA20x50 death cross ({cross['bars_ago']}b ago), bear regime ({asset})"
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
                signal_id=f"{self.meta.name}:{asset}:S:{cross_bar_ts}",
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
