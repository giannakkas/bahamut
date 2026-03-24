"""
Bahamut Training Orchestrator

Runs ~50 assets in paper-trading mode to feed the learning engine.
Completely isolated from the production v7 orchestrator.

Schedule: Every 10 minutes via Celery beat.
Rate limit: Processes assets in batches of 8 with 3s gaps to stay
            within TwelveData's 55 req/min limit.

SAFETY:
  - NEVER touches the production ExecutionEngine
  - NEVER uses real capital
  - Uses its own Redis keys (bahamut:training:*)
  - Uses its own DB table (training_trades)
"""
import time
import structlog
from datetime import datetime, timezone

logger = structlog.get_logger()

# Import Celery app
try:
    from bahamut.celery_app import celery_app
    _has_celery = True
except ImportError:
    _has_celery = False
    celery_app = None


def _celery_task(func):
    if _has_celery and celery_app:
        return celery_app.task(
            bind=False, name=f"bahamut.training.orchestrator.{func.__name__}",
            max_retries=0, acks_late=True,
        )(func)
    return func


@_celery_task
def run_training_cycle():
    """
    Main training cycle. Runs every 10 minutes.
    Pipeline: fetch data → evaluate strategies → SELECTOR picks best → execute selected only.
    """
    from bahamut.config_assets import TRAINING_ASSETS, ASSET_CLASS_MAP
    from bahamut.config_assets import TRAINING_VIRTUAL_CAPITAL, TRAINING_RISK_PER_TRADE_PCT
    from bahamut.training.selector import PendingSignal, select_candidates, save_last_decisions

    _set_running(True, len(TRAINING_ASSETS))

    start = time.time()
    logger.info("training_cycle_start", assets=len(TRAINING_ASSETS))

    processed = 0
    errors = 0
    trades_closed = 0
    pending_signals: list[PendingSignal] = []

    # Phase 1: Scan all assets — collect signals, update positions, DO NOT execute yet
    batch_size = 8
    for i in range(0, len(TRAINING_ASSETS), batch_size):
        batch = TRAINING_ASSETS[i:i + batch_size]

        for asset in batch:
            try:
                result = _scan_training_asset(
                    asset,
                    asset_class=ASSET_CLASS_MAP.get(asset, "unknown"),
                )
                trades_closed += result.get("trades_closed", 0)
                pending_signals.extend(result.get("signals", []))
                processed += 1
            except Exception as e:
                errors += 1
                logger.debug("training_asset_error", asset=asset, error=str(e))

            _set_progress(processed + errors, len(TRAINING_ASSETS))

        if i + batch_size < len(TRAINING_ASSETS):
            time.sleep(3)

    # Phase 2: Selector picks which signals to execute
    decisions = select_candidates(pending_signals)
    save_last_decisions(decisions)
    signals_generated = len(pending_signals)
    selected = decisions.get("execute", [])

    logger.info("training_selector_result",
                signals=signals_generated, selected=len(selected),
                watchlisted=len(decisions.get("watchlist", [])),
                rejected=len(decisions.get("rejected", [])))

    # Phase 3: Execute only selected signals
    trades_opened = 0
    from bahamut.training.engine import open_training_position
    risk_amount = TRAINING_VIRTUAL_CAPITAL * TRAINING_RISK_PER_TRADE_PCT

    for dec in selected:
        try:
            # Find the original PendingSignal
            sig = next((s for s in pending_signals
                        if s.asset == dec["asset"] and s.strategy == dec["strategy"]), None)
            if not sig:
                continue

            pos = open_training_position(
                asset=sig.asset,
                asset_class=sig.asset_class,
                strategy=sig.strategy,
                direction=sig.direction,
                entry_price=sig.entry_price,
                sl_pct=sig.sl_pct,
                tp_pct=sig.tp_pct,
                risk_amount=risk_amount,
                regime=sig.regime,
                max_hold_bars=sig.max_hold_bars,
            )
            if pos:
                trades_opened += 1
                logger.info("training_selected_trade",
                            asset=sig.asset, strategy=sig.strategy,
                            direction=sig.direction, priority=dec.get("priority_score", 0))
        except Exception as e:
            logger.warning("training_execute_failed", asset=dec["asset"], error=str(e))

    duration_ms = int((time.time() - start) * 1000)
    logger.info("training_cycle_complete",
                processed=processed, errors=errors,
                signals=signals_generated, selected=len(selected),
                trades_opened=trades_opened, trades_closed=trades_closed,
                duration_ms=duration_ms)

    _record_cycle_stats(processed, errors, signals_generated, trades_closed, duration_ms)
    _set_running(False, 0)

    # Phase 4: Cache candidates + all-assets for instant API responses
    # (candles are already in data layer cache from Phase 1, so this is fast)
    try:
        from bahamut.training.candidates import (
            get_training_candidates, get_all_training_assets,
            cache_candidates, cache_all_assets,
        )
        cache_candidates(get_training_candidates(max_results=20))
        cache_all_assets(get_all_training_assets())
        logger.info("training_cache_updated")
    except Exception as e:
        logger.debug("training_cache_failed", error=str(e))

    return {
        "status": "OK",
        "processed": processed,
        "errors": errors,
        "signals": signals_generated,
        "selected": len(selected),
        "trades_opened": trades_opened,
        "trades_closed": trades_closed,
        "duration_ms": duration_ms,
    }


def _scan_training_asset(asset: str, asset_class: str) -> dict:
    """Scan a single asset: fetch data → evaluate strategies → collect signals.
    Does NOT execute — returns PendingSignal objects for the selector."""
    from bahamut.training.engine import update_positions_for_asset
    from bahamut.training.selector import PendingSignal
    from bahamut.training.candidates import score_ema_cross, score_breakout

    result: dict = {"signals": [], "trades_closed": 0}

    candles = _fetch_training_candles(asset)
    if not candles or len(candles) < 50:
        return result

    latest_time = candles[-1].get("datetime", "")

    # Always update existing positions with latest price
    bar = _make_bar(candles[-1])
    closed = update_positions_for_asset(asset, bar)
    result["trades_closed"] = len(closed)

    # Only evaluate strategies on new bars
    if not _is_training_new_bar(asset, latest_time):
        return result

    try:
        from bahamut.features.indicators import compute_indicators
        indicators = compute_indicators(candles)
        prev_indicators = compute_indicators(candles[:-1]) if len(candles) > 1 else None
    except Exception:
        return result

    if not indicators:
        return result

    regime = "RANGE"
    try:
        from bahamut.regime.v8_detector import detect_regime
        regime_result = detect_regime(indicators, candles[-15:])
        regime = regime_result.regime
    except Exception:
        pass

    # Evaluate strategies and collect as PendingSignals (don't execute)
    strategies = _get_strategies()
    for strat_name, strategy in strategies.items():
        try:
            signal = strategy.evaluate(candles, indicators, prev_indicators, asset=asset)
        except TypeError:
            try:
                signal = strategy.evaluate(candles, indicators, prev_indicators)
            except Exception:
                continue
        except Exception:
            continue

        if signal:
            # Get readiness score from candidates scorer
            readiness = 50  # default
            try:
                if "v5" in strat_name:
                    c = score_ema_cross(asset, asset_class, strat_name, candles, indicators, prev_indicators)
                    if c:
                        readiness = c.score
                elif "v9" in strat_name or "breakout" in strat_name:
                    c = score_breakout(asset, asset_class, candles, indicators)
                    if c:
                        readiness = c.score
            except Exception:
                pass

            result["signals"].append(PendingSignal(
                asset=asset,
                asset_class=asset_class,
                strategy=strat_name,
                direction=signal.direction,
                readiness_score=readiness,
                regime=regime,
                entry_price=bar["close"],
                sl_pct=signal.sl_pct or 0.03,
                tp_pct=signal.tp_pct or 0.06,
                max_hold_bars=signal.max_hold_bars or 30,
                reasons=signal.reason.split(", ") if signal.reason else [],
            ))

    _mark_training_bar(asset, latest_time)
    return result


def _make_bar(candle: dict) -> dict:
    return {
        "open": candle.get("open", 0),
        "high": candle.get("high", 0),
        "low": candle.get("low", 0),
        "close": candle.get("close", 0),
        "datetime": candle.get("datetime", ""),
    }


# ═══════════════════════════════════════════
# DATA FETCHING (uses same TwelveData adapter)
# ═══════════════════════════════════════════

def _fetch_training_candles(asset: str, count: int = 100) -> list[dict]:
    """Fetch candles for a training asset. Fewer candles than production (100 vs 260)."""
    try:
        from bahamut.data.live_data import fetch_candles
        return fetch_candles(asset, count=count)
    except Exception as e:
        logger.debug("training_fetch_failed", asset=asset, error=str(e))
        return []


# ═══════════════════════════════════════════
# BAR TRACKING (Redis-backed, separate from production)
# ═══════════════════════════════════════════

def _is_training_new_bar(asset: str, latest_time: str) -> bool:
    """Check if this is a new bar for training (separate from production bar tracking)."""
    import os, redis as _redis
    try:
        r = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        stored = r.get(f"bahamut:training:last_bar:{asset}")
        if stored:
            return (stored.decode() if isinstance(stored, bytes) else stored) != latest_time
        return True  # No previous bar → new
    except Exception:
        return True


def _mark_training_bar(asset: str, bar_time: str):
    """Mark a training bar as processed."""
    import os, redis as _redis
    try:
        r = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        r.set(f"bahamut:training:last_bar:{asset}", bar_time, ex=86400)  # 24h TTL
    except Exception:
        pass


# ═══════════════════════════════════════════
# STRATEGY LOADING (reuse production strategies)
# ═══════════════════════════════════════════

_strategies = None

def _get_strategies() -> dict:
    """Load the same strategies used in production. Cached after first call."""
    global _strategies
    if _strategies is not None:
        return _strategies

    strats = {}
    try:
        from bahamut.strategies.v5_base import BreakoutStrategyV5Base
        strats["v5_base"] = BreakoutStrategyV5Base()
    except Exception:
        pass
    try:
        from bahamut.strategies.v5_tuned import BreakoutStrategyV5Tuned
        strats["v5_tuned"] = BreakoutStrategyV5Tuned()
    except Exception:
        pass
    try:
        from bahamut.alpha.v9_candidate import BreakoutStrategyV9
        strats["v9_breakout"] = BreakoutStrategyV9()
    except Exception:
        pass

    _strategies = strats
    return strats


# ═══════════════════════════════════════════
# CYCLE STATS (Redis for dashboard)
# ═══════════════════════════════════════════

def _record_cycle_stats(processed: int, errors: int, signals: int, trades_closed: int, duration_ms: int):
    import os, json, redis as _redis
    try:
        r = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        now_iso = datetime.now(timezone.utc).isoformat()
        status = "OK" if processed > 0 and errors == 0 else "DEGRADED" if processed > 0 else "FAILED"

        stats = {
            "last_cycle": now_iso,
            "processed": processed,
            "errors": errors,
            "signals": signals,
            "trades_closed": trades_closed,
            "duration_ms": duration_ms,
            "status": status,
        }
        r.set("bahamut:training:last_cycle", json.dumps(stats))

        # Append to cycle history (keep last 20)
        r.lpush("bahamut:training:cycle_history", json.dumps(stats))
        r.ltrim("bahamut:training:cycle_history", 0, 19)
    except Exception:
        pass


def _set_running(is_running: bool, total_assets: int):
    """Set running flag visible to dashboard."""
    import os, json, redis as _redis
    try:
        r = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        r.set("bahamut:training:running", json.dumps({
            "is_running": is_running,
            "total_assets": total_assets,
            "started_at": datetime.now(timezone.utc).isoformat() if is_running else None,
        }), ex=120)  # Auto-expire in 2min (safety)
    except Exception:
        pass


def _set_progress(current: int, total: int):
    """Update scan progress for live dashboard."""
    import os, json, redis as _redis
    try:
        r = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        r.set("bahamut:training:progress", json.dumps({
            "current": current, "total": total,
        }), ex=120)
    except Exception:
        pass
