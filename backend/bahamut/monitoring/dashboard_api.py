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


@router.get("/health")
async def system_health(user=Depends(get_current_user)):
    """Full system health check."""
    engine = get_execution_engine()
    pm = get_portfolio_manager()

    from bahamut.monitoring.telegram import is_configured as tg_ok
    from bahamut.monitoring.email import is_configured as em_ok

    try:
        from bahamut.config_assets import ACTIVE_TREND_ASSETS
        assets = ACTIVE_TREND_ASSETS
    except ImportError:
        assets = ["BTCUSD"]

    return {
        "status": "ok",
        "mode": "paper",
        "assets": assets,
        "strategies": list(pm.sleeves.keys()),
        "kill_switch": pm.kill_switch_triggered,
        "open_positions": len(engine.open_positions),
        "total_trades": len(engine.closed_trades),
        "equity": round(pm.total_equity, 2),
        "regimes": dict(getattr(pm, 'asset_regimes', {})),
        "telegram_configured": tg_ok(),
        "email_configured": em_ok(),
    }
