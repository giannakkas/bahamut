"""
Execution models — core data structures for the trading lifecycle.
These are in-memory representations. DB models are separate.
"""
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone
from enum import Enum
import uuid


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ExitReason(str, Enum):
    TP = "TP"
    SL = "SL"
    TIMEOUT = "TIMEOUT"
    MANUAL = "MANUAL"
    KILL_SWITCH = "KILL_SWITCH"
    SIGNAL = "SIGNAL"


@dataclass
class Order:
    order_id: str = ""
    strategy: str = ""
    asset: str = ""
    direction: str = "LONG"
    status: OrderStatus = OrderStatus.PENDING
    signal_time: str = ""
    fill_time: Optional[str] = None
    entry_price: float = 0.0      # 0 = fill at next open
    stop_price: float = 0.0
    tp_price: float = 0.0
    size: float = 0.0             # Units of asset
    risk_amount: float = 0.0      # $ at risk
    max_hold_bars: int = 30
    signal_id: str = ""
    sl_pct: float = 0.0
    tp_pct: float = 0.0

    def __post_init__(self):
        if not self.order_id:
            self.order_id = str(uuid.uuid4())[:12]
        if not self.signal_time:
            self.signal_time = datetime.now(timezone.utc).isoformat()


@dataclass
class Position:
    order_id: str = ""
    strategy: str = ""
    asset: str = ""
    direction: str = "LONG"
    status: OrderStatus = OrderStatus.OPEN
    entry_price: float = 0.0
    current_price: float = 0.0
    stop_price: float = 0.0
    tp_price: float = 0.0
    size: float = 0.0
    risk_amount: float = 0.0
    entry_time: str = ""
    entry_bar_idx: int = 0
    bars_held: int = 0
    max_hold_bars: int = 30
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0

    def update_price(self, price: float):
        self.current_price = price
        if self.direction == "LONG":
            self.unrealized_pnl = (price - self.entry_price) * self.size
            self.unrealized_pnl_pct = (price - self.entry_price) / self.entry_price if self.entry_price > 0 else 0
        else:
            self.unrealized_pnl = (self.entry_price - price) * self.size
            self.unrealized_pnl_pct = (self.entry_price - price) / self.entry_price if self.entry_price > 0 else 0


@dataclass
class ClosedTrade:
    trade_id: str = ""
    order_id: str = ""
    strategy: str = ""
    asset: str = ""
    direction: str = "LONG"
    entry_price: float = 0.0
    exit_price: float = 0.0
    stop_price: float = 0.0
    tp_price: float = 0.0
    size: float = 0.0
    risk_amount: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    entry_time: str = ""
    exit_time: str = ""
    exit_reason: str = ""
    bars_held: int = 0

    def __post_init__(self):
        if not self.trade_id:
            self.trade_id = str(uuid.uuid4())[:12]
