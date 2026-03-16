"""Celery tasks for agent orchestration."""
import asyncio
from bahamut.celery_app import celery_app
from bahamut.agents.orchestrator import orchestrator
import structlog

logger = structlog.get_logger()

DEMO_FEATURES = {
    "indicators": {
        "rsi_14": 62.5, "macd_histogram": 0.00023, "adx_14": 28.3,
        "ema_20": 1.0842, "ema_50": 1.0815, "ema_200": 1.0780,
        "close": 1.0855, "atr_14": 0.0045, "stoch_k": 72.1,
    },
    "ohlcv": {"open": 1.0840, "high": 1.0862, "low": 1.0830, "close": 1.0855},
    "macro": {"dxy": 103.2, "us10y": 4.25, "us2y": 4.55},
    "volatility": {"vix": 18.5},
    "portfolio": {"open_trade_count": 2, "net_exposure_pct": 0.04, "max_correlation": 0.35,
                  "drawdown": {"daily": 0.005, "weekly": 0.012}},
}

DEMO_ASSETS = [
    {"symbol": "EURUSD", "asset_class": "fx"},
    {"symbol": "XAUUSD", "asset_class": "commodities"},
]


@celery_app.task(name="bahamut.agents.tasks.run_all_signal_cycles")
def run_all_signal_cycles():
    logger.info("signal_cycles_batch_started")
    loop = asyncio.new_event_loop()
    for asset_info in DEMO_ASSETS:
        try:
            result = loop.run_until_complete(
                orchestrator.run_cycle(
                    asset=asset_info["symbol"], asset_class=asset_info["asset_class"],
                    timeframe="4H", regime="RISK_ON", regime_confidence=0.78,
                    trading_profile="BALANCED", features=DEMO_FEATURES,
                    portfolio_state=DEMO_FEATURES.get("portfolio", {}),
                )
            )
            d = result.get("decision", {})
            logger.info("cycle_result", asset=asset_info["symbol"],
                        direction=d.get("direction"), score=d.get("final_score"),
                        decision=d.get("decision"))
        except Exception as e:
            logger.exception("cycle_failed", asset=asset_info["symbol"], error=str(e))
    loop.close()


@celery_app.task(name="bahamut.agents.tasks.run_single_cycle")
def run_single_cycle(asset: str, asset_class: str, timeframe: str = "4H",
                     trading_profile: str = "BALANCED"):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            orchestrator.run_cycle(
                asset=asset, asset_class=asset_class, timeframe=timeframe,
                regime="RISK_ON", regime_confidence=0.78,
                trading_profile=trading_profile, features=DEMO_FEATURES,
                triggered_by="MANUAL",
            )
        )
    except Exception as e:
        logger.exception("single_cycle_failed", error=str(e))
        return {"error": str(e)}
    finally:
        loop.close()
