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
"""
import time
import structlog
from datetime import datetime, timezone

from bahamut.celery_app import celery_app
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
        _strategies = {
            "v5_base": V5Base(),
            "v5_tuned": V5Tuned(),
        }
    return _strategies


def _fetch_candles(asset: str, timeframe: str = "4H", count: int = 260) -> list[dict]:
    """
    Fetch candles from market data service.
    Tries Twelve Data → OANDA → cached/demo data.
    """
    import asyncio

    try:
        from bahamut.ingestion.market_data import MarketDataService
        svc = MarketDataService()

        loop = asyncio.new_event_loop()
        try:
            # Get raw candles if available
            from bahamut.ingestion.adapters.twelvedata import twelve_data, to_twelve_symbol, to_twelve_interval
            if twelve_data.configured:
                td_sym = to_twelve_symbol(asset)
                td_int = to_twelve_interval(timeframe)
                candles = loop.run_until_complete(
                    twelve_data.get_candles(td_sym, td_int, count=count))
                if candles and len(candles) >= 50:
                    return candles
        finally:
            loop.close()
    except Exception as e:
        logger.debug("candle_fetch_error", asset=asset, error=str(e))

    # Fallback: try loading from data_real cache
    try:
        from bahamut.backtesting.data_real import load_cache
        candles = load_cache(asset.replace("/", ""), timeframe.lower())
        if candles and len(candles) >= 50:
            return candles[-count:]
    except Exception:
        pass

    return []


@celery_app.task(name="bahamut.execution.v7_orchestrator.run_v7_cycle", bind=True, max_retries=1)
def run_v7_cycle(self):
    """
    Main v7 trading cycle. Runs every 2 minutes.
    Only processes if a new bar is detected (avoids duplicate signals).
    """
    global _last_bar_time

    engine = get_execution_engine()
    pm = get_portfolio_manager()
    strategies = _get_strategies()

    assets = ["BTCUSD"]  # Extend as needed

    for asset in assets:
        try:
            candles = _fetch_candles(asset)
            if not candles or len(candles) < 260:
                logger.debug("v7_insufficient_data", asset=asset, candles=len(candles) if candles else 0)
                continue

            # Check if this is a new bar
            latest_time = candles[-1].get("datetime", "")
            bar_key = f"{asset}"
            if _last_bar_time.get(bar_key) == latest_time:
                continue  # Already processed this bar
            _last_bar_time[bar_key] = latest_time

            logger.info("v7_new_bar", asset=asset, time=latest_time,
                        close=candles[-1].get("close", 0))

            # Compute indicators for current and previous bar
            indicators = compute_indicators(candles)
            prev_indicators = compute_indicators(candles[:-1]) if len(candles) > 1 else None

            if not indicators:
                continue

            # Build bar dict for execution engine
            bar = {
                "open": candles[-1].get("open", 0),
                "high": candles[-1].get("high", 0),
                "low": candles[-1].get("low", 0),
                "close": candles[-1].get("close", 0),
                "datetime": latest_time,
                "volume": candles[-1].get("volume", 0),
            }

            # 1. Process bar through execution engine (fills pending, checks exits)
            engine.on_new_bar(bar, pm.get_sleeve_equities())

            # 2. Evaluate each enabled strategy
            for strat_name, strategy in strategies.items():
                if not pm.is_strategy_enabled(strat_name):
                    continue

                # Check portfolio risk limits
                can_trade, reason = pm.can_trade(strat_name)
                if not can_trade:
                    logger.debug("v7_trade_blocked", strategy=strat_name, reason=reason)
                    continue

                # Evaluate strategy
                signal = strategy.evaluate(candles, indicators, prev_indicators)
                if signal:
                    signal.asset = asset
                    sleeve_eq = pm.get_sleeve_equity(strat_name)
                    order = engine.submit_signal(signal, sleeve_eq)
                    if order:
                        logger.info("v7_signal_submitted",
                                    strategy=strat_name,
                                    direction=signal.direction,
                                    asset=asset,
                                    order_id=order.order_id)

                        # Persist order
                        _persist_order(order)

            # 3. Update portfolio
            pm.update()

            # 4. Persist any new closed trades
            _persist_new_trades(engine)

            # 5. Persist sleeve states
            _persist_sleeves(pm)

        except Exception as e:
            logger.error("v7_cycle_error", asset=asset, error=str(e))

    # Take periodic snapshot (every cycle)
    try:
        snap = pm.take_snapshot()
        _persist_snapshot(snap)
    except Exception as e:
        logger.error("v7_snapshot_error", error=str(e))


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
    """Run the v7 cycle synchronously (for testing/debugging)."""
    run_v7_cycle()
