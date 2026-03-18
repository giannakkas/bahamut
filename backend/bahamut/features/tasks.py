"""Feature computation and regime detection tasks."""
from bahamut.celery_app import celery_app
import structlog
logger = structlog.get_logger()

@celery_app.task(name="bahamut.features.tasks.compute_features")
def compute_features():
    logger.info("compute_features_warmup")

@celery_app.task(name="bahamut.features.tasks.detect_regime")
def detect_regime():
    import asyncio
    try:
        from bahamut.features.regime import detect_regime_from_features
        from bahamut.ingestion.market_data import market_data
        loop = asyncio.new_event_loop()
        features = loop.run_until_complete(market_data.get_features_for_asset("EURUSD", "4H"))
        loop.close()
        if features and features.get("indicators"):
            state = detect_regime_from_features(features)
            logger.info("regime_detected", regime=state.primary_regime, confidence=state.confidence)
            try:
                import redis, json
                from bahamut.config import get_settings
                r = redis.from_url(get_settings().redis_url)
                r.set("bahamut:current_regime", json.dumps(state.to_dict()), ex=600)
                r.close()
            except Exception:
                pass
            return state.to_dict()
    except Exception as e:
        logger.error("detect_regime_failed", error=str(e))
    return {"primary_regime": "RISK_ON", "confidence": 0.3}
