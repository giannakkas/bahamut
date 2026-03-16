"""
Feature Engineering Service
Computes technical indicators from raw OHLCV candle data.
"""
import numpy as np
import structlog

logger = structlog.get_logger()


def compute_indicators(candles: list[dict]) -> dict:
    """
    Compute all technical indicators from OHLCV candle data.
    Returns a flat dict of indicator values based on the most recent candles.
    Requires at least 200 candles for EMA-200.
    """
    if len(candles) < 50:
        logger.warning("insufficient_candles", count=len(candles))
        return {}

    closes = np.array([c["close"] for c in candles], dtype=float)
    highs = np.array([c["high"] for c in candles], dtype=float)
    lows = np.array([c["low"] for c in candles], dtype=float)
    volumes = np.array([c.get("volume", 0) for c in candles], dtype=float)

    result = {
        "close": closes[-1],
        "open": candles[-1]["open"],
        "high": highs[-1],
        "low": lows[-1],
        "volume": volumes[-1],
    }

    # ── RSI (14) ──
    result["rsi_14"] = _rsi(closes, 14)

    # ── MACD (12, 26, 9) ──
    macd_line, signal_line, histogram = _macd(closes, 12, 26, 9)
    result["macd_line"] = macd_line
    result["macd_signal"] = signal_line
    result["macd_histogram"] = histogram

    # ── EMAs ──
    result["ema_20"] = _ema(closes, 20)
    result["ema_50"] = _ema(closes, 50)
    if len(closes) >= 200:
        result["ema_200"] = _ema(closes, 200)
    else:
        result["ema_200"] = _ema(closes, len(closes) - 1) if len(closes) > 1 else closes[-1]

    # ── ATR (14) ──
    result["atr_14"] = _atr(highs, lows, closes, 14)

    # ── Bollinger Bands (20, 2) ──
    bb_upper, bb_lower, bb_mid = _bollinger(closes, 20, 2)
    result["bollinger_upper"] = bb_upper
    result["bollinger_lower"] = bb_lower
    result["bollinger_mid"] = bb_mid

    # ── ADX (14) ──
    result["adx_14"] = _adx(highs, lows, closes, 14)

    # ── Stochastic (14, 3) ──
    stoch_k, stoch_d = _stochastic(highs, lows, closes, 14, 3)
    result["stoch_k"] = stoch_k
    result["stoch_d"] = stoch_d

    # ── Volume SMA (20) ──
    if len(volumes) >= 20:
        result["volume_sma_20"] = float(np.mean(volumes[-20:]))
    else:
        result["volume_sma_20"] = float(np.mean(volumes))

    # ── Realized Volatility (20-period) ──
    if len(closes) >= 21:
        returns = np.diff(np.log(closes[-21:]))
        result["realized_vol_20"] = float(np.std(returns) * np.sqrt(252))
    else:
        result["realized_vol_20"] = 0.0

    logger.info("indicators_computed", close=result["close"],
                rsi=round(result["rsi_14"], 1), atr=round(result["atr_14"], 6))

    return result


def _ema(data: np.ndarray, period: int) -> float:
    """Exponential Moving Average."""
    if len(data) < period:
        return float(data[-1])
    multiplier = 2 / (period + 1)
    ema = float(data[0])
    for price in data[1:]:
        ema = (price - ema) * multiplier + ema
    return round(ema, 8)


def _rsi(closes: np.ndarray, period: int = 14) -> float:
    """Relative Strength Index."""
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 4)


def _macd(closes: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD line, signal line, histogram."""
    ema_fast = _ema_series(closes, fast)
    ema_slow = _ema_series(closes, slow)
    macd_line = ema_fast - ema_slow
    signal_line_arr = _ema_series(macd_line, signal)

    return (
        round(float(macd_line[-1]), 8),
        round(float(signal_line_arr[-1]), 8),
        round(float(macd_line[-1] - signal_line_arr[-1]), 8),
    )


def _ema_series(data: np.ndarray, period: int) -> np.ndarray:
    """EMA as a full series."""
    result = np.zeros_like(data)
    multiplier = 2 / (period + 1)
    result[0] = data[0]
    for i in range(1, len(data)):
        result[i] = (data[i] - result[i - 1]) * multiplier + result[i - 1]
    return result


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    """Average True Range."""
    if len(closes) < period + 1:
        return float(np.mean(highs - lows))

    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1])
        )
    )

    atr = float(np.mean(tr[:period]))
    for i in range(period, len(tr)):
        atr = (atr * (period - 1) + tr[i]) / period
    return round(atr, 8)


def _bollinger(closes: np.ndarray, period: int = 20, std_dev: float = 2.0):
    """Bollinger Bands (upper, lower, mid)."""
    if len(closes) < period:
        mid = float(closes[-1])
        return mid, mid, mid

    sma = float(np.mean(closes[-period:]))
    std = float(np.std(closes[-period:]))
    return (
        round(sma + std_dev * std, 8),
        round(sma - std_dev * std, 8),
        round(sma, 8),
    )


def _adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    """Average Directional Index."""
    if len(closes) < period * 2:
        return 20.0  # default weak trend

    plus_dm = np.zeros(len(highs))
    minus_dm = np.zeros(len(highs))

    for i in range(1, len(highs)):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm[i] = up if (up > down and up > 0) else 0
        minus_dm[i] = down if (down > up and down > 0) else 0

    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1])
        )
    )

    # Smoothed TR and DMs
    atr_s = float(np.mean(tr[:period]))
    plus_dm_s = float(np.mean(plus_dm[1:period + 1]))
    minus_dm_s = float(np.mean(minus_dm[1:period + 1]))

    for i in range(period, len(tr)):
        atr_s = (atr_s * (period - 1) + tr[i]) / period
        plus_dm_s = (plus_dm_s * (period - 1) + plus_dm[i + 1]) / period
        minus_dm_s = (minus_dm_s * (period - 1) + minus_dm[i + 1]) / period

    if atr_s == 0:
        return 20.0

    plus_di = 100 * plus_dm_s / atr_s
    minus_di = 100 * minus_dm_s / atr_s

    if plus_di + minus_di == 0:
        return 20.0

    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    return round(dx, 4)


def _stochastic(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
                k_period: int = 14, d_period: int = 3):
    """Stochastic %K and %D."""
    if len(closes) < k_period:
        return 50.0, 50.0

    k_values = []
    for i in range(k_period - 1, len(closes)):
        h = np.max(highs[i - k_period + 1:i + 1])
        l = np.min(lows[i - k_period + 1:i + 1])
        if h == l:
            k_values.append(50.0)
        else:
            k_values.append(100 * (closes[i] - l) / (h - l))

    k = k_values[-1]
    d = float(np.mean(k_values[-d_period:])) if len(k_values) >= d_period else k

    return round(k, 4), round(d, 4)
