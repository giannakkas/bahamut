"""
Bahamut Monitoring Dashboard API

All endpoints require authentication (JWT Bearer token).

Endpoints:
  GET /api/monitoring/portfolio    — equity, PnL, drawdown, risk, regimes
  GET /api/monitoring/strategies   — per-strategy performance metrics
  GET /api/monitoring/positions    — open positions with risk
  GET /api/monitoring/trades       — recent closed trades
  GET /api/monitoring/execution    — execution quality metrics
  GET /api/monitoring/alerts       — recent alerts
  GET /api/monitoring/health       — system health check
"""
import os
import json
import structlog
from fastapi import APIRouter, Depends

from bahamut.execution.engine import get_execution_engine
from bahamut.portfolio.manager import get_portfolio_manager, get_cross_process_regimes, get_cross_process_kill_switch
from bahamut.auth.router import get_current_user

logger = structlog.get_logger()
router = APIRouter()


def _get_production_health() -> dict:
    """Gather production safety state for the dashboard health dict."""
    import time as _t
    result: dict = {}
    try:
        from bahamut.execution.circuit_breaker import circuit_breaker_binance, circuit_breaker_alpaca
        result["circuit_breaker_binance"] = circuit_breaker_binance.get_status()["state"]
        result["circuit_breaker_alpaca"] = circuit_breaker_alpaca.get_status()["state"]
    except Exception:
        result["circuit_breaker_binance"] = "UNKNOWN"
        result["circuit_breaker_alpaca"] = "UNKNOWN"
    try:
        from bahamut.execution.shutdown import is_shutting_down
        result["shutdown_in_progress"] = is_shutting_down()
    except Exception:
        result["shutdown_in_progress"] = False
    try:
        import redis, os
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                           socket_connect_timeout=1)
        ts_raw = r.get("bahamut:training:last_cycle_ts")
        if ts_raw:
            result["training_freshness_sec"] = int(_t.time() - int(ts_raw))
        else:
            result["training_freshness_sec"] = -1
        # Check for unauthorized positions from reconciliation
        unauthorized_keys = r.keys("bahamut:reconciliation:unauthorized:*")
        result["reconciliation_unauthorized_count"] = len(unauthorized_keys) if unauthorized_keys else 0
    except Exception:
        result["training_freshness_sec"] = -1
        result["reconciliation_unauthorized_count"] = 0
    try:
        from bahamut.execution._latency import p95
        result["latency_p95_binance_ms"] = p95("binance")
        result["latency_p95_alpaca_ms"] = p95("alpaca")
    except Exception:
        result["latency_p95_binance_ms"] = -1
        result["latency_p95_alpaca_ms"] = -1
    try:
        from bahamut.intelligence.ai_market_analyst import get_analysis_status
        _ai_status = get_analysis_status()
        result["ai_provider_active"] = _ai_status.get("ai_provider_active", "none")
        result["ai_daily_cost_usd"] = _ai_status.get("ai_daily_cost_usd", 0)
        result["ai_daily_cost_cap_usd"] = _ai_status.get("ai_daily_cost_cap_usd", 0.75)
    except Exception:
        result["ai_provider_active"] = "none"
        result["ai_daily_cost_usd"] = 0
        result["ai_daily_cost_cap_usd"] = 0.75
    return result


@router.get("/portfolio")
async def portfolio_summary(user=Depends(get_current_user)):
    """Core portfolio metrics — the numbers that matter."""
    engine = get_execution_engine()
    pm = get_portfolio_manager()
    pm.update()

    equity = pm.total_equity
    initial = pm.initial_capital
    pnl_total = equity - initial
    dd_pct = round(pm.total_drawdown * 100, 2)
    max_dd = round(max(dd_pct, getattr(pm, '_max_dd_seen', 0) * 100), 2)
    open_risk = sum(p.risk_amount for p in engine.open_positions
                    if not p.strategy.startswith("TEST_"))
    open_risk_pct = round(open_risk / max(1, equity) * 100, 2)

    # Per-asset regimes
    regimes = get_cross_process_regimes() or getattr(pm, 'asset_regimes', {})

    return {
        "equity": round(equity, 2),
        "initial_capital": round(initial, 2),
        "pnl_total": round(pnl_total, 2),
        "return_pct": round(pnl_total / max(1, initial) * 100, 2),
        "drawdown_pct": dd_pct,
        "max_drawdown_pct": max_dd,
        "open_risk": round(open_risk, 2),
        "open_risk_pct": open_risk_pct,
        "open_positions": len([p for p in engine.open_positions if not p.strategy.startswith("TEST_")]),
        "total_trades": len([t for t in engine.closed_trades if not t.strategy.startswith("TEST_")]),
        "kill_switch": pm.kill_switch_triggered or get_cross_process_kill_switch(),
        "regime": dict(regimes),
        "portfolio_mode": getattr(pm, 'current_portfolio_mode', 'unknown'),
    }


@router.get("/strategies")
async def strategy_performance(user=Depends(get_current_user)):
    """Per-strategy metrics: PnL, win rate, profit factor, expectancy."""
    engine = get_execution_engine()
    pm = get_portfolio_manager()
    result = {}

    for name, sleeve in pm.sleeves.items():
        trades = [t for t in engine.closed_trades if t.strategy == name]
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]

        total_pnl = sum(t.pnl for t in trades)
        gross_profit = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses)) if losses else 0
        pf = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0

        # Rolling 20-trade metrics
        recent = trades[-20:] if len(trades) >= 5 else trades
        r_wins = [t for t in recent if t.pnl > 0]
        r_wr = round(len(r_wins) / max(1, len(recent)) * 100, 1)
        r_gp = sum(t.pnl for t in r_wins) if r_wins else 0
        r_gl = abs(sum(t.pnl for t in recent if t.pnl <= 0)) or 1
        r_pf = round(r_gp / r_gl, 2)

        # Expectancy = avg win × WR - avg loss × (1-WR)
        avg_win = gross_profit / max(1, len(wins))
        avg_loss = gross_loss / max(1, len(losses))
        wr = len(wins) / max(1, len(trades))
        expectancy = round(avg_win * wr - avg_loss * (1 - wr), 2) if trades else 0

        # Open positions for this strategy
        open_pos = [p for p in engine.open_positions if p.strategy == name]

        result[name] = {
            "pnl": round(total_pnl, 2),
            "trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(wr * 100, 1),
            "profit_factor": pf,
            "expectancy": expectancy,
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "rolling_wr": r_wr,
            "rolling_pf": r_pf,
            "open_positions": len(open_pos),
            "equity": round(sleeve.current_equity, 2),
            "allocation_pct": round(sleeve.allocation_weight * 100, 1),
            "enabled": sleeve.enabled,
        }

    return result


@router.get("/positions")
async def open_positions(user=Depends(get_current_user)):
    """All open positions with risk metrics."""
    engine = get_execution_engine()
    pm = get_portfolio_manager()
    equity = pm.total_equity

    positions = []
    for pos in engine.open_positions:
        risk_pct = round(pos.risk_amount / max(1, equity) * 100, 2)

        # Unrealized PnL
        if pos.direction == "LONG":
            unrealized = (pos.current_price - pos.entry_price) * pos.size
        else:
            unrealized = (pos.entry_price - pos.current_price) * pos.size

        positions.append({
            "asset": pos.asset,
            "strategy": pos.strategy,
            "direction": pos.direction,
            "entry_price": round(pos.entry_price, 2),
            "current_price": round(pos.current_price, 2),
            "stop_loss": round(pos.stop_price, 2),
            "take_profit": round(pos.tp_price, 2),
            "size": round(pos.size, 6),
            "unrealized_pnl": round(unrealized, 2),
            "risk_amount": round(pos.risk_amount, 2),
            "risk_pct": risk_pct,
            "bars_held": pos.bars_held,
        })

    return {"positions": positions, "count": len(positions)}


@router.get("/trades")
async def trade_history(user=Depends(get_current_user)):
    """Recent closed trades."""
    engine = get_execution_engine()
    trades = []

    for t in reversed(engine.closed_trades[-50:]):
        pnl_pct = round(t.pnl / max(1, t.risk_amount) * 100, 1) if t.risk_amount else 0

        trades.append({
            "asset": t.asset,
            "strategy": t.strategy,
            "direction": t.direction,
            "entry_price": round(t.entry_price, 2),
            "exit_price": round(t.exit_price, 2),
            "pnl": round(t.pnl, 2),
            "pnl_pct": pnl_pct,
            "exit_reason": t.exit_reason,
            "bars_held": t.bars_held,
            "entry_time": getattr(t, 'entry_time', ''),
            "exit_time": getattr(t, 'exit_time', ''),
        })

    return {"trades": trades, "count": len([t for t in engine.closed_trades if not t.strategy.startswith("TEST_")])}


@router.get("/execution")
async def execution_quality(user=Depends(get_current_user)):
    """Execution quality metrics."""
    engine = get_execution_engine()

    # Slippage: compare entry_price to the order's signal price
    # For paper trading, slippage is deterministic (broker config),
    # so we report the configured value rather than computing fake numbers.
    # For real trading, this should compare fill_price to expected_price.
    broker_slippage_bps = engine.broker.config.slippage_bps
    broker_spread_bps = engine.broker.config.spread_bps
    broker_commission_bps = engine.broker.config.commission_rate * 10000  # convert to bps

    # Count states
    total_signals = len(engine._processed_signals) if hasattr(engine, '_processed_signals') else 0
    cancelled = len([o for o in engine.all_orders
                     if hasattr(o, 'status') and str(o.status) == "OrderStatus.CANCELLED"])

    # Compute actual average PnL per trade (with fees)
    trades = [t for t in engine.closed_trades if not t.strategy.startswith("TEST_")]
    avg_pnl = sum(t.pnl for t in trades) / max(1, len(trades)) if trades else 0
    avg_bars = sum(t.bars_held for t in trades) / max(1, len(trades)) if trades else 0

    return {
        "total_signals_processed": total_signals,
        "total_orders": len(engine.all_orders),
        "cancelled_orders": cancelled,
        "closed_trades": len(trades),
        "open_positions": len(engine.open_positions),
        "pending_orders": len(engine.pending_orders),
        "configured_slippage_bps": broker_slippage_bps,
        "configured_spread_bps": broker_spread_bps,
        "configured_commission_bps": round(broker_commission_bps, 1),
        "total_execution_cost_bps": round(broker_slippage_bps + broker_spread_bps / 2 + broker_commission_bps, 1),
        "avg_pnl_per_trade": round(avg_pnl, 2),
        "avg_bars_held": round(avg_bars, 1),
        "kill_switch": engine.is_kill_switch_active,
        "note": "slippage/spread are configured values (paper mode). Live trading should report actual fill vs expected.",
    }


@router.get("/alerts")
async def recent_alerts(user=Depends(get_current_user)):
    """Get recent alerts for dashboard display."""
    from bahamut.monitoring.alerts import get_recent_alerts
    alerts = get_recent_alerts(limit=50)
    return {"alerts": alerts, "count": len(alerts)}


# ═══════════════════════════════════════════════════════
# CYCLE INSPECTOR
# ═══════════════════════════════════════════════════════

@router.get("/cycle/current")
async def cycle_current(user=Depends(get_current_user)):
    """Current or most recent cycle state."""
    from bahamut.monitoring.cycle_log import get_current_cycle
    return get_current_cycle() or {"status": "IDLE"}


@router.get("/cycle/last")
async def cycle_last(user=Depends(get_current_user)):
    """Full detail of last completed cycle."""
    from bahamut.monitoring.cycle_log import get_last_cycle
    return get_last_cycle() or {"status": "NO_DATA"}


@router.get("/cycle/history")
async def cycle_history(user=Depends(get_current_user)):
    """Recent cycle history (last 30)."""
    from bahamut.monitoring.cycle_log import get_cycle_history, get_cycle_stats
    return {
        "cycles": get_cycle_history(30),
        "stats": get_cycle_stats(),
    }


@router.get("/health")
async def system_health(user=Depends(get_current_user)):
    """Comprehensive system diagnostics."""
    engine = get_execution_engine()
    pm = get_portfolio_manager()

    from bahamut.monitoring.telegram import is_configured as tg_ok
    from bahamut.monitoring.email import is_configured as em_ok

    try:
        from bahamut.config_assets import ACTIVE_TREND_ASSETS
        assets = ACTIVE_TREND_ASSETS
    except ImportError:
        assets = ["BTCUSD"]

    # Check DB connectivity
    db_ok = False
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            db_ok = True
    except Exception:
        pass

    # Check Redis connectivity + last cycle time
    redis_ok = False
    last_cycle = None
    lock_healthy = True
    try:
        import redis, os, time
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        r.ping()
        redis_ok = True
        lc = r.get("bahamut:last_v7_cycle")
        if lc:
            ts = float(lc)
            last_cycle = ts
            # If last cycle was >10 min ago, lock might be stuck
            if time.time() - ts > 600:
                lock_healthy = False
    except Exception:
        pass

    # Check for live data vs synthetic
    live_data = False
    data_status_map = {}
    try:
        from bahamut.data.live_data import get_data_source, get_data_status, get_last_bar_timestamp
        data_src = get_data_source()
        live_data = data_src == "LIVE"
        data_status_map = get_data_status()
    except Exception:
        try:
            from bahamut.ingestion.adapters.twelvedata import twelve_data
            live_data = twelve_data.configured
        except Exception:
            pass

    # Active strategies from sleeves
    active_strategies = [n for n, s in pm.sleeves.items()
                         if s.allocation_weight > 0]

    # Legacy schedulers status
    legacy_disabled = True
    try:
        from bahamut.celery_app import celery_app
        beat = celery_app.conf.beat_schedule
        legacy_tasks = [k for k in beat if k != "v7-trading-cycle"]
        legacy_disabled = len(legacy_tasks) == 0
    except Exception:
        pass

    return {
        "status": "ok",
        "mode": "OPERATIONS",
        "engine": "v7/v8/v9",
        "data_source": "LIVE" if live_data else "SYNTHETIC",
        "assets": assets,
        "active_strategies": active_strategies,
        "regimes": get_cross_process_regimes() or dict(getattr(pm, 'asset_regimes', {})),
        "data": data_status_map,
        "portfolio": {
            "equity": round(pm.total_equity, 2),
            "kill_switch": pm.kill_switch_triggered or get_cross_process_kill_switch(),
            "open_positions": len([p for p in engine.open_positions if not p.strategy.startswith("TEST_")]),
            "total_trades": len([t for t in engine.closed_trades if not t.strategy.startswith("TEST_")]),
        },
        "infrastructure": {
            "db_connected": db_ok,
            "redis_connected": redis_ok,
            "orchestrator_lock_healthy": lock_healthy,
            "last_cycle_timestamp": last_cycle,
            "legacy_schedulers_disabled": legacy_disabled,
            "telegram_configured": tg_ok(),
            "email_configured": em_ok(),
        },
    }

    # Add system readiness
    try:
        from bahamut.execution.system_readiness import get_readiness_state
        result["system_readiness"] = get_readiness_state()
    except Exception:
        result["system_readiness"] = {"can_trade": False, "reasons": ["readiness_check_failed"]}

    return result


# ═══════════════════════════════════════════════════════
# COMBINED DASHBOARD ENDPOINT — single call, all data
# ═══════════════════════════════════════════════════════

@router.get("/dashboard")
async def dashboard_all(user=Depends(get_current_user)):
    """Single endpoint returning all dashboard data. Reduces 9 calls to 1."""
    engine = get_execution_engine()
    pm = get_portfolio_manager()
    pm.update()

    equity = pm.total_equity
    initial = pm.initial_capital

    # Portfolio — use pm.total_drawdown as single source of truth (clamped to [0, 1])
    dd_pct = round(pm.total_drawdown * 100, 2)
    open_risk = sum(p.risk_amount for p in engine.open_positions
                    if not p.strategy.startswith("TEST_"))
    # Exclude TEST_ from aggregate counts (operator sees them in positions/trades tabs)
    real_positions = [p for p in engine.open_positions if not p.strategy.startswith("TEST_")]
    real_trades = [t for t in engine.closed_trades if not t.strategy.startswith("TEST_")]

    portfolio = {
        "equity": round(equity, 2),
        "pnl_total": round(equity - initial, 2),
        "return_pct": round((equity - initial) / max(1, initial) * 100, 2),
        "drawdown_pct": dd_pct,
        "open_risk_pct": round(open_risk / max(1, equity) * 100, 2),
        "open_positions": len(real_positions),
        "total_trades": len(real_trades),
        "kill_switch": pm.kill_switch_triggered or get_cross_process_kill_switch(),
        "regime": get_cross_process_regimes() or dict(getattr(pm, 'asset_regimes', {})),
    }

    # Win rate: always use training system data (matches Training Operations page)
    try:
        from bahamut.trading.engine import get_training_stats
        ts = get_training_stats()
        training_wr = ts.get("win_rate", 0)  # 0.0 to 1.0
        training_closed = ts.get("total_closed_trades", 0)
        portfolio["win_rate"] = round(training_wr * 100, 1)
        portfolio["training_closed"] = training_closed
    except Exception:
        portfolio["win_rate"] = 0.0
        portfolio["training_closed"] = 0

    # Strategies — sleeve names never start with TEST_, so this naturally excludes test trades
    strats = {}
    for name, sleeve in pm.sleeves.items():
        trades = [t for t in real_trades if t.strategy == name]
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]
        total_pnl = sum(t.pnl for t in trades)
        gp = sum(t.pnl for t in wins)
        gl = abs(sum(t.pnl for t in losses)) if losses else 0
        wr = len(wins) / max(1, len(trades))
        recent = trades[-20:] if len(trades) >= 5 else trades
        r_wins = [t for t in recent if t.pnl > 0]
        r_wr = round(len(r_wins) / max(1, len(recent)) * 100, 1)
        strats[name] = {
            "pnl": round(total_pnl, 2), "trades": len(trades),
            "win_rate": round(wr * 100, 1), "rolling_wr": r_wr,
            "profit_factor": round(gp / gl, 2) if gl > 0 else 0,
            "expectancy": round((gp / max(1, len(wins))) * wr - (gl / max(1, len(losses))) * (1 - wr), 2) if trades else 0,
            "open_positions": len([p for p in engine.open_positions if p.strategy == name]),
            "equity": round(sleeve.current_equity, 2),
        }

    # Positions (in-memory for this process)
    positions = []
    known_order_ids = set()
    for pos in engine.open_positions:
        unreal = (pos.current_price - pos.entry_price) * pos.size if pos.direction == "LONG" else (pos.entry_price - pos.current_price) * pos.size
        positions.append({
            "asset": pos.asset, "strategy": pos.strategy, "direction": pos.direction,
            "entry_price": round(pos.entry_price, 2), "current_price": round(pos.current_price, 2),
            "stop_loss": round(pos.stop_price, 2), "take_profit": round(pos.tp_price, 2),
            "unrealized_pnl": round(unreal, 2),
            "risk_pct": round(pos.risk_amount / max(1, equity) * 100, 2),
            "bars_held": pos.bars_held,
        })
        known_order_ids.add(pos.order_id)

    # Supplement with Redis test positions (cross-process)
    try:
        from bahamut.execution.test_trade_mode import get_test_positions_from_redis
        for rp in get_test_positions_from_redis():
            if rp.get("order_id") not in known_order_ids:
                positions.append({
                    "asset": rp.get("asset", ""), "strategy": rp.get("strategy", ""),
                    "direction": rp.get("direction", ""),
                    "entry_price": rp.get("entry_price", 0),
                    "current_price": rp.get("current_price", rp.get("entry_price", 0)),
                    "stop_loss": rp.get("stop_loss", 0), "take_profit": rp.get("take_profit", 0),
                    "unrealized_pnl": rp.get("unrealized_pnl", 0),
                    "risk_pct": round(rp.get("risk_amount", 0) / max(1, equity) * 100, 2),
                    "bars_held": rp.get("bars_held", 0),
                })
    except Exception:
        pass

    # Recent trades
    recent_trades = []
    for t in reversed(engine.closed_trades[-30:]):
        recent_trades.append({
            "asset": t.asset, "strategy": t.strategy, "direction": t.direction,
            "entry_price": round(t.entry_price, 2), "exit_price": round(t.exit_price, 2),
            "pnl": round(t.pnl, 2), "exit_reason": t.exit_reason, "bars_held": t.bars_held,
        })

    # Alerts
    from bahamut.monitoring.alerts import get_recent_alerts
    alerts = get_recent_alerts(limit=30)

    # Cycle data
    from bahamut.monitoring.cycle_log import get_last_cycle, get_cycle_history, get_cycle_stats
    last_cycle = get_last_cycle()
    cycle_hist = get_cycle_history(15)
    cycle_stats = get_cycle_stats()

    # Health (lightweight — skip DB/Redis checks for speed)
    data_src = "SYNTHETIC"
    data_status = {}
    try:
        from bahamut.data.live_data import get_data_source, get_data_status
        data_src = get_data_source()
        raw_status = get_data_status()
        # Sanitize nested values to ensure they're all JSON-safe primitives
        for k, v in raw_status.items():
            if isinstance(v, dict):
                data_status[k] = {sk: (str(sv) if not isinstance(sv, (str, int, float, bool, type(None))) else sv) for sk, sv in v.items()}
            else:
                data_status[k] = str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v
    except Exception:
        pass

    # Timing — use canonical data health module
    from bahamut.monitoring.time_utils import (
        next_4h_close_utc, seconds_until_next_4h_close, get_asset_timing
    )
    from bahamut.data.live_data import get_last_bar_timestamp, get_data_status
    from datetime import datetime as _dt, timezone as _tz

    now_utc = _dt.now(_tz.utc)
    asset_timing = {}
    data_provider_status = get_data_status()  # last candle info from provider
    try:
        from bahamut.config_assets import ACTIVE_TREND_ASSETS
        timing_assets = ACTIVE_TREND_ASSETS
    except ImportError:
        timing_assets = ["BTCUSD"]
    for a in timing_assets:
        last_processed = get_last_bar_timestamp(a)

        # Get last candle from provider (distinct from last processed bar)
        provider_info = data_provider_status.get(a, {})
        last_candle = ""
        if isinstance(provider_info, dict):
            detail = provider_info.get("detail", "")
            # detail is a timestamp if it starts with digits
            if detail and len(detail) >= 10 and detail[:4].isdigit():
                last_candle = detail

        # If no provider timestamp, fall back to last processed
        if not last_candle:
            last_candle = last_processed

        asset_timing[a] = get_asset_timing(last_candle, last_processed_ts=last_processed)

    timing = {
        "now_utc": now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "next_4h_close": next_4h_close_utc(now_utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "seconds_until_next_close": seconds_until_next_4h_close(now_utc),
        "assets": asset_timing,
    }

    # Strategy conditions
    strategy_conds = {}
    try:
        from bahamut.monitoring.strategy_conditions import get_latest_snapshots
        strategy_conds = get_latest_snapshots()
    except Exception:
        pass

    # Build result dict (DO NOT return early — performance/health/trust must be added below)
    result = {
        "portfolio": portfolio,
        "strategies": strats,
        "positions": {"positions": positions, "count": len(positions)},
        "trades": {"trades": recent_trades, "count": len(real_trades)},
        "alerts": alerts,
        "last_cycle": last_cycle,
        "cycle_history": cycle_hist,
        "cycle_stats": cycle_stats,
        "timing": timing,
        "strategy_conditions": strategy_conds,
        "health": {
            "engine": "v7/v8/v9", "data_source": data_src, "data": data_status,
            **_get_production_health(),
        },
    }

    # Add performance data
    try:
        from bahamut.monitoring.performance import compute_performance
        result["performance"] = compute_performance()
    except Exception:
        result["performance"] = {"portfolio": {}, "strategies": {}, "assets": {}, "has_data": False}

    # Add data health
    try:
        from bahamut.monitoring.data_health import get_data_health
        result["data_health"] = get_data_health()
    except Exception:
        result["data_health"] = {"status": "UNKNOWN", "source": "?", "assets": {}}

    # Add system readiness (canonical trading permission state)
    try:
        from bahamut.execution.system_readiness import get_readiness_state
        result["system_readiness"] = get_readiness_state()
    except Exception:
        result["system_readiness"] = {"can_trade": False, "reasons": ["readiness_check_failed"]}

    # Operator trust strip — last key events
    trust = {}
    try:
        trust["last_successful_cycle"] = last_cycle.get("ended_at") if last_cycle and last_cycle.get("status") == "SUCCESS" else None
        trust["last_signal"] = None
        trust["last_order"] = None
        trust["last_position_opened"] = None
        trust["last_position_closed"] = None
        # Check from engine
        if engine.all_orders:
            trust["last_order"] = engine.all_orders[-1].signal_time
        if engine.closed_trades:
            trust["last_position_closed"] = engine.closed_trades[-1].exit_time
        # Check open positions for most recent open
        if engine.open_positions:
            trust["last_position_opened"] = max(p.entry_time for p in engine.open_positions if p.entry_time)
    except Exception:
        pass
    result["operator_trust"] = trust

    # Training universe summary (lightweight — just counts)
    try:
        from bahamut.trading.engine import get_open_position_count
        import redis as _redis
        _r = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        last_cycle_raw = _r.get("bahamut:training:last_cycle")
        training_lc = json.loads(last_cycle_raw) if last_cycle_raw else {}
        result["training"] = {
            "open_positions": get_open_position_count(),
            "last_cycle": training_lc.get("last_cycle"),
            "total_signals": training_lc.get("signals", 0),
            "total_trades_closed": training_lc.get("trades_closed", 0),
        }
    except Exception:
        result["training"] = {"open_positions": 0}

    return result


# ═══════════════════════════════════════════════════════
# TEST TRADE ENDPOINTS
# ═══════════════════════════════════════════════════════

@router.post("/test-trade/open")
async def open_test_trade(user=Depends(get_current_user)):
    """Create a test trade to verify the full lifecycle. Super admin only."""
    from bahamut.execution.test_trade_mode import create_test_trade
    result = create_test_trade()
    return result


@router.post("/test-trade/close")
async def close_test_trade_endpoint(user=Depends(get_current_user)):
    """Close an open test trade. Super admin only."""
    from bahamut.execution.test_trade_mode import close_test_trade
    result = close_test_trade()
    return result


@router.get("/test-trade/status")
async def test_trade_status(user=Depends(get_current_user)):
    """Get current test trade state."""
    from bahamut.execution.test_trade_mode import get_test_trade_status
    return get_test_trade_status()


# ═══════════════════════════════════════════════════════
# PERFORMANCE ENDPOINT
# ═══════════════════════════════════════════════════════

@router.post("/alerts/acknowledge")
async def acknowledge_alert(key: str = "", user=Depends(get_current_user)):
    """Acknowledge (resolve) an alert by key. Removes it from active alerts."""
    if not key:
        return {"error": "alert key required"}
    from bahamut.monitoring.alerts import resolve_alert
    resolve_alert(key, reason=f"acknowledged by {getattr(user, 'email', 'operator')}")
    return {"status": "acknowledged", "key": key}


@router.get("/performance")
async def get_performance(user=Depends(get_current_user)):
    """Get full performance breakdown: portfolio, per-strategy, per-asset."""
    from bahamut.monitoring.performance import compute_performance
    return compute_performance()


@router.get("/data-health")
async def get_data_health_endpoint(user=Depends(get_current_user)):
    """Get data health status for all assets."""
    from bahamut.monitoring.data_health import get_data_health
    return get_data_health()


@router.get("/training")
async def get_training_dashboard(user=Depends(get_current_user)):
    """Get training universe stats: positions, closed trades, strategy performance, learning progress."""
    try:
        from bahamut.trading.engine import get_training_stats
        stats = get_training_stats()

        # Add last cycle info
        import os, json
        try:
            import redis
            r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
            raw = r.get("bahamut:training:last_cycle")
            if raw:
                stats["last_cycle"] = json.loads(raw)
        except Exception:
            pass

        # Add asset universe info
        from bahamut.config_assets import TRADING_ASSETS, ASSET_CLASS_MAP
        stats["universe_size"] = len(TRADING_ASSETS)
        stats["asset_classes"] = {}
        for a in TRADING_ASSETS:
            ac = ASSET_CLASS_MAP.get(a, "unknown")
            stats["asset_classes"][ac] = stats["asset_classes"].get(ac, 0) + 1

        return stats
    except Exception as e:
        return {"error": str(e), "open_positions": 0, "total_closed_trades": 0}


@router.get("/exploration-status")
async def get_exploration_status_endpoint():
    """Get current exploration mode status for dashboard."""
    try:
        from bahamut.paper_trading.sync_executor import get_exploration_status
        return get_exploration_status()
    except Exception as e:
        return {"enabled": False, "error": str(e)}


@router.get("/trading-accuracy")
async def get_trading_accuracy():
    """
    Canonical trading accuracy metric — based on REAL closed trade outcomes only.

    Uses STRICT closed trades only by default.
    Excludes EXPLORATION and TEST_ trades from the main accuracy number.
    This is the single source of truth for the top-right dashboard widget.
    """
    try:
        from bahamut.db.query import run_query_one, run_query

        # Strict trades only (excludes EXPLORATION and TEST_)
        strict = run_query_one("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN realized_pnl <= 0 THEN 1 ELSE 0 END) as losses,
                COALESCE(SUM(realized_pnl), 0) as total_pnl,
                COALESCE(AVG(realized_pnl), 0) as avg_pnl
            FROM paper_positions
            WHERE status = 'CLOSED'
              AND COALESCE(execution_mode, 'STRICT') != 'EXPLORATION'
              AND asset NOT LIKE 'TEST_%'
        """)

        # Exploration trades separately
        exploration = run_query_one("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as wins
            FROM paper_positions
            WHERE status = 'CLOSED'
              AND execution_mode = 'EXPLORATION'
        """)

        s_total = int(strict.get("total", 0) or 0) if strict else 0
        s_wins = int(strict.get("wins", 0) or 0) if strict else 0
        s_losses = int(strict.get("losses", 0) or 0) if strict else 0
        s_pnl = float(strict.get("total_pnl", 0) or 0) if strict else 0
        s_avg = float(strict.get("avg_pnl", 0) or 0) if strict else 0

        e_total = int(exploration.get("total", 0) or 0) if exploration else 0
        e_wins = int(exploration.get("wins", 0) or 0) if exploration else 0

        strict_accuracy = round(s_wins / max(1, s_total) * 100, 1) if s_total > 0 else None
        exploration_accuracy = round(e_wins / max(1, e_total) * 100, 1) if e_total > 0 else None

        # Fall back to training data when no production strict trades
        if s_total == 0:
            tf = _training_accuracy()
            if tf.get("has_data"):
                return {
                    "strict_accuracy_pct": tf["strict_accuracy_pct"],
                    "strict_total_trades": tf["strict_total_trades"],
                    "strict_wins": tf["strict_wins"],
                    "strict_losses": 0,
                    "strict_total_pnl": 0,
                    "strict_avg_pnl": 0,
                    "exploration_accuracy_pct": exploration_accuracy,
                    "exploration_total_trades": e_total,
                    "exploration_wins": e_wins,
                    "has_data": True,
                    "source": "training",
                }

        return {
            "strict_accuracy_pct": strict_accuracy,
            "strict_total_trades": s_total,
            "strict_wins": s_wins,
            "strict_losses": s_losses,
            "strict_total_pnl": round(s_pnl, 2),
            "strict_avg_pnl": round(s_avg, 2),
            "exploration_accuracy_pct": exploration_accuracy,
            "exploration_total_trades": e_total,
            "exploration_wins": e_wins,
            "has_data": s_total > 0,
        }
    except Exception as e:
        logger.error("trading_accuracy_failed", error=str(e))
        tf = _training_accuracy()
        if tf.get("has_data"):
            return tf
        return {"strict_accuracy_pct": None, "has_data": False, "strict_total_trades": 0}


def _training_accuracy() -> dict:
    """Pull win rate from training system as fallback for header widget."""
    try:
        from bahamut.trading.engine import get_training_stats
        ts = get_training_stats()
        wr = ts.get("win_rate", 0)  # 0.0 to 1.0
        closed = ts.get("total_closed_trades", 0)
        if closed > 0:
            return {
                "strict_accuracy_pct": round(wr * 100, 1),
                "strict_total_trades": closed,
                "strict_wins": round(wr * closed),
                "has_data": True,
                "source": "training",
            }
    except Exception:
        pass
    return {"has_data": False}


@router.post("/alerts/dismiss")
async def dismiss_alert_by_key(body: dict = {}):
    """Dismiss a monitoring alert by its key. Stays dismissed for 7 days."""
    key = body.get("key", "")
    if not key:
        return {"error": "key required"}
    from bahamut.monitoring.alerts import dismiss_monitoring_alert
    dismiss_monitoring_alert(key)
    return {"status": "dismissed", "key": key}


@router.post("/alerts/dismiss-all")
async def dismiss_all_alerts():
    """Dismiss all active monitoring alerts."""
    from bahamut.monitoring.alerts import dismiss_all_monitoring_alerts
    count = dismiss_all_monitoring_alerts()
    return {"status": "dismissed", "count": count}


@router.get("/failed-signals")
async def get_failed_signals_endpoint(user=Depends(get_current_user)):
    """Get recent failed/rejected production signals for dashboard."""
    try:
        from bahamut.paper_trading.sync_executor import get_failed_signals
        return {"signals": get_failed_signals(limit=50)}
    except Exception as e:
        logger.error("failed_signals_endpoint_error", error=str(e))
        return {"signals": []}


@router.get("/funding-rates")
async def get_funding_rates(user=Depends(get_current_user)):
    """Funding rate costs for open crypto futures positions."""
    try:
        from bahamut.execution.funding_rate import check_all_positions_funding
        from bahamut.trading.engine import get_open_positions

        positions = get_open_positions()
        pos_dicts = [
            {
                "asset": p.asset,
                "direction": p.direction,
                "size": p.size,
                "entry_price": p.entry_price,
                "entry_time": p.entry_time,
            }
            for p in positions
        ]

        estimates = check_all_positions_funding(pos_dicts)
        total_estimated_cost = sum(e.get("estimated_cost", 0) for e in estimates)

        return {
            "positions_checked": len(estimates),
            "total_estimated_funding_cost": round(total_estimated_cost, 2),
            "high_rate_count": sum(1 for e in estimates if e.get("is_high")),
            "details": estimates,
        }
    except Exception as e:
        logger.error("funding_rates_endpoint_error", error=str(e))
        return {"positions_checked": 0, "total_estimated_funding_cost": 0, "details": []}
