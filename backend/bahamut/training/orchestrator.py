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

    # Decrement pattern suppression timers
    try:
        from bahamut.training.context_gate import decrement_suppression_cycles
        decrement_suppression_cycles()
    except Exception:
        pass

    processed = 0
    errors = 0
    trades_closed = 0
    pending_signals: list[PendingSignal] = []
    observed_regimes: dict[str, str] = {}  # asset_class → latest regime

    # Reset per-cycle dedup tracking
    try:
        from bahamut.training.engine import reset_cycle_dedup, cleanup_invalid_positions
        reset_cycle_dedup()
        cleaned = cleanup_invalid_positions()
        if cleaned:
            logger.info("training_cleanup", removed=cleaned)
    except Exception:
        pass

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
                # Collect regime per asset class
                if result.get("regime"):
                    observed_regimes[ASSET_CLASS_MAP.get(asset, "unknown")] = result["regime"]
                processed += 1
            except Exception as e:
                errors += 1
                logger.debug("training_asset_error", asset=asset, error=str(e))

            _set_progress(processed + errors, len(TRAINING_ASSETS))

        if i + batch_size < len(TRAINING_ASSETS):
            time.sleep(3)

    # Phase 1.5: Check if regime changes should release suppressed patterns
    if observed_regimes:
        try:
            from bahamut.training.context_gate import check_regime_release
            check_regime_release(observed_regimes)
        except Exception:
            pass

    # Phase 2: Selector picks which signals to execute
    decisions = select_candidates(pending_signals)
    save_last_decisions(decisions)
    signals_generated = len(pending_signals)
    selected = decisions.get("execute", [])

    logger.info("training_selector_result",
                signals=signals_generated, selected=len(selected),
                watchlisted=len(decisions.get("watchlist", [])),
                rejected=len(decisions.get("rejected", [])))

    # Telegram: notify on new execution decisions
    if selected:
        try:
            from bahamut.monitoring.telegram import send_training_signal
            send_training_signal({
                "signals": signals_generated,
                "selected": len(selected),
                "assets": [d["asset"] for d in selected],
            })
        except Exception:
            pass

    # Phase 3: Execute only selected signals
    trades_opened = 0
    from bahamut.training.engine import open_training_position
    risk_amount = TRAINING_VIRTUAL_CAPITAL * TRAINING_RISK_PER_TRADE_PCT

    logger.info("training_execution_phase",
                selected_count=len(selected),
                risk_per_trade=risk_amount,
                selected_assets=[d["asset"] for d in selected])

    for dec in selected:
        try:
            # Find the original PendingSignal
            sig = next((s for s in pending_signals
                        if s.asset == dec["asset"] and s.strategy == dec["strategy"]), None)
            if not sig:
                logger.warning("training_execute_signal_not_found",
                               asset=dec["asset"], strategy=dec["strategy"])
                continue

            logger.info("training_execute_attempting",
                        asset=sig.asset, strategy=sig.strategy,
                        direction=sig.direction, entry_price=sig.entry_price,
                        exec_type=sig.execution_type,
                        risk=round(risk_amount * sig.risk_multiplier, 2))

            pos = open_training_position(
                asset=sig.asset,
                asset_class=sig.asset_class,
                strategy=sig.strategy,
                direction=sig.direction,
                entry_price=sig.entry_price,
                sl_pct=sig.sl_pct,
                tp_pct=sig.tp_pct,
                risk_amount=risk_amount * sig.risk_multiplier,
                regime=sig.regime,
                max_hold_bars=sig.max_hold_bars,
                execution_type=sig.execution_type,
                confidence_score=sig.confidence_score,
                trigger_reason=sig.trigger_reason,
            )
            if pos:
                trades_opened += 1
                logger.info("training_trade_OPENED",
                            asset=sig.asset, strategy=sig.strategy,
                            direction=sig.direction, position_id=pos.position_id,
                            execution_type=sig.execution_type,
                            confidence=sig.confidence_score,
                            entry_price=sig.entry_price)
            else:
                logger.warning("training_execute_returned_none",
                               asset=sig.asset, strategy=sig.strategy,
                               msg="open_training_position returned None/False")
        except Exception as e:
            logger.error("training_execute_failed", asset=dec["asset"],
                         error=str(e), traceback=True)

    duration_ms = int((time.time() - start) * 1000)
    logger.info("training_cycle_complete",
                processed=processed, errors=errors,
                signals=signals_generated, selected=len(selected),
                trades_opened=trades_opened, trades_closed=trades_closed,
                duration_ms=duration_ms)

    # Push live update to admin dashboard
    try:
        from bahamut.ws.admin_live import publish_event
        publish_event("cycle_completed", {
            "mode": "training", "processed": processed,
            "signals": signals_generated, "selected": len(selected),
            "opened": trades_opened, "closed": trades_closed,
            "duration_ms": duration_ms,
        })
    except Exception:
        pass

    _record_cycle_stats(processed, errors, signals_generated, trades_closed,
                        duration_ms, trades_opened=trades_opened, selected=len(selected))
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

    # Phase 5: Adaptive threshold update
    try:
        from bahamut.training.adaptive_thresholds import run_adaptive_update
        profile = run_adaptive_update()
        logger.info("training_adaptive_updated", mode=profile.mode)
    except Exception as e:
        logger.debug("training_adaptive_failed", error=str(e))

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
    is_new_bar = _is_training_new_bar(asset, latest_time)

    # Always update existing positions with latest price
    bar = _make_bar(candles[-1])
    closed = update_positions_for_asset(asset, bar)
    result["trades_closed"] = len(closed)

    # Always compute indicators (needed for both standard and early eval)
    try:
        indicators, prev_indicators = _compute_training_indicators(asset, candles)
    except Exception:
        return result

    if not indicators:
        return result

    regime = "RANGE"
    try:
        from bahamut.regime.v8_detector import detect_regime
        from bahamut.data.binance_data import is_crypto

        if is_crypto(asset):
            # DUAL TIMEFRAME: Use 4H candles for macro regime detection
            # 15m candles oscillate and look like RANGE even during crashes.
            # 4H gives the true macro picture (CRASH/TREND/RANGE).
            from bahamut.data.binance_data import get_candles, compute_indicators as binance_ind
            candles_4h = get_candles(asset, interval="4h", limit=100)
            if candles_4h and len(candles_4h) >= 30:
                ind_4h = binance_ind(candles_4h)
                regime_result = detect_regime(ind_4h, candles_4h[-15:])
                regime = regime_result.regime
                logger.debug("training_crypto_dual_regime",
                             asset=asset, regime=regime,
                             reason=regime_result.reason)
            else:
                # Fallback to 15m indicators
                regime_result = detect_regime(indicators, candles[-15:])
                regime = regime_result.regime
        else:
            # Stocks: standard regime from 4H indicators
            regime_result = detect_regime(indicators, candles[-15:])
            regime = regime_result.regime
    except Exception:
        pass

    # Inject regime into indicators so strategies (v10) can read it
    indicators["_regime"] = regime
    indicators["_asset_class"] = asset_class

    # Inject timeframe so strategies can adjust SL/TP
    from bahamut.data.binance_data import is_crypto
    indicators["_interval"] = CRYPTO_INTERVAL if is_crypto(asset) else "4h"

    result["regime"] = regime  # For orchestrator regime collection

    # Evaluate strategies and collect as PendingSignals (don't execute)
    strategies = _get_strategies()
    strategy_signals_found = 0

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
            strategy_signals_found += 1
            # Get readiness score + indicators from candidates scorer
            readiness = 50
            candidate_indicators = {}
            distance_str = ""
            try:
                if "v5" in strat_name:
                    c = score_ema_cross(asset, asset_class, strat_name, candles, indicators, prev_indicators)
                    if c:
                        readiness = c.score
                        candidate_indicators = c.indicators
                        distance_str = c.distance_to_trigger
                elif "v9" in strat_name or "breakout" in strat_name:
                    c = score_breakout(asset, asset_class, candles, indicators)
                    if c:
                        readiness = c.score
                        candidate_indicators = c.indicators
                        distance_str = c.distance_to_trigger
                elif "v10" in strat_name or "mean" in strat_name:
                    from bahamut.alpha.v10_mean_reversion import score_mean_reversion
                    c = score_mean_reversion(asset, asset_class, candles, indicators, prev_indicators, regime)
                    if c:
                        readiness = c.score
                        candidate_indicators = c.indicators
                        distance_str = c.distance_to_trigger
            except Exception:
                pass

            # Record scan direction for consistency checking
            from bahamut.training.engine import record_scan_direction, evaluate_early_execution
            record_scan_direction(asset, signal.direction)

            # Determine execution type
            exec_type = "standard"
            confidence = float(readiness)
            trigger = "4h_close"
            risk_mult = 1.0

            if not is_new_bar and readiness >= 90:
                # Not a new 4H bar — evaluate for early execution
                early = evaluate_early_execution(
                    asset=asset,
                    readiness_score=readiness,
                    regime=regime,
                    direction=signal.direction,
                    indicators=candidate_indicators,
                    distance_to_trigger=distance_str,
                )
                if early["eligible"]:
                    exec_type = "early"
                    confidence = early["confidence"]
                    trigger = "early_signal"
                    risk_mult = early["risk_multiplier"]
                    logger.info("training_early_eligible",
                                asset=asset, score=readiness, confidence=confidence)
            elif not is_new_bar:
                # Not a new bar and not early-eligible — skip (wait for 4H close)
                logger.debug("training_signal_skipped_not_new_bar",
                             asset=asset, strategy=strat_name, readiness=readiness)
                continue

            logger.info("training_signal_generated",
                        asset=asset, strategy=strat_name, direction=signal.direction,
                        readiness=readiness, regime=regime, exec_type=exec_type,
                        is_new_bar=is_new_bar, source="strategy")

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
                execution_type=exec_type,
                confidence_score=confidence,
                trigger_reason=trigger,
                risk_multiplier=risk_mult,
                indicators=candidate_indicators,
            ))

    # ═══════════════════════════════════════════
    # DEBUG EXPLORATION OVERRIDE
    # When strategies don't fire (they require exact crossover/breakout events),
    # but candidate scores are promising, force a signal for exploration learning.
    #
    # FIRES EVERY CYCLE (not gated on is_new_bar):
    #   - Strategies only fire on rare events (EMA cross, breakout confirmation)
    #   - Stocks have no bars on weekends → is_new_bar is always False
    #   - We need signals to prove execution works and start learning
    #
    # Config-driven — disable by setting exploration.debug_override=false
    # ═══════════════════════════════════════════
    if strategy_signals_found == 0:
        debug_enabled = True
        debug_min_score = 20  # Low floor — most approaching candidates qualify
        try:
            from bahamut.admin.config import get_config
            debug_enabled = get_config("exploration.debug_override", True)
            debug_min_score = get_config("exploration.debug_min_score", 20)
        except Exception as e:
            logger.warning("debug_override_config_failed", error=str(e),
                           msg="using defaults: enabled=True, min_score=20")

        # Skip assets that already have an open position (no duplicates)
        has_existing_position = False
        try:
            from bahamut.training.engine import _load_positions
            existing = _load_positions()
            has_existing_position = any(p.asset == asset for p in existing)
        except Exception:
            pass

        logger.info("debug_override_check",
                    asset=asset, enabled=debug_enabled,
                    min_score=debug_min_score, is_new_bar=is_new_bar,
                    regime=regime, has_existing_position=has_existing_position)

        if debug_enabled and not has_existing_position:
            # Evaluate all candidate scorers for this asset
            best_candidate = None
            best_score = 0
            scorer_errors = []
            for strat_name in ["v5_base", "v9_breakout", "v10_mean_reversion"]:
                try:
                    c = None
                    if "v5" in strat_name:
                        c = score_ema_cross(asset, asset_class, strat_name, candles, indicators, prev_indicators)
                    elif "v9" in strat_name:
                        c = score_breakout(asset, asset_class, candles, indicators)
                    elif "v10" in strat_name:
                        from bahamut.alpha.v10_mean_reversion import score_mean_reversion
                        c = score_mean_reversion(asset, asset_class, candles, indicators, prev_indicators, regime)

                    if c:
                        logger.info("debug_override_candidate_scored",
                                    asset=asset, strategy=strat_name,
                                    score=c.score, direction=c.direction,
                                    min_required=debug_min_score,
                                    passes=c.score >= debug_min_score)
                        if c.score >= debug_min_score and c.score > best_score:
                            best_candidate = c
                            best_score = c.score
                    else:
                        logger.debug("debug_override_scorer_returned_none",
                                     asset=asset, strategy=strat_name)
                except Exception as e:
                    scorer_errors.append(f"{strat_name}: {str(e)[:80]}")
                    logger.error("debug_override_scorer_exception",
                                 asset=asset, strategy=strat_name, error=str(e))

            if best_candidate:
                # Check per-cycle rate limit using a simple counter on the result
                direction = best_candidate.direction if hasattr(best_candidate, 'direction') and best_candidate.direction in ("LONG", "SHORT") else "LONG"
                strat = best_candidate.strategy if hasattr(best_candidate, 'strategy') else "v5_base"

                logger.info("DEBUG_EXPLORATION_OVERRIDE",
                            asset=asset, strategy=strat,
                            score=best_score, direction=direction,
                            regime=regime, debug_min_score=debug_min_score,
                            is_new_bar=is_new_bar,
                            reason="Candidate score qualifies for debug exploration")

                # Get strategy's actual parameters (don't hardcode)
                strat_obj = strategies.get(strat)
                strat_sl = getattr(strat_obj, "sl_pct", 0.05) if strat_obj else 0.05
                strat_tp = getattr(strat_obj, "tp_pct", 0.10) if strat_obj else 0.10
                strat_hold = getattr(strat_obj, "max_hold", 20) if strat_obj else 20

                # Context gate check — even debug exploration must not open in invalid regimes
                context_blocked = False
                try:
                    from bahamut.training.context_gate import validate_strategy_context
                    gate = validate_strategy_context(strat, regime, direction)
                    if not gate["valid"]:
                        logger.info("debug_exploration_context_blocked",
                                    asset=asset, strategy=strat, regime=regime,
                                    reason=gate["reason"])
                        context_blocked = True
                except Exception:
                    pass

                if not context_blocked:
                    result["signals"].append(PendingSignal(
                        asset=asset,
                        asset_class=asset_class,
                        strategy=strat,
                        direction=direction,
                        readiness_score=best_score,
                        regime=regime,
                        entry_price=bar["close"],
                        sl_pct=strat_sl,
                        tp_pct=strat_tp,
                        max_hold_bars=strat_hold,
                        reasons=best_candidate.reasons if hasattr(best_candidate, 'reasons') else ["debug_exploration_override"],
                        execution_type="debug_exploration",
                        confidence_score=float(best_score),
                        trigger_reason="debug_exploration_override",
                        risk_multiplier=0.5,
                        indicators=best_candidate.indicators if hasattr(best_candidate, 'indicators') else {},
                    ))
            else:
                logger.info("debug_override_no_qualifying_candidate",
                            asset=asset, min_score=debug_min_score,
                            scorer_errors=scorer_errors if scorer_errors else "none")
        elif has_existing_position:
            logger.info("debug_override_skipped_duplicate",
                        asset=asset, reason="Already has open position")

    # Log per-asset scan summary
    logger.info("training_asset_scan_complete",
                asset=asset, is_new_bar=is_new_bar,
                strategies_loaded=len(strategies),
                strategy_signals=strategy_signals_found,
                total_signals=len(result["signals"]),
                trades_closed=result["trades_closed"],
                regime=regime)

    if is_new_bar:
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
# DATA FETCHING
#   Crypto: Binance public API (free, unlimited, 15m candles)
#   Stocks: Twelve Data (4H candles, 55 req/min)
# ═══════════════════════════════════════════

# Crypto candle interval — can go as tight as 1m
CRYPTO_INTERVAL = "15m"
CRYPTO_CANDLE_COUNT = 200  # 200 × 15m = ~50 hours of data

def _fetch_training_candles(asset: str, count: int = 100) -> list[dict]:
    """Fetch candles for a training asset.
    Crypto → Binance public API (free, 15m candles)
    Stocks → Twelve Data (4H candles, metered)
    """
    try:
        from bahamut.data.binance_data import is_crypto
        if is_crypto(asset):
            from bahamut.data.binance_data import get_candles
            return get_candles(asset, interval=CRYPTO_INTERVAL, limit=CRYPTO_CANDLE_COUNT)
    except Exception as e:
        logger.debug("binance_data_failed", asset=asset, error=str(e)[:50])

    # Fallback: Twelve Data (stocks, or crypto if Binance fails)
    try:
        from bahamut.data.live_data import fetch_candles
        return fetch_candles(asset, count=count)
    except Exception as e:
        logger.debug("training_fetch_failed", asset=asset, error=str(e))
        return []


def _compute_training_indicators(asset: str, candles: list[dict]):
    """Compute indicators — use Binance indicators for crypto, standard for stocks."""
    try:
        from bahamut.data.binance_data import is_crypto, compute_indicators as binance_indicators
        if is_crypto(asset) and candles:
            indicators = binance_indicators(candles)
            prev_indicators = binance_indicators(candles[:-1]) if len(candles) > 1 else None
            return indicators, prev_indicators
    except Exception:
        pass

    # Standard Twelve Data indicators
    from bahamut.features.indicators import compute_indicators
    indicators = compute_indicators(candles)
    prev_indicators = compute_indicators(candles[:-1]) if len(candles) > 1 else None
    return indicators, prev_indicators


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
        from bahamut.strategies.v5_base import V5Base
        strats["v5_base"] = V5Base()
        logger.info("strategy_loaded", name="v5_base")
    except Exception as e:
        logger.error("strategy_load_failed", name="v5_base", error=str(e))
    try:
        from bahamut.strategies.v5_tuned import V5Tuned
        strats["v5_tuned"] = V5Tuned()
        logger.info("strategy_loaded", name="v5_tuned")
    except Exception as e:
        logger.error("strategy_load_failed", name="v5_tuned", error=str(e))
    try:
        from bahamut.alpha.v9_candidate import V9Breakout
        strats["v9_breakout"] = V9Breakout()
        logger.info("strategy_loaded", name="v9_breakout")
    except Exception as e:
        logger.error("strategy_load_failed", name="v9_breakout", error=str(e))
    try:
        from bahamut.alpha.v10_mean_reversion import V10MeanReversion
        strats["v10_mean_reversion"] = V10MeanReversion()
        logger.info("strategy_loaded", name="v10_mean_reversion")
    except Exception as e:
        logger.error("strategy_load_failed", name="v10_mean_reversion", error=str(e))

    if not strats:
        logger.critical("no_strategies_loaded", msg="ALL strategy imports failed — 0 signals possible")
        return strats  # Don't cache empty — retry next call

    _strategies = strats
    return strats


# ═══════════════════════════════════════════
# CYCLE STATS (Redis for dashboard)
# ═══════════════════════════════════════════

def _record_cycle_stats(processed: int, errors: int, signals: int,
                        trades_closed: int, duration_ms: int,
                        trades_opened: int = 0, selected: int = 0):
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
            "selected": selected,
            "trades_opened": trades_opened,
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
