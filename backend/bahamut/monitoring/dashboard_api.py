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
import structlog
from fastapi import APIRouter, Depends

from bahamut.execution.engine import get_execution_engine
from bahamut.portfolio.manager import get_portfolio_manager
from bahamut.auth.router import get_current_user

logger = structlog.get_logger()
router = APIRouter()


@router.get("/portfolio")
async def portfolio_summary(user=Depends(get_current_user)):
    """Core portfolio metrics — the numbers that matter."""
    engine = get_execution_engine()
    pm = get_portfolio_manager()
    pm.update()

    equity = pm.total_equity
    initial = pm.initial_capital
    pnl_total = equity - initial
    dd_pct = round((1 - equity / pm.peak_equity) * 100 if pm.peak_equity > 0 else 0, 2)
    max_dd = round(max(dd_pct, getattr(pm, '_max_dd_seen', dd_pct)), 2)
    open_risk = sum(p.risk_amount for p in engine.open_positions)
    open_risk_pct = round(open_risk / max(1, equity) * 100, 2)

    # Per-asset regimes
    regimes = getattr(pm, 'asset_regimes', {})

    return {
        "equity": round(equity, 2),
        "initial_capital": round(initial, 2),
        "pnl_total": round(pnl_total, 2),
        "return_pct": round(pnl_total / max(1, initial) * 100, 2),
        "drawdown_pct": dd_pct,
        "max_drawdown_pct": max_dd,
        "open_risk": round(open_risk, 2),
        "open_risk_pct": open_risk_pct,
        "open_positions": len(engine.open_positions),
        "total_trades": len(engine.closed_trades),
        "kill_switch": pm.kill_switch_triggered,
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

    return {"trades": trades, "count": len(engine.closed_trades)}


@router.get("/execution")
async def execution_quality(user=Depends(get_current_user)):
    """Execution quality metrics."""
    engine = get_execution_engine()

    # Calculate average slippage from closed trades
    slippages = []
    for t in engine.closed_trades:
        if t.entry_price > 0:
            slip = abs(t.entry_price - round(t.entry_price)) / t.entry_price * 10000
            slippages.append(slip)

    # Count states
    total_signals = len(engine._processed_signals) if hasattr(engine, '_processed_signals') else 0
    cancelled = len([o for o in engine.all_orders
                     if hasattr(o, 'status') and str(o.status) == "OrderStatus.CANCELLED"])

    return {
        "total_signals_processed": total_signals,
        "total_orders": len(engine.all_orders),
        "cancelled_orders": cancelled,
        "closed_trades": len(engine.closed_trades),
        "open_positions": len(engine.open_positions),
        "pending_orders": len(engine.pending_orders),
        "avg_slippage_bps": round(sum(slippages) / max(1, len(slippages)), 1) if slippages else 0,
        "kill_switch": engine.is_kill_switch_active,
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
        "regimes": dict(getattr(pm, 'asset_regimes', {})),
        "data": data_status_map,
        "portfolio": {
            "equity": round(pm.total_equity, 2),
            "kill_switch": pm.kill_switch_triggered,
            "open_positions": len(engine.open_positions),
            "total_trades": len(engine.closed_trades),
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

    # Portfolio
    dd_pct = round((1 - equity / pm.peak_equity) * 100 if pm.peak_equity > 0 else 0, 2)
    open_risk = sum(p.risk_amount for p in engine.open_positions)
    portfolio = {
        "equity": round(equity, 2),
        "pnl_total": round(equity - initial, 2),
        "return_pct": round((equity - initial) / max(1, initial) * 100, 2),
        "drawdown_pct": dd_pct,
        "open_risk_pct": round(open_risk / max(1, equity) * 100, 2),
        "open_positions": len(engine.open_positions),
        "total_trades": len(engine.closed_trades),
        "kill_switch": pm.kill_switch_triggered,
        "regime": dict(getattr(pm, 'asset_regimes', {})),
    }

    # Strategies
    strats = {}
    for name, sleeve in pm.sleeves.items():
        trades = [t for t in engine.closed_trades if t.strategy == name]
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

    # Positions
    positions = []
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

    # Timing
    from bahamut.monitoring.time_utils import (
        next_4h_close_utc, seconds_until_next_4h_close, get_asset_timing
    )
    from bahamut.data.live_data import get_last_bar_timestamp
    from datetime import datetime as _dt, timezone as _tz

    now_utc = _dt.now(_tz.utc)
    asset_timing = {}
    try:
        from bahamut.config_assets import ACTIVE_TREND_ASSETS
        timing_assets = ACTIVE_TREND_ASSETS
    except ImportError:
        timing_assets = ["BTCUSD"]
    for a in timing_assets:
        lbt = get_last_bar_timestamp(a)
        asset_timing[a] = get_asset_timing(lbt)

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

    return {
        "portfolio": portfolio,
        "strategies": strats,
        "positions": {"positions": positions, "count": len(positions)},
        "trades": {"trades": recent_trades, "count": len(engine.closed_trades)},
        "alerts": alerts,
        "last_cycle": last_cycle,
        "cycle_history": cycle_hist,
        "cycle_stats": cycle_stats,
        "timing": timing,
        "strategy_conditions": strategy_conds,
        "health": {
            "engine": "v7/v8/v9", "data_source": data_src, "data": data_status,
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
