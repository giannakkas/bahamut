"""
Bahamut Performance Engine

Computes portfolio-level, per-strategy, and per-asset performance metrics
from the ExecutionEngine's in-memory trade records.

All calculations are deterministic and safe for empty states.
"""
import structlog
from bahamut.execution.engine import get_execution_engine
from bahamut.portfolio.manager import get_portfolio_manager

logger = structlog.get_logger()


def compute_performance() -> dict:
    """
    Compute full performance breakdown.

    Returns:
        {
            "portfolio": { ... },
            "strategies": { "v5_base": { ... }, ... },
            "assets": { "BTCUSD": { ... }, ... },
            "has_data": bool,
        }
    """
    engine = get_execution_engine()
    pm = get_portfolio_manager()
    trades = engine.closed_trades
    positions = engine.open_positions

    has_data = len(trades) > 0 or len(positions) > 0

    # ─── Portfolio level ───
    portfolio = _compute_metrics(trades, positions, pm)

    # ─── Per strategy ───
    strategy_names = set()
    for t in trades:
        strategy_names.add(t.strategy)
    for p in positions:
        strategy_names.add(p.strategy)
    # Always include core strategies even if no trades
    for s in ["v5_base", "v5_tuned", "v9_breakout"]:
        strategy_names.add(s)

    strategies = {}
    for name in sorted(strategy_names):
        s_trades = [t for t in trades if t.strategy == name]
        s_positions = [p for p in positions if p.strategy == name]
        strategies[name] = _compute_metrics(s_trades, s_positions, pm)
        strategies[name]["strategy"] = name

    # ─── Per asset ───
    asset_names = set()
    for t in trades:
        asset_names.add(t.asset)
    for p in positions:
        asset_names.add(p.asset)
    for a in ["BTCUSD", "ETHUSD"]:
        asset_names.add(a)

    assets = {}
    for name in sorted(asset_names):
        a_trades = [t for t in trades if t.asset == name]
        a_positions = [p for p in positions if p.asset == name]
        assets[name] = _compute_metrics(a_trades, a_positions, pm)
        assets[name]["asset"] = name

    return {
        "portfolio": portfolio,
        "strategies": strategies,
        "assets": assets,
        "has_data": has_data,
    }


def _compute_metrics(trades: list, positions: list, pm) -> dict:
    """Compute standard trading metrics for a set of trades."""
    total = len(trades)
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]

    total_pnl = sum(t.pnl for t in trades)
    gross_profit = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))

    win_rate = len(wins) / max(1, total)
    profit_factor = gross_profit / max(0.01, gross_loss) if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0)
    avg_win = gross_profit / max(1, len(wins))
    avg_loss = gross_loss / max(1, len(losses))
    expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss) if total > 0 else 0

    # Duration
    avg_bars = sum(t.bars_held for t in trades) / max(1, total) if total > 0 else 0

    # Max drawdown (sequential)
    peak = 0
    max_dd = 0
    running = 0
    for t in trades:
        running += t.pnl
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd:
            max_dd = dd

    # Rolling win rate (last 20)
    recent = trades[-20:] if len(trades) >= 20 else trades
    rolling_wr = len([t for t in recent if t.pnl > 0]) / max(1, len(recent)) if recent else 0

    # Last trade timestamp
    last_trade_time = trades[-1].exit_time if trades else None

    return {
        "total_trades": total,
        "closed_trades": total,
        "open_positions": len(positions),
        "pnl": round(total_pnl, 2),
        "win_rate": round(win_rate * 100, 1),
        "profit_factor": round(profit_factor, 2) if profit_factor != float('inf') else 999.0,
        "expectancy": round(expectancy, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "max_drawdown": round(max_dd, 2),
        "avg_bars_held": round(avg_bars, 1),
        "rolling_wr_20": round(rolling_wr * 100, 1),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "wins": len(wins),
        "losses": len(losses),
        "last_trade_time": last_trade_time,
    }
