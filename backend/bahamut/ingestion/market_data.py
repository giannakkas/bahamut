"""
Live Market Data Service
Central service that fetches real data from OANDA and computes features.
Used by the agent orchestrator to feed real data to agents.
"""
import asyncio
import structlog
from typing import Optional

from bahamut.ingestion.adapters.oanda import (
    oanda, to_oanda_instrument, to_oanda_granularity, SYMBOL_MAP
)
from bahamut.features.indicators import compute_indicators

logger = structlog.get_logger()

# Cache for latest data to avoid redundant API calls within same cycle
_cache: dict[str, dict] = {}
_cache_ts: dict[str, float] = {}
CACHE_TTL = 30  # seconds


class MarketDataService:
    """Provides real market data and computed features for agents."""

    async def get_features_for_asset(self, symbol: str, timeframe: str = "4H") -> dict:
        """
        Fetch candles from OANDA and compute indicators.
        Returns a features dict ready for agent consumption.
        Falls back to demo data if OANDA is not configured.
        """
        cache_key = f"{symbol}:{timeframe}"

        # Check cache
        import time
        now = time.time()
        if cache_key in _cache and (now - _cache_ts.get(cache_key, 0)) < CACHE_TTL:
            return _cache[cache_key]

        if not oanda.configured:
            logger.info("oanda_not_configured_using_demo", symbol=symbol)
            return self._demo_features(symbol)

        try:
            instrument = to_oanda_instrument(symbol)
            granularity = to_oanda_granularity(timeframe)

            # Fetch 200 candles for indicator computation
            candles = await oanda.get_candles(
                instrument=instrument,
                granularity=granularity,
                count=200,
            )

            if not candles:
                logger.warning("no_candles_returned", symbol=symbol, tf=timeframe)
                return self._demo_features(symbol)

            # Compute indicators
            indicators = compute_indicators(candles)

            if not indicators:
                return self._demo_features(symbol)

            # Get current price
            price = await oanda.get_latest_price(instrument)

            # Build feature set
            features = {
                "indicators": indicators,
                "ohlcv": {
                    "open": candles[-1]["open"],
                    "high": candles[-1]["high"],
                    "low": candles[-1]["low"],
                    "close": candles[-1]["close"],
                    "volume": candles[-1].get("volume", 0),
                },
                "price": price or {},
                "candle_count": len(candles),
                "source": "oanda_live",
                "symbol": symbol,
                "timeframe": timeframe,
            }

            # Cache it
            _cache[cache_key] = features
            _cache_ts[cache_key] = now

            logger.info("live_features_computed", symbol=symbol, tf=timeframe,
                        close=indicators.get("close"), rsi=round(indicators.get("rsi_14", 0), 1),
                        source="oanda")

            return features

        except Exception as e:
            logger.error("feature_fetch_failed", symbol=symbol, error=str(e))
            return self._demo_features(symbol)

    async def get_all_prices(self) -> list[dict]:
        """Get latest prices for all configured instruments."""
        if not oanda.configured:
            return []

        instruments = list(SYMBOL_MAP.values())
        return await oanda.get_multiple_prices(instruments)

    async def get_account_state(self) -> dict:
        """Get OANDA account summary for risk calculations."""
        if not oanda.configured:
            return self._demo_portfolio()

        summary = await oanda.get_account_summary()
        if not summary:
            return self._demo_portfolio()

        return {
            "equity": summary["equity"],
            "balance": summary["balance"],
            "open_trade_count": summary["open_trade_count"],
            "net_exposure_pct": summary["margin_used"] / max(summary["equity"], 1),
            "max_correlation": 0.35,  # computed from positions in production
            "drawdown": {
                "daily": 0,  # computed from daily high watermark
                "weekly": 0,
            },
        }

    def _demo_features(self, symbol: str) -> dict:
        """Fallback demo data when OANDA is not configured."""
        demo = {
            "EURUSD": {"close": 1.0855, "rsi": 62.5, "macd_hist": 0.00023, "adx": 28.3,
                       "ema_20": 1.0842, "ema_50": 1.0815, "ema_200": 1.0780, "atr": 0.0045, "stoch_k": 72.1},
            "XAUUSD": {"close": 2645.30, "rsi": 58.2, "macd_hist": 1.25, "adx": 22.1,
                       "ema_20": 2640.50, "ema_50": 2625.80, "ema_200": 2580.00, "atr": 18.5, "stoch_k": 65.3},
            "GBPUSD": {"close": 1.2715, "rsi": 55.8, "macd_hist": 0.00015, "adx": 19.8,
                       "ema_20": 1.2700, "ema_50": 1.2685, "ema_200": 1.2650, "atr": 0.0055, "stoch_k": 58.2},
            "USDJPY": {"close": 149.85, "rsi": 48.3, "macd_hist": -0.045, "adx": 24.5,
                       "ema_20": 150.10, "ema_50": 150.50, "ema_200": 148.90, "atr": 0.65, "stoch_k": 42.1},
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
            "source": "demo",
            "symbol": symbol,
            "timeframe": "4H",
        }

    def _demo_portfolio(self) -> dict:
        return {
            "equity": 124350,
            "balance": 123100,
            "open_trade_count": 2,
            "net_exposure_pct": 0.04,
            "max_correlation": 0.35,
            "drawdown": {"daily": 0.005, "weekly": 0.012},
        }


# Singleton
market_data = MarketDataService()
