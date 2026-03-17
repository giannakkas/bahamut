"""
Live Market Data Service
Fetches real data from Twelve Data (primary) or OANDA (fallback).
Computes technical indicators and provides features to agents.
"""
import time
import structlog

from bahamut.ingestion.adapters.twelvedata import (
    twelve_data, to_twelve_symbol, to_twelve_interval
)
from bahamut.ingestion.adapters.oanda import (
    oanda, to_oanda_instrument, to_oanda_granularity
)
from bahamut.features.indicators import compute_indicators

logger = structlog.get_logger()

_cache: dict[str, dict] = {}
_cache_ts: dict[str, float] = {}
CACHE_TTL = 60  # 1 minute — Grow plan has unlimited daily credits


class MarketDataService:

    async def get_features_for_asset(self, symbol: str, timeframe: str = "4H") -> dict:
        cache_key = f"{symbol}:{timeframe}"
        now = time.time()
        if cache_key in _cache and (now - _cache_ts.get(cache_key, 0)) < CACHE_TTL:
            return _cache[cache_key]

        # Try Twelve Data first (easiest free API)
        if twelve_data.configured:
            features = await self._fetch_from_twelvedata(symbol, timeframe)
            if features:
                _cache[cache_key] = features
                _cache_ts[cache_key] = now
                return features

        # Try OANDA as fallback
        if oanda.configured:
            features = await self._fetch_from_oanda(symbol, timeframe)
            if features:
                _cache[cache_key] = features
                _cache_ts[cache_key] = now
                return features

        # Demo fallback
        logger.info("no_data_source_using_demo", symbol=symbol)
        return self._demo_features(symbol)

    async def _fetch_from_twelvedata(self, symbol: str, timeframe: str) -> dict | None:
        try:
            td_symbol = to_twelve_symbol(symbol)
            td_interval = to_twelve_interval(timeframe)

            candles = await twelve_data.get_candles(td_symbol, td_interval, count=200)
            if not candles or len(candles) < 20:
                return None

            indicators = compute_indicators(candles)
            if not indicators:
                return None

            price = await twelve_data.get_latest_price(td_symbol)

            features = {
                "indicators": indicators,
                "ohlcv": {
                    "open": candles[-1]["open"], "high": candles[-1]["high"],
                    "low": candles[-1]["low"], "close": candles[-1]["close"],
                    "volume": candles[-1].get("volume", 0),
                },
                "candles": candles[-30:],  # Last 30 candles for whale/volume analysis
                "price": price or {},
                "candle_count": len(candles),
                "source": "twelvedata_live",
                "symbol": symbol,
                "timeframe": timeframe,
            }

            logger.info("twelvedata_features_ready", symbol=symbol, tf=timeframe,
                        close=indicators.get("close"), rsi=round(indicators.get("rsi_14", 0), 1))
            return features

        except Exception as e:
            logger.error("twelvedata_fetch_failed", symbol=symbol, error=str(e))
            return None

    async def _fetch_from_oanda(self, symbol: str, timeframe: str) -> dict | None:
        try:
            instrument = to_oanda_instrument(symbol)
            granularity = to_oanda_granularity(timeframe)

            candles = await oanda.get_candles(instrument, granularity, count=200)
            if not candles or len(candles) < 20:
                return None

            indicators = compute_indicators(candles)
            if not indicators:
                return None

            price = await oanda.get_latest_price(instrument)

            features = {
                "indicators": indicators,
                "ohlcv": {
                    "open": candles[-1]["open"], "high": candles[-1]["high"],
                    "low": candles[-1]["low"], "close": candles[-1]["close"],
                    "volume": candles[-1].get("volume", 0),
                },
                "candles": candles[-30:],
                "price": price or {},
                "candle_count": len(candles),
                "source": "oanda_live",
                "symbol": symbol,
                "timeframe": timeframe,
            }

            logger.info("oanda_features_ready", symbol=symbol, tf=timeframe,
                        close=indicators.get("close"))
            return features

        except Exception as e:
            logger.error("oanda_fetch_failed", symbol=symbol, error=str(e))
            return None

    async def get_account_state(self) -> dict:
        if oanda.configured:
            summary = await oanda.get_account_summary()
            if summary:
                return {
                    "equity": summary["equity"],
                    "balance": summary["balance"],
                    "open_trade_count": summary["open_trade_count"],
                    "net_exposure_pct": summary["margin_used"] / max(summary["equity"], 1),
                    "max_correlation": 0.35,
                    "drawdown": {"daily": 0, "weekly": 0},
                }
        return self._demo_portfolio()

    def _demo_features(self, symbol: str) -> dict:
        demo = {
            "EURUSD": {"close": 1.0855, "rsi": 62.5, "macd_hist": 0.00023, "adx": 28.3,
                       "ema_20": 1.0842, "ema_50": 1.0815, "ema_200": 1.0780, "atr": 0.0045, "stoch_k": 72.1},
            "XAUUSD": {"close": 2645.30, "rsi": 58.2, "macd_hist": 1.25, "adx": 22.1,
                       "ema_20": 2640.50, "ema_50": 2625.80, "ema_200": 2580.00, "atr": 18.5, "stoch_k": 65.3},
            "GBPUSD": {"close": 1.2715, "rsi": 55.8, "macd_hist": 0.00015, "adx": 19.8,
                       "ema_20": 1.2700, "ema_50": 1.2685, "ema_200": 1.2650, "atr": 0.0055, "stoch_k": 58.2},
            "USDJPY": {"close": 149.85, "rsi": 48.3, "macd_hist": -0.045, "adx": 24.5,
                       "ema_20": 150.10, "ema_50": 150.50, "ema_200": 148.90, "atr": 0.65, "stoch_k": 42.1},
            "BTCUSD": {"close": 87250.00, "rsi": 54.2, "macd_hist": 125.0, "adx": 26.5,
                       "ema_20": 86800, "ema_50": 85500, "ema_200": 78000, "atr": 1250, "stoch_k": 55.3},
            "ETHUSD": {"close": 2280.50, "rsi": 51.8, "macd_hist": 8.5, "adx": 21.3,
                       "ema_20": 2260, "ema_50": 2210, "ema_200": 2050, "atr": 65, "stoch_k": 48.7},
            "AAPL": {"close": 228.50, "rsi": 58.7, "macd_hist": 0.85, "adx": 25.1,
                     "ema_20": 226.80, "ema_50": 223.50, "ema_200": 215.00, "atr": 3.2, "stoch_k": 62.4},
            "TSLA": {"close": 265.30, "rsi": 62.1, "macd_hist": 2.15, "adx": 31.8,
                     "ema_20": 258.50, "ema_50": 248.00, "ema_200": 220.00, "atr": 8.5, "stoch_k": 71.2},
            "NVDA": {"close": 138.75, "rsi": 55.4, "macd_hist": 1.20, "adx": 23.9,
                     "ema_20": 136.50, "ema_50": 132.00, "ema_200": 118.00, "atr": 4.1, "stoch_k": 57.8},
            "META": {"close": 612.40, "rsi": 57.9, "macd_hist": 3.50, "adx": 27.4,
                     "ema_20": 605.00, "ema_50": 590.00, "ema_200": 540.00, "atr": 12.5, "stoch_k": 60.1},
        }
        d = demo.get(symbol, demo["EURUSD"])
        return {
            "indicators": {
                "close": d["close"], "open": d["close"] * 0.999,
                "high": d["close"] * 1.002, "low": d["close"] * 0.998,
                "rsi_14": d["rsi"], "macd_histogram": d["macd_hist"],
                "adx_14": d["adx"], "ema_20": d["ema_20"],
                "ema_50": d["ema_50"], "ema_200": d["ema_200"],
                "atr_14": d["atr"], "stoch_k": d["stoch_k"],
                "volume": 45000, "stoch_d": d["stoch_k"] - 3,
                "macd_line": d["macd_hist"] * 2, "macd_signal": d["macd_hist"],
                "bollinger_upper": d["close"] + d["atr"] * 2,
                "bollinger_lower": d["close"] - d["atr"] * 2,
                "realized_vol_20": 0.12,
            },
            "ohlcv": {"open": d["close"] * 0.999, "high": d["close"] * 1.002,
                      "low": d["close"] * 0.998, "close": d["close"], "volume": 45000},
            "source": "demo", "symbol": symbol, "timeframe": "4H",
        }

    def _demo_portfolio(self) -> dict:
        return {"equity": 124350, "balance": 123100, "open_trade_count": 2,
                "net_exposure_pct": 0.04, "max_correlation": 0.35,
                "drawdown": {"daily": 0.005, "weekly": 0.012}}


market_data = MarketDataService()


async def get_current_prices() -> dict[str, float]:
    """
    Fetch current prices for all monitored assets.
    Returns: {"EURUSD": 1.0850, "BTCUSD": 67500.0, ...}
    Used by paper trading engine to check SL/TP.
    """
    from bahamut.ingestion.adapters.twelvedata import twelve_data, to_twelve_symbol

    assets = [
        "EURUSD", "GBPUSD", "USDJPY", "XAUUSD",
        "BTCUSD", "ETHUSD",
        "AAPL", "TSLA", "NVDA", "META",
    ]

    prices = {}
    for asset in assets:
        try:
            td_symbol = to_twelve_symbol(asset)
            result = await twelve_data.get_latest_price(td_symbol)
            if result and result.get("mid"):
                prices[asset] = result["mid"]
        except Exception:
            continue

    return prices
