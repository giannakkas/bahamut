"""
Bahamut v7 Portfolio Manager

Runs multiple strategy sleeves in parallel with isolated capital.
Each sleeve has its own equity, PnL tracking, and risk budget.

Capital flows:
  Total portfolio → allocated to sleeves by weight → strategies trade within sleeve

Risk controls:
  - Max total open risk (default 6%)
  - Max open positions per sleeve (default 1)
  - Kill switch at portfolio drawdown threshold (default 10%)
"""
import os
import json
import structlog
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from bahamut.execution.engine import get_execution_engine

logger = structlog.get_logger()


# ═══════════════════════════════════════════════════════
# REDIS CROSS-PROCESS BRIDGE
# Writes: worker process (orchestrator cycle)
# Reads: API process (dashboard endpoints)
# ═══════════════════════════════════════════════════════

def _get_redis():
    try:
        import redis
        return redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    except Exception:
        return None


def _redis_write(namespace: str, key: str, value):
    """Write a value to Redis for cross-process reads."""
    r = _get_redis()
    if r:
        try:
            r.hset(f"bahamut:pm:{namespace}", key, json.dumps(value))
        except Exception:
            pass


def _redis_read(namespace: str, key: str, default=None):
    """Read a value from Redis (cross-process)."""
    r = _get_redis()
    if not r:
        return default
    try:
        raw = r.hget(f"bahamut:pm:{namespace}", key)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return default


def _redis_read_all(namespace: str) -> dict:
    """Read all values from a Redis hash namespace."""
    r = _get_redis()
    if not r:
        return {}
    try:
        raw = r.hgetall(f"bahamut:pm:{namespace}")
        return {
            (k.decode() if isinstance(k, bytes) else k): json.loads(v)
            for k, v in raw.items()
        }
    except Exception:
        return {}


def get_cross_process_regimes() -> dict:
    """Read asset regimes from Redis — safe for API process."""
    return _redis_read_all("regime")


def get_cross_process_kill_switch() -> bool:
    """Read kill switch state from Redis — safe for API process."""
    return _redis_read("kill_switch", "active", False)


@dataclass
class Sleeve:
    strategy_name: str
    allocation_weight: float = 0.5
    initial_capital: float = 50_000.0
    current_equity: float = 50_000.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    peak_equity: float = 50_000.0
    drawdown: float = 0.0
    trade_count: int = 0
    win_count: int = 0
    enabled: bool = True
    max_open_positions: int = 2  # 1 per asset × 2 assets


@dataclass
class PortfolioSnapshot:
    timestamp: str = ""
    total_equity: float = 0.0
    total_realized_pnl: float = 0.0
    total_unrealized_pnl: float = 0.0
    total_open_risk: float = 0.0
    drawdown: float = 0.0
    sleeve_data: dict = field(default_factory=dict)


class PortfolioManager:
    """Manages portfolio sleeves and risk."""

    def __init__(
        self,
        total_capital: float = 100_000.0,
        allocations: dict[str, float] = None,
        max_total_risk_pct: float = 0.06,
        max_drawdown_pct: float = 0.10,
    ):
        self.total_capital = total_capital
        self.initial_capital = total_capital
        self.max_total_risk_pct = max_total_risk_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.kill_switch_triggered = False

        # Restore peak equity and max drawdown from Redis if available
        stored_peak = _redis_read("portfolio", "peak_equity")
        self.peak_equity = float(stored_peak) if stored_peak and float(stored_peak) > total_capital else total_capital
        stored_max_dd = _redis_read("portfolio", "max_drawdown_pct")
        self._max_dd_seen = float(stored_max_dd) if stored_max_dd else 0.0

        # v8: regime state — per asset
        self.asset_regimes: dict[str, str] = {}
        self.current_regime = "RANGE"       # Last processed (for backward compat)
        self.current_portfolio_mode = "unknown"

        if allocations is None:
            # All sleeves: trend strategies get capital, others start at 0
            allocations = {
                "v5_base": 0.35, "v5_tuned": 0.35, "v9_breakout": 0.30,
                "v8_range": 0.0, "v8_defensive": 0.0,
            }

        self.sleeves: dict[str, Sleeve] = {}
        for name, weight in allocations.items():
            capital = total_capital * weight
            self.sleeves[name] = Sleeve(
                strategy_name=name,
                allocation_weight=weight,
                initial_capital=capital,
                current_equity=capital,
                peak_equity=capital,
            )

        self.snapshots: list[PortfolioSnapshot] = []

    # ═══════════════════════════════════════════════════════
    # SLEEVE MANAGEMENT
    # ═══════════════════════════════════════════════════════

    def get_sleeve_equity(self, strategy: str) -> float:
        sleeve = self.sleeves.get(strategy)
        return sleeve.current_equity if sleeve else 0

    def get_sleeve_equities(self) -> dict[str, float]:
        return {name: s.current_equity for name, s in self.sleeves.items() if s.enabled}

    def is_strategy_enabled(self, strategy: str) -> bool:
        sleeve = self.sleeves.get(strategy)
        return sleeve.enabled if sleeve else False

    def enable_strategy(self, strategy: str):
        if strategy in self.sleeves:
            self.sleeves[strategy].enabled = True
            logger.info("strategy_enabled", strategy=strategy)

    def disable_strategy(self, strategy: str):
        if strategy in self.sleeves:
            self.sleeves[strategy].enabled = False
            logger.info("strategy_disabled", strategy=strategy)

    # ═══════════════════════════════════════════════════════
    # v8: REGIME-DRIVEN ACTIVATION
    # ═══════════════════════════════════════════════════════

    def apply_routing(self, decision, asset: str = ""):
        """
        Record the regime decision per asset.
        Persists to Redis for cross-process visibility (worker → API).
        """
        self.current_regime = decision.regime
        self.current_portfolio_mode = decision.portfolio_mode
        if asset:
            self.asset_regimes[asset] = decision.regime
            # Persist to Redis for cross-process reads
            _redis_write("regime", asset, decision.regime)

        # Update target weights for display only
        for name, weight in decision.weights.items():
            if name in self.sleeves:
                self.sleeves[name].allocation_weight = weight

    # ═══════════════════════════════════════════════════════
    # RISK CHECK
    # ═══════════════════════════════════════════════════════

    def can_trade(self, strategy: str, asset: str = "") -> tuple[bool, str]:
        """Check if a strategy is allowed to trade right now."""
        if self.kill_switch_triggered:
            return False, "kill_switch_active"

        sleeve = self.sleeves.get(strategy)
        if not sleeve:
            return False, "unknown_strategy"
        if not sleeve.enabled:
            return False, "strategy_disabled"

        engine = get_execution_engine()

        # Per-asset limit: max 1 position per strategy per asset
        if asset:
            asset_positions = [p for p in engine.open_positions
                               if p.strategy == strategy and p.asset == asset]
            if len(asset_positions) >= 1:
                return False, f"position_exists_for_{asset}"

        # Global per-strategy limit: max_open_positions across all assets
        open_for_strat = [p for p in engine.open_positions if p.strategy == strategy]
        if len(open_for_strat) >= sleeve.max_open_positions:
            return False, f"max_positions_reached ({sleeve.max_open_positions})"

        # Check total open risk (exclude test positions)
        total_risk = sum(p.risk_amount for p in engine.open_positions
                         if not p.strategy.startswith("TEST_"))
        if total_risk / max(1, self.total_equity) > self.max_total_risk_pct:
            return False, f"total_risk_exceeded ({self.max_total_risk_pct*100:.0f}%)"

        return True, "ok"

    # ═══════════════════════════════════════════════════════
    # UPDATE (called each bar)
    # ═══════════════════════════════════════════════════════

    def update(self):
        """Update sleeve equities from execution engine state."""
        engine = get_execution_engine()

        for name, sleeve in self.sleeves.items():
            realized = engine.get_strategy_pnl(name)
            unrealized = engine.get_strategy_unrealized(name)

            sleeve.realized_pnl = round(realized, 2)
            sleeve.unrealized_pnl = round(unrealized, 2)
            sleeve.current_equity = round(sleeve.initial_capital + realized + unrealized, 2)
            sleeve.peak_equity = max(sleeve.peak_equity, sleeve.current_equity)
            sleeve.drawdown = round(
                1 - sleeve.current_equity / sleeve.peak_equity
                if sleeve.peak_equity > 0 else 0, 4)

            # Trade count — exclude test trades
            sleeve.trade_count = len([t for t in engine.closed_trades
                                       if t.strategy == name and not t.strategy.startswith("TEST_")])
            sleeve.win_count = len([t for t in engine.closed_trades
                                     if t.strategy == name and t.pnl > 0
                                     and not t.strategy.startswith("TEST_")])

        # Portfolio-level
        # NOTE: Test trades (strategy starting with TEST_) are already excluded
        # because no sleeve is named TEST_*, so sleeve equity is unaffected.
        self.total_capital = sum(s.current_equity for s in self.sleeves.values())
        self.peak_equity = max(self.peak_equity, self.total_capital)

        # Persist peak equity to Redis (survives restarts)
        _redis_write("portfolio", "peak_equity", round(self.peak_equity, 2))

        # Kill switch on drawdown
        dd = 1 - self.total_capital / self.peak_equity if self.peak_equity > 0 else 0

        # Track max drawdown seen (persisted to Redis)
        if dd > 0:
            self._max_dd_seen = max(getattr(self, '_max_dd_seen', 0), dd)
            _redis_write("portfolio", "max_drawdown_pct", round(self._max_dd_seen, 6))

        # GUARD: threshold must be > 0 to trigger. A zero threshold would fire at 0% drawdown.
        if (self.max_drawdown_pct > 0
                and dd > 0
                and dd >= self.max_drawdown_pct
                and not self.kill_switch_triggered):
            self.kill_switch_triggered = True
            _redis_write("kill_switch", "active", True)
            logger.warning("portfolio_kill_switch",
                           equity=round(self.total_capital, 2),
                           peak_equity=round(self.peak_equity, 2),
                           drawdown=round(dd * 100, 2),
                           threshold=round(self.max_drawdown_pct * 100, 2),
                           reason="drawdown_exceeded_threshold")

    @property
    def total_equity(self) -> float:
        return sum(s.current_equity for s in self.sleeves.values())

    @property
    def total_drawdown(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        dd = 1 - self.total_equity / self.peak_equity
        return round(max(0.0, min(1.0, dd)), 4)

    # ═══════════════════════════════════════════════════════
    # REBALANCE
    # ═══════════════════════════════════════════════════════

    def rebalance(self, new_weights: dict[str, float] = None):
        """
        Rebalance sleeve capital toward target weights.
        Does NOT force-close trades — adjusts accounting only.
        """
        if new_weights:
            for name, weight in new_weights.items():
                if name in self.sleeves:
                    self.sleeves[name].allocation_weight = weight

        total = self.total_equity
        for name, sleeve in self.sleeves.items():
            target = total * sleeve.allocation_weight
            sleeve.initial_capital = round(target, 2)

        logger.info("portfolio_rebalanced",
                     weights={n: s.allocation_weight for n, s in self.sleeves.items()})

    # ═══════════════════════════════════════════════════════
    # SNAPSHOT
    # ═══════════════════════════════════════════════════════

    def take_snapshot(self) -> PortfolioSnapshot:
        engine = get_execution_engine()
        snap = PortfolioSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat(),
            total_equity=round(self.total_equity, 2),
            total_realized_pnl=round(sum(s.realized_pnl for s in self.sleeves.values()), 2),
            total_unrealized_pnl=round(sum(s.unrealized_pnl for s in self.sleeves.values()), 2),
            total_open_risk=round(sum(p.risk_amount for p in engine.open_positions), 2),
            drawdown=self.total_drawdown,
            sleeve_data={
                name: {
                    "equity": s.current_equity,
                    "realized_pnl": s.realized_pnl,
                    "unrealized_pnl": s.unrealized_pnl,
                    "drawdown": s.drawdown,
                    "trades": s.trade_count,
                    "wins": s.win_count,
                    "enabled": s.enabled,
                    "weight": s.allocation_weight,
                }
                for name, s in self.sleeves.items()
            },
        )
        self.snapshots.append(snap)
        return snap

    def get_summary(self) -> dict:
        engine = get_execution_engine()
        self.update()

        return {
            "total_equity": round(self.total_equity, 2),
            "initial_capital": self.initial_capital,
            "total_return_pct": round(
                (self.total_equity - self.initial_capital) / self.initial_capital * 100, 2),
            "total_realized_pnl": round(sum(s.realized_pnl for s in self.sleeves.values()), 2),
            "total_unrealized_pnl": round(sum(s.unrealized_pnl for s in self.sleeves.values()), 2),
            "total_open_risk": round(sum(p.risk_amount for p in engine.open_positions), 2),
            "drawdown_pct": round(self.total_drawdown * 100, 2),
            "peak_equity": round(self.peak_equity, 2),
            "open_positions": len(engine.open_positions),
            "total_trades": len(engine.closed_trades),
            "kill_switch": self.kill_switch_triggered,
            "regime": self.current_regime,
            "portfolio_mode": self.current_portfolio_mode,
            "asset_regimes": dict(self.asset_regimes),
            "sleeves": {
                name: {
                    "allocation_pct": round(s.allocation_weight * 100, 1),
                    "equity": s.current_equity,
                    "realized_pnl": s.realized_pnl,
                    "unrealized_pnl": s.unrealized_pnl,
                    "drawdown_pct": round(s.drawdown * 100, 2),
                    "trades": s.trade_count,
                    "wins": s.win_count,
                    "win_rate": round(s.win_count / max(1, s.trade_count) * 100, 1),
                    "enabled": s.enabled,
                    "open_positions": len([p for p in engine.open_positions
                                           if p.strategy == name]),
                }
                for name, s in self.sleeves.items()
            },
        }


# ── Singleton ──
_manager: Optional[PortfolioManager] = None

def get_portfolio_manager() -> PortfolioManager:
    global _manager
    if _manager is None:
        _manager = PortfolioManager()
    return _manager

def init_portfolio_manager(
    total_capital: float = 100_000.0,
    allocations: dict = None,
) -> PortfolioManager:
    global _manager
    _manager = PortfolioManager(total_capital=total_capital, allocations=allocations)
    return _manager
