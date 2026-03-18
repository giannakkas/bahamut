"""
Paper Trading Engine — Auto-executes demo trades from signal cycles.

Flow:
1. Signal cycle completes → consensus score calculated
2. Engine checks: score >= threshold? portfolio has room? no duplicate position?
3. Opens paper position with ATR-based SL/TP
4. Every price update → checks SL/TP/timeout
5. On close → triggers learning feedback loop
"""

import structlog
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from bahamut.database import AsyncSessionLocal
from bahamut.paper_trading.models import (
    PaperPortfolio, PaperPosition, PositionStatus, TradeDirection
)

logger = structlog.get_logger(__name__)

# --- Configuration ---
SIGNAL_THRESHOLDS = {
    "STRONG_SIGNAL": 0.72,
    "SIGNAL": 0.58,
    "WEAK_SIGNAL": 0.45,
}

# Position sizing
DEFAULT_RISK_PCT = 2.0          # Risk 2% of portfolio per trade
SL_ATR_MULTIPLIER = 2.0         # Stop loss = 2x ATR
TP_ATR_MULTIPLIER = 3.0         # Take profit = 3x ATR (1.5:1 reward/risk)
MAX_HOLD_HOURS = 48             # Close positions after 48h if no SL/TP hit
MAX_OPEN_POSITIONS = 5
MIN_SCORE_TO_TRADE = 0.45       # Minimum consensus score to open a trade

# Asset-specific lot sizes for position value calculation
ASSET_CONFIG = {
    # FX
    "EURUSD": {"pip_value": 0.0001, "lot_size": 100_000, "min_qty": 0.01},
    "GBPUSD": {"pip_value": 0.0001, "lot_size": 100_000, "min_qty": 0.01},
    "USDJPY": {"pip_value": 0.01, "lot_size": 100_000, "min_qty": 0.01},
    "AUDUSD": {"pip_value": 0.0001, "lot_size": 100_000, "min_qty": 0.01},
    "USDCHF": {"pip_value": 0.0001, "lot_size": 100_000, "min_qty": 0.01},
    "USDCAD": {"pip_value": 0.0001, "lot_size": 100_000, "min_qty": 0.01},
    "NZDUSD": {"pip_value": 0.0001, "lot_size": 100_000, "min_qty": 0.01},
    "EURGBP": {"pip_value": 0.0001, "lot_size": 100_000, "min_qty": 0.01},
    # Commodities
    "XAUUSD": {"pip_value": 0.01, "lot_size": 100, "min_qty": 0.01},
    "XAGUSD": {"pip_value": 0.01, "lot_size": 5000, "min_qty": 0.01},
    # Crypto
    "BTCUSD": {"pip_value": 0.01, "lot_size": 1, "min_qty": 0.001},
    "ETHUSD": {"pip_value": 0.01, "lot_size": 1, "min_qty": 0.01},
    "SOLUSD": {"pip_value": 0.01, "lot_size": 1, "min_qty": 0.1},
    "BNBUSD": {"pip_value": 0.01, "lot_size": 1, "min_qty": 0.01},
    "XRPUSD": {"pip_value": 0.0001, "lot_size": 1, "min_qty": 1},
    "ADAUSD": {"pip_value": 0.0001, "lot_size": 1, "min_qty": 1},
    "DOGEUSD": {"pip_value": 0.00001, "lot_size": 1, "min_qty": 10},
    "AVAXUSD": {"pip_value": 0.01, "lot_size": 1, "min_qty": 0.1},
    "DOTUSD": {"pip_value": 0.01, "lot_size": 1, "min_qty": 0.1},
    "LINKUSD": {"pip_value": 0.01, "lot_size": 1, "min_qty": 0.1},
    "MATICUSD": {"pip_value": 0.0001, "lot_size": 1, "min_qty": 1},
    "SHIBUSD": {"pip_value": 0.00000001, "lot_size": 1, "min_qty": 100000},
}
# All stocks default to: lot_size=1, min_qty=1 (whole shares)
_STOCK_DEFAULTS = {"pip_value": 0.01, "lot_size": 1, "min_qty": 1}


async def get_or_create_portfolio(session: AsyncSession) -> PaperPortfolio:
    """Get the system demo portfolio, create if doesn't exist."""
    result = await session.execute(
        select(PaperPortfolio).where(PaperPortfolio.name == "SYSTEM_DEMO")
    )
    portfolio = result.scalar_one_or_none()

    if not portfolio:
        portfolio = PaperPortfolio(
            name="SYSTEM_DEMO",
            initial_balance=100_000.0,
            current_balance=100_000.0,
            peak_balance=100_000.0,
        )
        session.add(portfolio)
        await session.flush()
        logger.info("paper_portfolio_created", balance=100_000.0)

    return portfolio


async def count_open_positions(session: AsyncSession, portfolio_id: int) -> int:
    """Count currently open positions."""
    result = await session.execute(
        select(PaperPosition).where(
            and_(
                PaperPosition.portfolio_id == portfolio_id,
                PaperPosition.status == PositionStatus.OPEN.value
            )
        )
    )
    return len(result.scalars().all())


async def has_open_position_for_asset(
    session: AsyncSession, portfolio_id: int, asset: str
) -> bool:
    """Check if there's already an open position for this asset."""
    result = await session.execute(
        select(PaperPosition).where(
            and_(
                PaperPosition.portfolio_id == portfolio_id,
                PaperPosition.asset == asset,
                PaperPosition.status == PositionStatus.OPEN.value
            )
        )
    )
    return result.scalar_one_or_none() is not None


def calculate_position_size(
    portfolio_balance: float,
    risk_pct: float,
    entry_price: float,
    stop_loss: float,
    asset: str,
) -> tuple[float, float, float]:
    """
    Calculate position size based on risk management.
    Returns: (quantity, position_value, risk_amount)
    """
    config = ASSET_CONFIG.get(asset, _STOCK_DEFAULTS)
    risk_amount = portfolio_balance * (risk_pct / 100.0)
    sl_distance = abs(entry_price - stop_loss)

    if sl_distance == 0:
        sl_distance = entry_price * 0.01  # Fallback: 1% of price

    # For FX: quantity in lots, for stocks/crypto: quantity in units
    lot_size = config["lot_size"]
    min_qty = config["min_qty"]

    # How many units can we buy with our risk budget?
    quantity = risk_amount / sl_distance

    # For FX, convert to lots
    if lot_size > 1:
        quantity = quantity / lot_size

    # Enforce minimum
    quantity = max(quantity, min_qty)

    # Round appropriately
    if config["lot_size"] == 1 and config["min_qty"] >= 1:
        quantity = round(quantity)  # Whole shares
        quantity = max(quantity, 1)
    else:
        quantity = round(quantity, 4)

    position_value = quantity * lot_size * entry_price if lot_size > 1 else quantity * entry_price
    actual_risk = quantity * lot_size * sl_distance if lot_size > 1 else quantity * sl_distance

    return quantity, position_value, actual_risk


def calculate_sl_tp(
    entry_price: float, direction: str, atr: float, asset: str
) -> tuple[float, float]:
    """Calculate stop loss and take profit from ATR."""
    if atr <= 0:
        # Fallback: use 1% for SL, 1.5% for TP
        atr = entry_price * 0.01

    sl_distance = atr * SL_ATR_MULTIPLIER
    tp_distance = atr * TP_ATR_MULTIPLIER

    if direction == "LONG":
        stop_loss = entry_price - sl_distance
        take_profit = entry_price + tp_distance
    else:
        stop_loss = entry_price + sl_distance
        take_profit = entry_price - tp_distance

    return round(stop_loss, 6), round(take_profit, 6)


async def process_signal(
    asset: str,
    direction: str,          # "LONG" or "SHORT"
    consensus_score: float,
    signal_label: str,       # "STRONG_SIGNAL", "SIGNAL", "WEAK_SIGNAL"
    entry_price: float,
    atr: float,
    agent_votes: dict,       # {"technical": {"direction": "LONG", "confidence": 0.78}, ...}
    cycle_id: str = None,
) -> dict:
    """
    Main entry point — called after every signal cycle.
    Decides whether to open a trade and executes it.
    """
    log = logger.bind(asset=asset, direction=direction, score=consensus_score)

    # Gate 1: Score too low
    if consensus_score < MIN_SCORE_TO_TRADE:
        log.info("paper_trade_skipped", reason="score_below_minimum")
        return {"action": "SKIP", "reason": "Score below minimum"}

    # Gate 2: Only trade SIGNAL or above (skip WEAK_SIGNAL for now, too noisy)
    if signal_label not in ("STRONG_SIGNAL", "SIGNAL"):
        log.info("paper_trade_skipped", reason="weak_signal")
        return {"action": "SKIP", "reason": "Only trading SIGNAL or STRONG_SIGNAL"}

    async with AsyncSessionLocal() as session:
        async with session.begin():
            portfolio = await get_or_create_portfolio(session)

            if not portfolio.is_active:
                log.info("paper_trade_skipped", reason="portfolio_inactive")
                return {"action": "SKIP", "reason": "Portfolio inactive"}

            # Gate 3: Max open positions
            open_count = await count_open_positions(session, portfolio.id)
            if open_count >= portfolio.max_open_positions:
                log.info("paper_trade_skipped", reason="max_positions_reached",
                         open=open_count)
                return {"action": "SKIP", "reason": f"Max positions ({open_count})"}

            # Gate 4: Already have position in this asset
            if await has_open_position_for_asset(session, portfolio.id, asset):
                log.info("paper_trade_skipped", reason="duplicate_asset")
                return {"action": "SKIP", "reason": f"Already in {asset}"}

            # Calculate position
            stop_loss, take_profit = calculate_sl_tp(entry_price, direction, atr, asset)
            quantity, position_value, risk_amount = calculate_position_size(
                portfolio.current_balance,
                portfolio.risk_per_trade_pct,
                entry_price,
                stop_loss,
                asset,
            )

            # Gate 5: Risk amount sanity check
            if risk_amount > portfolio.current_balance * 0.05:
                log.warning("paper_trade_skipped", reason="risk_too_high",
                            risk=risk_amount, balance=portfolio.current_balance)
                return {"action": "SKIP", "reason": "Risk exceeds 5% of portfolio"}

            # Open the position
            position = PaperPosition(
                portfolio_id=portfolio.id,
                asset=asset,
                direction=direction,
                entry_price=entry_price,
                quantity=quantity,
                position_value=position_value,
                entry_signal_score=consensus_score,
                entry_signal_label=signal_label,
                stop_loss=stop_loss,
                take_profit=take_profit,
                risk_amount=risk_amount,
                atr_at_entry=atr,
                current_price=entry_price,
                agent_votes=agent_votes,
                consensus_score=consensus_score,
                cycle_id=cycle_id,
            )
            session.add(position)

            log.info("paper_trade_opened",
                     qty=quantity, entry=entry_price,
                     sl=stop_loss, tp=take_profit,
                     risk=round(risk_amount, 2),
                     value=round(position_value, 2))

            return {
                "action": "OPENED",
                "asset": asset,
                "direction": direction,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "quantity": quantity,
                "risk_amount": round(risk_amount, 2),
                "signal_score": consensus_score,
            }


async def update_open_positions(price_data: dict[str, float]) -> list[dict]:
    """
    Called on every price update.
    Checks all open positions for SL/TP hits and timeout.
    Returns list of closed positions.

    price_data: {"EURUSD": 1.0850, "BTCUSD": 67500.0, ...}
    """
    closed = []

    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(
                select(PaperPosition).where(
                    PaperPosition.status == PositionStatus.OPEN.value
                )
            )
            positions = result.scalars().all()

            for pos in positions:
                current_price = price_data.get(pos.asset)
                if not current_price:
                    continue

                # Update current price and unrealized PnL
                config = ASSET_CONFIG.get(pos.asset, _STOCK_DEFAULTS)
                lot = config["lot_size"]
                if pos.direction == TradeDirection.LONG.value:
                    pnl = (current_price - pos.entry_price) * pos.quantity * lot
                else:
                    pnl = (pos.entry_price - current_price) * pos.quantity * lot

                pnl_pct = (pnl / pos.position_value * 100) if pos.position_value else 0

                pos.current_price = current_price
                pos.unrealized_pnl = round(pnl, 2)
                pos.unrealized_pnl_pct = round(pnl_pct, 2)

                # Track max favorable / adverse excursion
                if pnl > pos.max_favorable:
                    pos.max_favorable = round(pnl, 2)
                if pnl < pos.max_adverse:
                    pos.max_adverse = round(pnl, 2)

                # Check close conditions
                close_reason = None

                if pos.direction == TradeDirection.LONG.value:
                    if current_price <= pos.stop_loss:
                        close_reason = PositionStatus.CLOSED_SL
                    elif current_price >= pos.take_profit:
                        close_reason = PositionStatus.CLOSED_TP
                else:  # SHORT
                    if current_price >= pos.stop_loss:
                        close_reason = PositionStatus.CLOSED_SL
                    elif current_price <= pos.take_profit:
                        close_reason = PositionStatus.CLOSED_TP

                # Timeout check
                if pos.opened_at:
                    age = datetime.now(timezone.utc) - pos.opened_at.replace(tzinfo=timezone.utc)
                    if age > timedelta(hours=MAX_HOLD_HOURS):
                        close_reason = PositionStatus.CLOSED_TIMEOUT

                if close_reason:
                    result = await close_position(session, pos, current_price, close_reason)
                    closed.append(result)

    return closed


async def close_position(
    session: AsyncSession,
    position: PaperPosition,
    exit_price: float,
    status: PositionStatus,
) -> dict:
    """Close a position and update portfolio stats."""
    # Calculate final PnL
    config = ASSET_CONFIG.get(position.asset, _STOCK_DEFAULTS)
    lot = config["lot_size"]
    if position.direction == TradeDirection.LONG.value:
        pnl = (exit_price - position.entry_price) * position.quantity * lot
    else:
        pnl = (position.entry_price - exit_price) * position.quantity * lot

    pnl_pct = (pnl / position.position_value * 100) if position.position_value else 0

    position.exit_price = exit_price
    position.realized_pnl = round(pnl, 2)
    position.realized_pnl_pct = round(pnl_pct, 2)
    position.status = status.value
    position.closed_at = datetime.now(timezone.utc)
    position.unrealized_pnl = 0
    position.unrealized_pnl_pct = 0

    # Update portfolio
    portfolio_result = await session.execute(
        select(PaperPortfolio).where(PaperPortfolio.id == position.portfolio_id)
    )
    portfolio = portfolio_result.scalar_one()

    portfolio.current_balance += pnl
    portfolio.total_pnl += pnl
    portfolio.total_pnl_pct = (
        (portfolio.current_balance - portfolio.initial_balance)
        / portfolio.initial_balance * 100
    )
    portfolio.total_trades += 1

    is_win = pnl > 0
    if is_win:
        portfolio.winning_trades += 1
    else:
        portfolio.losing_trades += 1

    portfolio.win_rate = (
        portfolio.winning_trades / portfolio.total_trades * 100
        if portfolio.total_trades > 0 else 0
    )

    if pnl > portfolio.best_trade_pnl:
        portfolio.best_trade_pnl = round(pnl, 2)
    if pnl < portfolio.worst_trade_pnl:
        portfolio.worst_trade_pnl = round(pnl, 2)

    if portfolio.current_balance > portfolio.peak_balance:
        portfolio.peak_balance = portfolio.current_balance

    drawdown = (
        (portfolio.peak_balance - portfolio.current_balance)
        / portfolio.peak_balance * 100
    )
    if drawdown > portfolio.max_drawdown:
        portfolio.max_drawdown = round(drawdown, 2)

    portfolio.updated_at = datetime.now(timezone.utc)

    logger.info("paper_trade_closed",
                asset=position.asset,
                direction=position.direction,
                status=status.value,
                pnl=round(pnl, 2),
                pnl_pct=round(pnl_pct, 2),
                balance=round(portfolio.current_balance, 2),
                win_rate=round(portfolio.win_rate, 1))

    return {
        "position_id": position.id,
        "asset": position.asset,
        "direction": position.direction,
        "entry_price": position.entry_price,
        "exit_price": exit_price,
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "status": status.value,
        "agent_votes": position.agent_votes,
        "consensus_score": position.consensus_score,
        "cycle_id": position.cycle_id,
    }


async def close_on_opposite_signal(asset: str, new_direction: str) -> dict | None:
    """If we're LONG and a SHORT signal fires (or vice versa), close the position."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(
                select(PaperPosition).where(
                    and_(
                        PaperPosition.asset == asset,
                        PaperPosition.status == PositionStatus.OPEN.value,
                        PaperPosition.direction != new_direction,
                    )
                )
            )
            position = result.scalar_one_or_none()
            if position and position.current_price:
                return await close_position(
                    session, position, position.current_price,
                    PositionStatus.CLOSED_SIGNAL
                )
    return None


async def get_portfolio_summary() -> dict:
    """Get current portfolio state for the dashboard."""
    async with AsyncSessionLocal() as session:
        portfolio = await get_or_create_portfolio(session)

        result = await session.execute(
            select(PaperPosition).where(
                and_(
                    PaperPosition.portfolio_id == portfolio.id,
                    PaperPosition.status == PositionStatus.OPEN.value,
                )
            )
        )
        open_positions = result.scalars().all()

        return {
            "balance": round(portfolio.current_balance, 2),
            "initial_balance": portfolio.initial_balance,
            "total_pnl": round(portfolio.total_pnl, 2),
            "total_pnl_pct": round(portfolio.total_pnl_pct, 2),
            "total_trades": portfolio.total_trades,
            "winning_trades": portfolio.winning_trades,
            "losing_trades": portfolio.losing_trades,
            "win_rate": round(portfolio.win_rate, 1),
            "best_trade": portfolio.best_trade_pnl,
            "worst_trade": portfolio.worst_trade_pnl,
            "max_drawdown": portfolio.max_drawdown,
            "peak_balance": portfolio.peak_balance,
            "open_positions": [
                {
                    "id": p.id,
                    "asset": p.asset,
                    "direction": p.direction,
                    "entry_price": p.entry_price,
                    "current_price": p.current_price,
                    "quantity": p.quantity,
                    "position_value": p.position_value,
                    "risk_amount": p.risk_amount,
                    "unrealized_pnl": p.unrealized_pnl,
                    "unrealized_pnl_pct": p.unrealized_pnl_pct,
                    "stop_loss": p.stop_loss,
                    "take_profit": p.take_profit,
                    "signal_score": p.entry_signal_score,
                    "opened_at": p.opened_at.isoformat() if p.opened_at else None,
                }
                for p in open_positions
            ],
        }
