"""
Strategy base — common interface for all operationalized strategies.
Each strategy produces structured signals. No execution logic here.
"""
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone


@dataclass
class StrategyMeta:
    name: str
    version: str
    asset_classes: list = field(default_factory=lambda: ["crypto"])
    description: str = ""
    sl_pct: float = 0.0
    tp_pct: float = 0.0
    max_hold_bars: int = 0
    risk_pct: float = 0.02


@dataclass
class Signal:
    strategy: str
    asset: str
    direction: str           # LONG / SHORT / NONE
    entry_type: str = "market_next_open"
    sl_pct: float = 0.0      # As fraction (0.08 = 8%)
    tp_pct: float = 0.0
    max_hold_bars: int = 30
    quality: float = 0.5     # 0-1
    reason: str = ""
    timestamp: str = ""
    signal_id: str = ""
    # Phase 3 Item 7: sub-strategy tag for trust/suppression isolation.
    # Example: v10_mean_reversion emits one of "v10_range_long",
    # "v10_range_short", "v10_crash_short". Other strategies leave this
    # empty (""), in which case the learning engine keys on parent
    # strategy only — behavior unchanged for v5/v9.
    substrategy: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if not self.signal_id:
            import uuid
            self.signal_id = str(uuid.uuid4())[:12]


class BaseStrategy:
    """Base class for all strategies."""
    meta: StrategyMeta

    def evaluate(self, candles: list, indicators: dict,
                 prev_indicators: dict = None) -> Optional[Signal]:
        """Evaluate current market state and return Signal or None."""
        raise NotImplementedError
