"""
Bahamut v7 Dashboard API

Routes for the trader operations dashboard:
  /v7/portfolio/summary — full portfolio overview
  /v7/portfolio/sleeves — per-strategy breakdown
  /v7/portfolio/equity-curve — equity snapshots
  /v7/execution/open-positions — live open trades
  /v7/execution/closed-trades — historical trades
  /v7/execution/orders — all orders
  /v7/execution/stats — execution engine stats
  /v7/portfolio/rebalance — rebalance sleeves
  /v7/portfolio/kill-switch — emergency stop
  /v7/strategies/{name}/enable — enable strategy
  /v7/strategies/{name}/disable — disable strategy
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from bahamut.portfolio.manager import get_portfolio_manager
from bahamut.execution.engine import get_execution_engine

router = APIRouter()


# ═══════════════════════════════════════════════════════
# PORTFOLIO
# ═══════════════════════════════════════════════════════

@router.get("/portfolio/summary")
async def portfolio_summary():
    pm = get_portfolio_manager()
    return pm.get_summary()


@router.get("/portfolio/sleeves")
async def portfolio_sleeves():
    pm = get_portfolio_manager()
    pm.update()
    return {
        name: {
            "strategy_name": s.strategy_name,
            "allocation_pct": round(s.allocation_weight * 100, 1),
            "initial_capital": s.initial_capital,
            "current_equity": s.current_equity,
            "realized_pnl": s.realized_pnl,
            "unrealized_pnl": s.unrealized_pnl,
            "peak_equity": s.peak_equity,
            "drawdown_pct": round(s.drawdown * 100, 2),
            "trades": s.trade_count,
            "wins": s.win_count,
            "win_rate": round(s.win_count / max(1, s.trade_count) * 100, 1),
            "enabled": s.enabled,
        }
        for name, s in pm.sleeves.items()
    }


@router.get("/portfolio/equity-curve")
async def equity_curve():
    pm = get_portfolio_manager()
    return [
        {
            "timestamp": snap.timestamp,
            "equity": snap.total_equity,
            "drawdown_pct": round(snap.drawdown * 100, 2),
            "sleeves": snap.sleeve_data,
        }
        for snap in pm.snapshots[-500:]  # Last 500 snapshots
    ]


# ═══════════════════════════════════════════════════════
# EXECUTION
# ═══════════════════════════════════════════════════════

@router.get("/execution/open-positions")
async def open_positions():
    return get_execution_engine().get_open_positions_list()


@router.get("/execution/closed-trades")
async def closed_trades():
    return get_execution_engine().get_closed_trades_list()


@router.get("/execution/orders")
async def all_orders():
    engine = get_execution_engine()
    return [
        {
            "order_id": o.order_id, "strategy": o.strategy, "asset": o.asset,
            "direction": o.direction, "status": o.status.value,
            "signal_time": o.signal_time, "fill_time": o.fill_time,
            "entry_price": o.entry_price, "stop_price": o.stop_price,
            "tp_price": o.tp_price, "size": o.size,
            "risk_amount": o.risk_amount,
        }
        for o in engine.all_orders[-100:]  # Last 100
    ]


@router.get("/execution/stats")
async def execution_stats():
    return get_execution_engine().get_stats()


# ═══════════════════════════════════════════════════════
# CONTROLS
# ═══════════════════════════════════════════════════════

class RebalanceRequest(BaseModel):
    weights: Optional[dict[str, float]] = None


@router.post("/portfolio/rebalance")
async def rebalance(req: RebalanceRequest = None):
    pm = get_portfolio_manager()
    pm.rebalance(req.weights if req else None)
    return {"status": "rebalanced", "sleeves": {
        n: s.allocation_weight for n, s in pm.sleeves.items()
    }}


@router.post("/portfolio/kill-switch")
async def kill_switch():
    pm = get_portfolio_manager()
    engine = get_execution_engine()
    # Use last known price or 0 to close at market
    price = 0
    for pos in engine.open_positions:
        price = pos.current_price
        break
    closed = engine.activate_kill_switch(price or 0)
    pm.kill_switch_triggered = True
    return {"status": "kill_switch_activated", "positions_closed": closed}


@router.post("/portfolio/resume")
async def resume_trading():
    pm = get_portfolio_manager()
    engine = get_execution_engine()
    engine.resume_trading()
    pm.kill_switch_triggered = False
    return {"status": "trading_resumed"}


@router.post("/strategies/{name}/enable")
async def enable_strategy(name: str):
    pm = get_portfolio_manager()
    if name not in pm.sleeves:
        raise HTTPException(404, f"Strategy '{name}' not found")
    pm.enable_strategy(name)
    return {"status": "enabled", "strategy": name}


@router.post("/strategies/{name}/disable")
async def disable_strategy(name: str):
    pm = get_portfolio_manager()
    if name not in pm.sleeves:
        raise HTTPException(404, f"Strategy '{name}' not found")
    pm.disable_strategy(name)
    return {"status": "disabled", "strategy": name}


# ═══════════════════════════════════════════════════════
# MANUAL TRIGGER + DB HISTORY
# ═══════════════════════════════════════════════════════

@router.post("/orchestrator/run-cycle")
async def manual_run_cycle():
    """Manually trigger one v7 trading cycle (for testing)."""
    try:
        from bahamut.execution.v7_orchestrator import run_v7_cycle_sync
        run_v7_cycle_sync()
        return {"status": "cycle_completed"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.get("/history/trades")
async def db_trade_history():
    """Load trade history from DB (persisted across restarts)."""
    try:
        from bahamut.execution.v7_persistence import load_trades_from_db
        return load_trades_from_db()
    except Exception as e:
        return {"error": str(e), "trades": []}


@router.get("/history/equity-curve")
async def db_equity_curve():
    """Load equity curve from DB snapshots."""
    try:
        from bahamut.execution.v7_persistence import load_snapshots_from_db
        return load_snapshots_from_db(limit=500)
    except Exception as e:
        return {"error": str(e), "snapshots": []}


@router.get("/health")
async def v7_health():
    """Health check for v7 trading system."""
    engine = get_execution_engine()
    pm = get_portfolio_manager()
    return {
        "status": "ok",
        "mode": "paper",
        "kill_switch": pm.kill_switch_triggered,
        "strategies": {
            name: {
                "enabled": s.enabled,
                "equity": s.current_equity,
            }
            for name, s in pm.sleeves.items()
        },
        "open_positions": len(engine.open_positions),
        "pending_orders": len(engine.pending_orders),
        "total_closed": len(engine.closed_trades),
    }

