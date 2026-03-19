"""
Scanner Celery Tasks — periodic market scanning + deep analysis.

Flow:
1. Every 30 min: quick scan all 57 assets (score + rank)
2. Top 10 picks get full 6-agent analysis
3. Results cached in Redis for dashboard
"""

import asyncio
import json
import structlog

from bahamut.celery_app import celery_app
from bahamut.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="scanner.run_market_scan", bind=True, max_retries=2)
def run_market_scan(self):
    """
    Full market scan — runs every 30 min.
    Scans all 57 assets, scores them, caches results.
    Then triggers deep analysis on top picks.
    """
    try:
        results = run_async(_scan_async())
        if results and results.get("top_picks"):
            logger.info("market_scan_complete",
                        scanned=results["total_scanned"],
                        top_pick=results["top_picks"][0]["symbol"] if results["top_picks"] else "none",
                        top_score=results["top_picks"][0]["score"] if results["top_picks"] else 0)

            # Trigger deep analysis on top 10
            deep_analyze_top_picks.delay([p["symbol"] for p in results["top_picks"][:10]])

        return {"status": "ok", "scanned": results.get("total_scanned", 0)}
    except Exception as e:
        logger.error("market_scan_failed", error=str(e))
        raise self.retry(countdown=120)


async def _scan_async():
    from bahamut.scanner.scanner import run_full_scan, cache_scan_results
    results = await run_full_scan("4h")
    cache_scan_results(results)
    # Persist to PostgreSQL so results survive Redis TTL
    from bahamut.agents.persistence import save_scan_results
    save_scan_results(results)
    return results


@celery_app.task(name="scanner.deep_analyze_top_picks")
def deep_analyze_top_picks(symbols: list[str]):
    """
    Run full 6-agent cycles on the top picks from the scanner.
    """
    from bahamut.agents.orchestrator import orchestrator
    from bahamut.agents.tasks import _cache_to_redis, save_cycle_to_db
    from bahamut.scanner.scanner import SYMBOL_CLASS

    logger.info("deep_analysis_started", symbols=symbols)

    loop = asyncio.new_event_loop()
    deep_results = []

    for symbol in symbols:
        try:
            asset_class = SYMBOL_CLASS.get(symbol, "indices")
            result = loop.run_until_complete(
                orchestrator.run_cycle(
                    asset=symbol,
                    asset_class=asset_class,
                    timeframe="4H",
                    trading_profile="BALANCED",
                    triggered_by="SCANNER",
                )
            )

            d = result.get("decision", {})
            deep_results.append({
                "symbol": symbol,
                "direction": d.get("direction"),
                "score": d.get("final_score", 0),
                "decision": d.get("decision"),
                "agreement": d.get("agreement_pct", 0),
            })

            _cache_to_redis(symbol, result)
            save_cycle_to_db(result)

            logger.info("deep_analysis_result",
                        symbol=symbol, direction=d.get("direction"),
                        score=d.get("final_score"), decision=d.get("decision"))

        except Exception as e:
            logger.error("deep_analysis_failed", symbol=symbol, error=str(e))

    loop.close()

    # Cache deep results
    try:
        import redis
        r = redis.from_url(settings.redis_url)
        r.set("bahamut:deep_analysis", json.dumps(deep_results, default=str), ex=1800)
        r.close()
    except Exception as e:
        logger.warning("deep_analysis_cache_failed", error=str(e))

    logger.info("deep_analysis_completed", analyzed=len(deep_results),
                signals=[r for r in deep_results if r.get("decision") in ("SIGNAL", "STRONG_SIGNAL")])

    return deep_results
