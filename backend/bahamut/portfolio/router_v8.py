"""
Bahamut v8 — Regime Router

Routes capital and strategy activation based on detected market regime.

TREND  → v5_base + v5_tuned (50/50)
RANGE  → v8_range (100%)
CRASH  → v8_defensive (100%, no trading)
"""
import structlog
from dataclasses import dataclass

from bahamut.regime.v8_detector import RegimeResult

logger = structlog.get_logger()

# ── Allocation templates per regime ──
REGIME_ALLOCATIONS = {
    "TREND": {
        "active": ["v5_base", "v5_tuned", "v9_breakout"],
        "inactive": ["v8_range", "v8_defensive"],
        "weights": {"v5_base": 0.35, "v5_tuned": 0.35, "v9_breakout": 0.30},
        "mode": "trend_capture",
    },
    "RANGE": {
        "active": ["v8_range"],
        "inactive": ["v5_base", "v5_tuned", "v9_breakout", "v8_defensive"],
        "weights": {"v8_range": 1.0},
        "mode": "mean_reversion",
    },
    "CRASH": {
        "active": ["v8_defensive"],
        "inactive": ["v5_base", "v5_tuned", "v9_breakout", "v8_range"],
        "weights": {"v8_defensive": 1.0},
        "mode": "capital_preservation",
    },
}


@dataclass
class RoutingDecision:
    regime: str = "RANGE"
    confidence: float = 0.5
    active_strategies: list = None
    inactive_strategies: list = None
    weights: dict = None
    portfolio_mode: str = "unknown"
    reason: str = ""

    def __post_init__(self):
        if self.active_strategies is None:
            self.active_strategies = []
        if self.inactive_strategies is None:
            self.inactive_strategies = []
        if self.weights is None:
            self.weights = {}


# Track last regime PER ASSET for change detection
_last_regime: dict[str, str] = {}


def route(regime: RegimeResult, asset: str = "BTCUSD") -> RoutingDecision:
    """
    Determine which strategies should be active based on the current regime.
    Tracks regime changes per asset independently.
    """
    global _last_regime

    template = REGIME_ALLOCATIONS.get(regime.regime, REGIME_ALLOCATIONS["RANGE"])

    decision = RoutingDecision(
        regime=regime.regime,
        confidence=regime.confidence,
        active_strategies=list(template["active"]),
        inactive_strategies=list(template["inactive"]),
        weights=dict(template["weights"]),
        portfolio_mode=template["mode"],
        reason=regime.reason,
    )

    # Log regime changes per asset
    prev = _last_regime.get(asset, "")
    if regime.regime != prev:
        logger.info("regime_change",
                     asset=asset,
                     old=prev or "INIT",
                     new=regime.regime,
                     confidence=regime.confidence,
                     mode=template["mode"],
                     active=template["active"])
        _last_regime[asset] = regime.regime

    return decision


def get_current_regime(asset: str = "BTCUSD") -> str:
    """Return the last detected regime for an asset."""
    return _last_regime.get(asset, "RANGE")


def get_all_regimes() -> dict[str, str]:
    """Return current regime for all tracked assets."""
    return dict(_last_regime)
