"""
Celery Tasks for Paper Trading — The automation layer.

Tasks:
1. check_paper_positions  — Every 1 min, update prices + check SL/TP
2. process_learning_queue — Every 5 min, run learning on closed trades
3. paper_trading_daily_report — Daily at 22:00 UTC, log performance summary
"""

import asyncio
import structlog
from datetime import datetime, timezone

from bahamut.celery_app import celery_app

logger = structlog.get_logger(__name__)


def run_async(coro):
    """Helper to run async code in sync Celery tasks."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="paper_trading.check_positions", bind=True, max_retries=2)
def check_paper_positions(self):
    """
    Runs every 1 minute.
    Fetches live prices for all assets with open positions,
    updates unrealized PnL, and closes positions that hit SL/TP/timeout.
    """
    try:
        from bahamut.agents.persistence import ensure_tables
        ensure_tables()
    except Exception:
        pass

    try:
        closed = run_async(_check_positions_async())
        if closed:
            logger.info("paper_positions_closed", count=len(closed),
                        trades=[c["asset"] for c in closed])
            # Trigger learning for each closed trade
            for trade in closed:
                process_learning_for_trade.delay(trade)
        return {"checked": True, "closed": len(closed) if closed else 0}
    except Exception as e:
        logger.error("check_positions_failed", error=str(e))
        raise self.retry(countdown=30)


async def _check_positions_async():
    """Fetch prices and update positions."""
    from bahamut.paper_trading.engine import update_open_positions
    from bahamut.ingestion.market_data import get_current_prices

    # Get live prices for all monitored assets
    prices = await get_current_prices()
    if not prices:
        logger.warning("no_prices_available_for_paper_trading")
        return []

    return await update_open_positions(prices)


@celery_app.task(name="paper_trading.process_learning", bind=True, max_retries=3)
def process_learning_for_trade(self, closed_trade: dict):
    """
    Process a single closed trade through the learning feedback loop.
    Updates agent performance stats and trust scores.
    """
    try:
        result = run_async(_process_learning_async(closed_trade))
        logger.info("learning_completed",
                     asset=closed_trade.get("asset"),
                     pnl=closed_trade.get("pnl"),
                     adjustments=len(result.get("adjustments", {})))

        # Apply trust score updates
        if result.get("adjustments"):
            run_async(_apply_trust_async(result["adjustments"]))

        return result
    except Exception as e:
        logger.error("learning_failed", error=str(e),
                     trade=closed_trade.get("asset"))
        raise self.retry(countdown=60)


async def _process_learning_async(closed_trade: dict):
    from bahamut.paper_trading.learning import process_closed_trade
    return await process_closed_trade(closed_trade)


async def _apply_trust_async(adjustments: dict):
    from bahamut.paper_trading.learning import apply_trust_adjustments
    return await apply_trust_adjustments(adjustments)


@celery_app.task(name="paper_trading.daily_report")
def paper_trading_daily_report():
    """
    Daily at 22:00 UTC — Log portfolio performance summary.
    Could later be extended to send Telegram/email reports.
    """
    try:
        summary = run_async(_get_summary_async())
        logger.info("paper_trading_daily_report",
                     balance=summary.get("balance"),
                     total_pnl=summary.get("total_pnl"),
                     win_rate=summary.get("win_rate"),
                     total_trades=summary.get("total_trades"),
                     open_positions=len(summary.get("open_positions", [])))
        return summary
    except Exception as e:
        logger.error("daily_report_failed", error=str(e))
        return {"error": str(e)}


async def _get_summary_async():
    from bahamut.paper_trading.engine import get_portfolio_summary
    return await get_portfolio_summary()


@celery_app.task(name="paper_trading.on_signal_complete")
def on_signal_complete(
    asset: str,
    direction: str,
    consensus_score: float,
    signal_label: str,
    entry_price: float,
    atr: float,
    agent_votes: dict,
    cycle_id: str = None,
):
    """
    Hook called by orchestrator after every signal cycle completes.
    Uses SYNC executor to avoid async event loop issues in Celery.
    """
    # Ensure tables exist
    try:
        from bahamut.agents.persistence import ensure_tables
        ensure_tables()
    except Exception as e:
        logger.warning("ensure_tables_failed", error=str(e))

    logger.info("paper_trading_signal_received",
                asset=asset, direction=direction,
                score=consensus_score, label=signal_label,
                price=entry_price, atr=atr)

    try:
        from bahamut.paper_trading.sync_executor import process_signal_sync
        result = process_signal_sync(
            asset=asset,
            direction=direction,
            consensus_score=consensus_score,
            signal_label=signal_label,
            entry_price=entry_price,
            atr=atr,
            agent_votes=agent_votes,
            cycle_id=cycle_id,
        )
        logger.info("paper_trading_signal_result",
                    asset=asset, action=result.get("action"),
                    reason=result.get("reason", ""))
        return result
    except Exception as e:
        logger.error("on_signal_complete_failed", error=str(e), asset=asset)
        import traceback
        logger.error("on_signal_complete_traceback", tb=traceback.format_exc())
        return {"error": str(e)}


async def _process_signal_async(
    asset, direction, consensus_score, signal_label,
    entry_price, atr, agent_votes, cycle_id
):
    from bahamut.paper_trading.engine import process_signal, close_on_opposite_signal

    # First check if we need to close an opposite position
    await close_on_opposite_signal(asset, direction)

    return await process_signal(
        asset=asset,
        direction=direction,
        consensus_score=consensus_score,
        signal_label=signal_label,
        entry_price=entry_price,
        atr=atr,
        agent_votes=agent_votes,
        cycle_id=cycle_id,
    )
