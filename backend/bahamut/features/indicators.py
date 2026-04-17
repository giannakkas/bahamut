"""
Feature Engineering Service
Computes technical indicators from raw OHLCV candle data.

CANONICAL indicator engine — used by all asset classes (crypto via
bahamut.data.binance_data wrapper, stocks directly). There is ONE math
implementation here so values are reproducible and asset-class-agnostic.

Indicators implemented:
  - EMA (recursive, exact)
  - RSI (Wilder smoothing)
  - ATR (Wilder smoothing)
  - ADX (Wilder-smoothed +DI/-DI then DX, default 20 when insufficient data)
  - Bollinger Bands (20, 2σ, population std)
  - MACD (12/26/9)
  - Stochastic (14, 3)
  - Volume SMA
  - Realized volatility (log-returns, annualized √252)

Every returned dict carries indicator_engine_version and indicator_source
so diagnostics can prove which math produced a given snapshot.
"""
import numpy as np
import structlog

logger = structlog.get_logger()

# Bump on any math change — downstream caches can key on this.
INDICATOR_ENGINE_VERSION = "v2.1-canonical-2026-04-17"

# Annualization factors: periods per year for realized volatility
_ANNUAL_FACTORS = {
    "1m": 525600, "5m": 105120, "15m": 35040, "30m": 17520,
    "1h": 8760, "2h": 4380, "4h": 2190, "6h": 1460,
    "8h": 1095, "12h": 730, "1d": 252,
}


def compute_indicators(candles: list[dict], interval: str = "4h") -> dict:
    """
    Compute all technical indicators from OHLCV candle data.
    Returns a flat dict of indicator values based on the most recent candles.
    Requires at least 200 candles for EMA-200.

    HARD INVARIANT: the last candle must be closed. If it has is_closed=False,
    we drop it before computing indicators. This prevents strategies from
    acting on in-progress bars. Legacy lists without is_closed field are
    assumed closed (backward-compatible).
    """
    if len(candles) < 20:
        logger.warning("insufficient_candles", count=len(candles))
        return {}

    # Closed-candle invariant
    if candles and candles[-1].get("is_closed") is False:
        logger.warning("features_indicators_dropping_forming_candle",
                       datetime=candles[-1].get("datetime", ""),
                       source=candles[-1].get("source", "unknown"))
        candles = candles[:-1]
        if len(candles) < 20:
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
        result["_ema200_degraded"] = False
    else:
        result["ema_200"] = _ema(closes, len(closes) - 1) if len(closes) > 1 else closes[-1]
        result["_ema200_degraded"] = True
        logger.warning("ema200_degraded", candles=len(closes),
                        effective_period=len(closes) - 1,
                        msg="EMA-200 using shorter period — values may be unreliable")

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
        ann_factor = _ANNUAL_FACTORS.get(interval, 252)
        result["realized_vol_20"] = float(np.std(returns) * np.sqrt(ann_factor))
    else:
        result["realized_vol_20"] = 0.0

    # Provenance — every caller can see which engine + version produced these.
    result["indicator_engine_version"] = INDICATOR_ENGINE_VERSION
    result["indicator_source"] = "canonical"

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
    std = float(np.std(closes[-period:], ddof=1))  # sample std (N-1), standard for Bollinger
    return (
        round(sma + std_dev * std, 8),
        round(sma - std_dev * std, 8),
        round(sma, 8),
    )


def _adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    """Average Directional Index — TRUE Wilder-smoothed ADX.

    Computes +DM/-DM → Wilder smooth → +DI/-DI → DX → Wilder smooth DX → ADX.
    Previous implementation returned a single unsmoothed DX value (not ADX).
    """
    n = len(closes)
    if n < period * 2 + 1:
        return 20.0  # default weak trend

    # Step 1: +DM and -DM
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)

    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm[i] = up if (up > down and up > 0) else 0
        minus_dm[i] = down if (down > up and down > 0) else 0

    # Step 2: True Range
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1])
        )
    )

    # Step 3: Wilder-smooth TR, +DM, -DM (first value = sum of first `period`)
    atr_s = float(np.sum(tr[:period]))
    pdm_s = float(np.sum(plus_dm[1:period + 1]))
    mdm_s = float(np.sum(minus_dm[1:period + 1]))

    # Build DX series for ADX smoothing
    dx_values = []

    for i in range(period, len(tr)):
        # Wilder smoothing: prev - (prev/period) + current
        atr_s = atr_s - (atr_s / period) + tr[i]
        pdm_s = pdm_s - (pdm_s / period) + plus_dm[i + 1]
        mdm_s = mdm_s - (mdm_s / period) + minus_dm[i + 1]

        if atr_s == 0:
            dx_values.append(0.0)
            continue

        plus_di = 100 * pdm_s / atr_s
        minus_di = 100 * mdm_s / atr_s
        di_sum = plus_di + minus_di

        if di_sum == 0:
            dx_values.append(0.0)
        else:
            dx_values.append(100 * abs(plus_di - minus_di) / di_sum)

    if len(dx_values) < period:
        return round(dx_values[-1], 4) if dx_values else 20.0

    # Step 4: Wilder-smooth the DX series to get ADX
    adx = float(np.mean(dx_values[:period]))  # First ADX = mean of first `period` DX values
    for i in range(period, len(dx_values)):
        adx = (adx * (period - 1) + dx_values[i]) / period

    return round(adx, 4)


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
