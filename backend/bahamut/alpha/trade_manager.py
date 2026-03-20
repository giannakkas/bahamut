"""
Bahamut v4 — Trade Manager State Machine

Tracks each position through explicit lifecycle states.
Integrates with exit engine for deterministic trade management.
"""
from dataclasses import dataclass, field
from typing import Optional


# Trade lifecycle states
STATE_NEW = "NEW"
STATE_OPEN = "OPEN"
STATE_PARTIAL = "PARTIAL_TAKEN"
STATE_BREAKEVEN = "BREAKEVEN_PROTECTED"
STATE_TRAILING = "TRAILING"
STATE_EXIT_READY = "EXIT_READY"
STATE_CLOSED = "CLOSED"


@dataclass
class ManagedTrade:
    """Extended trade object with state tracking."""
    trade_id: str
    asset: str
    direction: str
    entry_price: float
    entry_time: int
    stop_loss: float
    take_profit: float
    original_stop_loss: float = 0.0
    original_take_profit: float = 0.0
    size_multiplier: float = 1.0
    remaining_size: float = 1.0        # 1.0 = full, 0.6 after partial
    max_hold: int = 12
    regime: str = ""
    entry_type: str = "momentum"
    entry_quality: float = 0.5

    # State
    state: str = STATE_NEW
    mfe: float = 0.0                   # Max favorable excursion (price)
    mae: float = 0.0                   # Max adverse excursion (price)
    mfe_r: float = 0.0                 # MFE in R-multiples
    mae_r: float = 0.0                 # MAE in R-multiples
    partial_pnl: float = 0.0          # PnL from partial exits
    bars_held: int = 0

    # Exit
    exit_price: Optional[float] = None
    exit_time: Optional[int] = None
    exit_reason: Optional[str] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0

    def __post_init__(self):
        if self.original_stop_loss == 0:
            self.original_stop_loss = self.stop_loss
        if self.original_take_profit == 0:
            self.original_take_profit = self.take_profit

    @property
    def sl_distance(self) -> float:
        return abs(self.entry_price - self.original_stop_loss)

    @property
    def r_multiple(self) -> float:
        """Current R-multiple based on entry and original SL distance."""
        if self.exit_price and self.sl_distance > 0:
            if self.direction == "LONG":
                return (self.exit_price - self.entry_price) / self.sl_distance
            else:
                return (self.entry_price - self.exit_price) / self.sl_distance
        return 0.0

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id, "asset": self.asset,
            "direction": self.direction,
            "entry_price": self.entry_price, "exit_price": self.exit_price,
            "entry_time": self.entry_time, "exit_time": self.exit_time,
            "stop_loss": self.stop_loss, "take_profit": self.take_profit,
            "original_stop_loss": self.original_stop_loss,
            "exit_reason": self.exit_reason,
            "pnl": self.pnl, "pnl_pct": round(self.pnl_pct, 4),
            "regime": self.regime,
            "entry_type": self.entry_type,
            "entry_quality": self.entry_quality,
            "size_multiplier": self.size_multiplier,
            "remaining_size": self.remaining_size,
            "state": self.state,
            "mfe_r": round(self.mfe_r, 3),
            "mae_r": round(self.mae_r, 3),
            "bars_held": self.bars_held,
            "partial_pnl": round(self.partial_pnl, 2),
        }
