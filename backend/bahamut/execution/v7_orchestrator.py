"""
Bahamut v7 Orchestrator — The heartbeat of the trading system.

Runs on each new 4H bar:
  1. Fetch latest candles for each asset
  2. Compute indicators (current + previous bar)
  3. Evaluate all enabled strategies
  4. Submit signals to execution engine
  5. Process bar through execution engine (fill pending, check exits)
  6. Update portfolio manager
  7. Persist state to DB
  8. Take equity snapshot

Celery task: runs every 2 min, only acts when a new 4H bar is detected.
Works standalone (without Celery) when called via run_v7_cycle_sync().
"""
import time
import structlog
from datetime import datetime, timezone

# Celery import — optional, works without it for manual triggers
try:
    from bahamut.celery_app import celery_app
    _has_celery = True
except ImportError:
    _has_celery = False
    celery_app = None

from bahamut.execution.engine import get_execution_engine
from bahamut.portfolio.manager import get_portfolio_manager
from bahamut.features.indicators import compute_indicators

logger = structlog.get_logger()

# Track last processed bar to avoid duplicate processing
_last_bar_time: dict[str, str] = {}

# Strategy registry
_strategies = None

def _get_strategies():
    """Lazy-load strategy instances."""
    global _strategies
    if _strategies is None:
        from bahamut.strategies.v5_base import V5Base
        from bahamut.strategies.v5_tuned import V5Tuned
        from bahamut.strategies.v8_range import V8Range
        from bahamut.strategies.v8_defensive import V8Defensive
        from bahamut.alpha.v9_candidate import V9Breakout
        _strategies = {
            "v5_base": V5Base(),
            "v5_tuned": V5Tuned(),
            "v8_range": V8Range(),
            "v8_defensive": V8Defensive(),
            "v9_breakout": V9Breakout(),
        }
    return _strategies


def _fetch_candles(asset: str, timeframe: str = "4H", count: int = 260) -> list[dict]:
    """
    Fetch candles via live data provider.
    Tries: Redis cache → Twelve Data API → synthetic fallback.
    """
    try:
        from bahamut.data.live_data import fetch_candles
        return fetch_candles(asset, count)
    except Exception as e:
        logger.error("candle_fetch_error", asset=asset, error=str(e))
        return []


def _celery_task(func):
    """Register as Celery task if available, otherwise pass through."""
    if _has_celery and celery_app:
        return celery_app.task(
            name="bahamut.execution.v7_orchestrator.run_v7_cycle",
            bind=True, max_retries=1)(func)
    return func


@_celery_task
def run_v7_cycle(self=None):
    """
    Main v7 trading cycle. Runs every 2 minutes.
    Uses Redis distributed lock. Full cycle instrumented for observability.
    """
    from bahamut.monitoring.cycle_log import start_cycle, end_cycle, record_skip

    lock = None
    try:
        import redis, os
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        lock = r.lock("bahamut:v7_cycle_lock", timeout=300, blocking=False)
        if not lock.acquire(blocking=False):
            logger.info("v7_cycle_skipped_lock_held")
            record_skip("orchestrator lock already held")
            return
    except Exception as e:
        logger.debug("v7_cycle_lock_unavailable", error=str(e))

    cycle = start_cycle()
    try:
        _run_v7_cycle_inner()
        end_cycle("SUCCESS")
    except Exception as e:
        logger.error("v7_cycle_fatal", error=str(e))
        end_cycle("ERROR", error=str(e))
    finally:
        # Send cycle report email (only for new-bar cycles or errors)
        try:
            from bahamut.monitoring.cycle_log import get_last_cycle
            from bahamut.monitoring.alerts import send_cycle_report
            lc = get_last_cycle()
            # Send report if: any asset had a new bar, or cycle errored
            has_new_bar = any(a.get("new_bar") for a in lc.get("assets", []))
            if has_new_bar or lc.get("status") == "ERROR":
                send_cycle_report(lc)
        except Exception as e:
            logger.debug("cycle_report_error", error=str(e))

        if lock:
            try:
                lock.release()
            except Exception:
                pass
        try:
            import redis, os, time as _t
            r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
            r.set("bahamut:last_v7_cycle", str(_t.time()))
        except Exception:
            pass


def _run_v7_cycle_inner():
    """Inner cycle logic with full observability instrumentation."""
    global _last_bar_time
    from bahamut.monitoring.cycle_log import (
        add_asset_evaluation, add_strategy_decision, record_signal, record_order,
        record_position_closed, AssetEvaluation, StrategyDecision,
    )
    from bahamut.data.live_data import is_new_bar, get_data_source

    engine = get_execution_engine()
    pm = get_portfolio_manager()
    strategies = _get_strategies()

    assets = ["BTCUSD"]
    try:
        from bahamut.config_assets import ACTIVE_TREND_ASSETS
        assets = ACTIVE_TREND_ASSETS
    except ImportError:
        pass

    closed_before = len(engine.closed_trades)

    for asset in assets:
        try:
            candles = _fetch_candles(asset)
            if not candles or len(candles) < 260:
                add_asset_evaluation(AssetEvaluation(
                    asset=asset, regime="UNKNOWN",
                    summary=f"insufficient data ({len(candles) if candles else 0} candles)"))
                continue

            latest_time = candles[-1].get("datetime", "")
            new_bar = is_new_bar(asset, latest_time)

            # Always compute regime (cheap, no side effects) so we never show "?"
            indicators = compute_indicators(candles)
            prev_indicators = compute_indicators(candles[:-1]) if len(candles) > 1 else None
            current_regime = "?"
            regime_conf = 0.0
            if indicators:
                try:
                    from bahamut.regime.v8_detector import detect_regime
                    regime_result = detect_regime(indicators, candles[-15:])
                    current_regime = regime_result.regime
                    regime_conf = regime_result.confidence
                    pm.asset_regimes[asset] = current_regime
                except Exception:
                    current_regime = pm.asset_regimes.get(asset, "?")

            # Always compute strategy conditions for observability
            if indicators:
                try:
                    from bahamut.monitoring.strategy_conditions import compute_conditions
                    compute_conditions(asset, candles, indicators, prev_indicators, current_regime)
                except Exception:
                    pass

            if not new_bar:
                add_asset_evaluation(AssetEvaluation(
                    asset=asset, timestamp=latest_time,
                    bar_close=candles[-1].get("close", 0),
                    new_bar=False, regime=current_regime,
                    regime_confidence=regime_conf,
                    summary=f"same bar as last cycle ({latest_time})"))
                continue

            logger.info("v7_new_bar", asset=asset, time=latest_time,
                        close=candles[-1].get("close", 0),
                        source=get_data_source())

            if not indicators:
                add_asset_evaluation(AssetEvaluation(
                    asset=asset, timestamp=latest_time, new_bar=True,
                    summary="indicator computation failed"))
                continue

            # Route strategies based on already-detected regime
            regime_str = current_regime
            active_strats = []
            try:
                from bahamut.regime.v8_detector import RegimeResult
                from bahamut.portfolio.router_v8 import route
                regime_obj = RegimeResult(regime=current_regime, confidence=regime_conf)
                routing = route(regime_obj, asset=asset)
                pm.apply_routing(routing, asset=asset)
                active_strats = routing.active_strategies
            except Exception as e:
                logger.error("v8_regime_error", error=str(e))

            # Start asset evaluation record
            asset_eval = AssetEvaluation(
                asset=asset, timestamp=latest_time, regime=regime_str,
                regime_confidence=regime_conf, active_strategies=list(active_strats),
                bar_close=candles[-1].get("close", 0), new_bar=True,
            )

            bar = {
                "open": candles[-1].get("open", 0),
                "high": candles[-1].get("high", 0),
                "low": candles[-1].get("low", 0),
                "close": candles[-1].get("close", 0),
                "datetime": latest_time,
                "volume": candles[-1].get("volume", 0),
            }

            engine.on_new_bar(bar, pm.get_sleeve_equities(), asset=asset)

            # Check for positions closed by this bar
            closed_after_bar = len(engine.closed_trades)
            new_closes = closed_after_bar - closed_before
            for _ in range(new_closes):
                record_position_closed()
            closed_before = closed_after_bar

            # Evaluate strategies
            for strat_name in active_strats:
                strategy = strategies.get(strat_name)
                if not strategy:
                    asset_eval.strategies_evaluated.append(
                        StrategyDecision(strat_name, "SKIPPED", "strategy not loaded"))
                    continue

                can_trade, reason = pm.can_trade(strat_name, asset=asset)
                if not can_trade:
                    asset_eval.strategies_evaluated.append(
                        StrategyDecision(strat_name, "BLOCKED", reason))
                    continue

                # Crypto risk cap
                try:
                    from bahamut.config_assets import MAX_COMBINED_CRYPTO_OPEN_RISK_PCT
                    total_risk = sum(p.risk_amount for p in engine.open_positions)
                    if total_risk / max(1, pm.total_equity) > MAX_COMBINED_CRYPTO_OPEN_RISK_PCT:
                        asset_eval.strategies_evaluated.append(
                            StrategyDecision(strat_name, "BLOCKED", "combined crypto risk cap exceeded"))
                        continue
                except ImportError:
                    pass

                # Evaluate
                try:
                    signal = strategy.evaluate(candles, indicators, prev_indicators, asset=asset)
                except TypeError:
                    signal = strategy.evaluate(candles, indicators, prev_indicators)

                if signal:
                    signal.asset = asset
                    record_signal()
                    try:
                        from bahamut.config_assets import get_risk_multiplier
                        risk_mult = get_risk_multiplier(asset)
                    except ImportError:
                        risk_mult = 1.0

                    sleeve_eq = pm.get_sleeve_equity(strat_name) * risk_mult
                    order = engine.submit_signal(signal, sleeve_eq)
                    if order:
                        record_order()
                        asset_eval.strategies_evaluated.append(
                            StrategyDecision(strat_name, "EXECUTED",
                                             f"signal {signal.direction}, order {order.order_id}"))
                        _persist_order(order)
                    else:
                        asset_eval.strategies_evaluated.append(
                            StrategyDecision(strat_name, "BLOCKED",
                                             "signal generated but order rejected (duplicate/limit)"))
                else:
                    # Provide reason for no signal
                    reason_text = _get_no_signal_reason(strat_name, indicators, prev_indicators, asset)
                    asset_eval.strategies_evaluated.append(
                        StrategyDecision(strat_name, "NO_SIGNAL", reason_text))

            # Generate summary
            results = [f"{s.strategy}→{s.result}" for s in asset_eval.strategies_evaluated]
            asset_eval.summary = f"{regime_str} ({regime_conf:.0%}), {', '.join(results) or 'no strategies'}"
            add_asset_evaluation(asset_eval)

            pm.update()
            _persist_new_trades(engine)
            _persist_sleeves(pm)

        except Exception as e:
            logger.error("v7_cycle_error", asset=asset, error=str(e))
            add_asset_evaluation(AssetEvaluation(
                asset=asset, summary=f"ERROR: {str(e)[:100]}"))

    # Snapshot + alerts
    try:
        snap = pm.take_snapshot()
        _persist_snapshot(snap)
    except Exception as e:
        logger.error("v7_snapshot_error", error=str(e))

    try:
        from bahamut.monitoring.alerts import check_alerts
        check_alerts(pm.get_summary(), engine.get_stats())
    except Exception:
        pass


def _get_no_signal_reason(strat_name: str, ind: dict, prev_ind: dict, asset: str) -> str:
    """Generate a human-readable reason for NO_SIGNAL."""
    close = ind.get("close", 0)
    ema20 = ind.get("ema_20", 0)
    ema50 = ind.get("ema_50", 0)
    ema200 = ind.get("ema_200", 0)

    if "v5" in strat_name:
        if close <= ema200:
            return f"price ${close:,.0f} below EMA200 ${ema200:,.0f} (no bull regime)"
        if prev_ind:
            p20 = prev_ind.get("ema_20", 0)
            p50 = prev_ind.get("ema_50", 0)
            if p20 > p50:
                return f"EMA20 already above EMA50 (no new cross)"
            else:
                return f"EMA20 ${ema20:,.0f} has not crossed above EMA50 ${ema50:,.0f}"
        return "waiting for EMA20×EMA50 golden cross"

    if "v9" in strat_name or "breakout" in strat_name:
        return "no confirmed 20-bar high breakout"

    return "entry conditions not met"


# ── Track what's been persisted ──
_persisted_trade_ids: set = set()
_persisted_order_ids: set = set()


def _persist_order(order):
    """Persist order to DB."""
    global _persisted_order_ids
    if order.order_id in _persisted_order_ids:
        return
    try:
        from bahamut.execution.v7_persistence import persist_order
        persist_order({
            "order_id": order.order_id,
            "strategy": order.strategy,
            "asset": order.asset,
            "direction": order.direction,
            "status": order.status.value if hasattr(order.status, 'value') else str(order.status),
            "signal_time": order.signal_time,
            "fill_time": order.fill_time,
            "entry_price": order.entry_price,
            "stop_price": order.stop_price,
            "tp_price": order.tp_price,
            "size": order.size,
            "risk_amount": order.risk_amount,
            "sl_pct": order.sl_pct,
            "tp_pct": order.tp_pct,
            "max_hold_bars": order.max_hold_bars,
            "signal_id": order.signal_id,
        })
        _persisted_order_ids.add(order.order_id)
    except Exception as e:
        logger.error("persist_order_error", error=str(e))


def _persist_new_trades(engine):
    """Persist any newly closed trades."""
    global _persisted_trade_ids
    try:
        from bahamut.execution.v7_persistence import persist_trade
        for trade in engine.closed_trades:
            if trade.trade_id not in _persisted_trade_ids:
                persist_trade({
                    "trade_id": trade.trade_id,
                    "order_id": trade.order_id,
                    "strategy": trade.strategy,
                    "asset": trade.asset,
                    "direction": trade.direction,
                    "entry_price": trade.entry_price,
                    "exit_price": trade.exit_price,
                    "stop_price": trade.stop_price,
                    "tp_price": trade.tp_price,
                    "size": trade.size,
                    "risk_amount": trade.risk_amount,
                    "pnl": trade.pnl,
                    "pnl_pct": trade.pnl_pct,
                    "entry_time": trade.entry_time,
                    "exit_time": trade.exit_time,
                    "exit_reason": trade.exit_reason,
                    "bars_held": trade.bars_held,
                })
                _persisted_trade_ids.add(trade.trade_id)
    except Exception as e:
        logger.error("persist_trades_error", error=str(e))


def _persist_sleeves(pm):
    """Persist all sleeve states."""
    try:
        from bahamut.execution.v7_persistence import persist_sleeve
        for name, sleeve in pm.sleeves.items():
            persist_sleeve(name, {
                "weight": sleeve.allocation_weight,
                "initial_capital": sleeve.initial_capital,
                "equity": sleeve.current_equity,
                "realized_pnl": sleeve.realized_pnl,
                "unrealized_pnl": sleeve.unrealized_pnl,
                "peak_equity": sleeve.peak_equity,
                "drawdown": sleeve.drawdown,
                "trades": sleeve.trade_count,
                "wins": sleeve.win_count,
                "enabled": sleeve.enabled,
            })
    except Exception as e:
        logger.error("persist_sleeves_error", error=str(e))


def _persist_snapshot(snap):
    """Persist equity snapshot."""
    try:
        from bahamut.execution.v7_persistence import persist_snapshot
        persist_snapshot({
            "timestamp": snap.timestamp,
            "total_equity": snap.total_equity,
            "total_realized_pnl": snap.total_realized_pnl,
            "total_unrealized_pnl": snap.total_unrealized_pnl,
            "total_open_risk": snap.total_open_risk,
            "drawdown": snap.drawdown,
            "sleeve_data": snap.sleeve_data,
        })
    except Exception as e:
        logger.error("persist_snapshot_error", error=str(e))


# ── Manual trigger (for testing without Celery) ──

def run_v7_cycle_sync():
    """Run the v7 cycle synchronously — bypasses Celery and Redis lock."""
    from bahamut.monitoring.cycle_log import start_cycle, end_cycle, get_last_cycle

    cycle = start_cycle()
    try:
        _run_v7_cycle_inner()
        end_cycle("SUCCESS")
        result = {"status": "SUCCESS", "cycle_id": cycle.cycle_id}
    except Exception as e:
        end_cycle("ERROR", error=str(e))
        result = {"status": "ERROR", "error": str(e)}

    # Send cycle report email
    try:
        from bahamut.monitoring.alerts import send_cycle_report
        lc = get_last_cycle()
        has_new_bar = any(a.get("new_bar") for a in lc.get("assets", []))
        if has_new_bar or lc.get("status") == "ERROR":
            send_cycle_report(lc)
    except Exception:
        pass

    return result
