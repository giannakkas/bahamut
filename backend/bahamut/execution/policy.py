"""
Bahamut.AI Execution Policy — authoritative gate between signal and trade.

No trade executes without passing through this layer.
9 hard blockers + soft sizing constraints.
"""
import structlog
from dataclasses import dataclass, field

logger = structlog.get_logger()


@dataclass
class ExecutionRequest:
    asset: str
    direction: str
    consensus_score: float
    signal_label: str
    execution_mode_from_consensus: str  # AUTO, APPROVAL, WATCH
    disagreement_gate: str              # CLEAR, APPROVAL_ONLY, BLOCKED
    disagreement_index: float = 0.0
    risk_flags: list[str] = field(default_factory=list)
    risk_can_trade: bool = True
    trading_profile: str = "BALANCED"
    current_drawdown_daily: float = 0.0
    current_drawdown_weekly: float = 0.0
    open_position_count: int = 0
    has_position_in_asset: bool = False
    portfolio_balance: float = 100000.0
    regime: str = "RISK_ON"
    mean_agent_trust: float = 1.0       # avg trust of contributing agents
    system_confidence: float = 0.5      # composite: trust stability + disagreement + perf + calib


@dataclass
class ExecutionDecision:
    allowed: bool
    mode: str       # PAPER_AUTO, PAPER_APPROVAL, BLOCKED
    reason: str
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    position_size_multiplier: float = 1.0
    requires_approval: bool = False

    def to_dict(self):
        return {
            "allowed": self.allowed, "mode": self.mode, "reason": self.reason,
            "blockers": self.blockers, "warnings": self.warnings,
            "position_size_multiplier": self.position_size_multiplier,
            "requires_approval": self.requires_approval,
        }


PROFILE_LIMITS = {
    "CONSERVATIVE": {
        "max_daily_drawdown": 0.02, "max_weekly_drawdown": 0.04,
        "max_concurrent_trades": 3, "min_consensus_score": 0.65,
        "auto_trade_allowed": False, "max_position_pct": 0.02,
    },
    "BALANCED": {
        "max_daily_drawdown": 0.03, "max_weekly_drawdown": 0.06,
        "max_concurrent_trades": 5, "min_consensus_score": 0.55,
        "auto_trade_allowed": True, "max_position_pct": 0.03,
    },
    "AGGRESSIVE": {
        "max_daily_drawdown": 0.05, "max_weekly_drawdown": 0.10,
        "max_concurrent_trades": 8, "min_consensus_score": 0.45,
        "auto_trade_allowed": True, "max_position_pct": 0.05,
    },
}


class ExecutionPolicy:

    def evaluate(self, req: ExecutionRequest) -> ExecutionDecision:
        blockers, warnings = [], []
        size_mult = 1.0
        limits = PROFILE_LIMITS.get(req.trading_profile, PROFILE_LIMITS["BALANCED"])

        # ── HARD BLOCKERS ──
        if not req.risk_can_trade:
            blockers.append(f"RISK_VETO: {', '.join(req.risk_flags)}")
        if req.current_drawdown_daily >= limits["max_daily_drawdown"]:
            blockers.append(f"DAILY_DD: {req.current_drawdown_daily:.2%} >= {limits['max_daily_drawdown']:.2%}")
        if req.current_drawdown_weekly >= limits["max_weekly_drawdown"]:
            blockers.append(f"WEEKLY_DD: {req.current_drawdown_weekly:.2%} >= {limits['max_weekly_drawdown']:.2%}")
        if req.open_position_count >= limits["max_concurrent_trades"]:
            blockers.append(f"MAX_POSITIONS: {req.open_position_count} >= {limits['max_concurrent_trades']}")
        if req.has_position_in_asset:
            blockers.append(f"DUPLICATE: Already in {req.asset}")
        if req.consensus_score < limits["min_consensus_score"]:
            blockers.append(f"SCORE_LOW: {req.consensus_score:.3f} < {limits['min_consensus_score']:.3f}")
        if req.disagreement_gate == "BLOCKED":
            blockers.append(f"DISAGREEMENT_BLOCKED: idx={req.disagreement_index:.3f}")
        if req.regime == "CRISIS" and req.trading_profile == "CONSERVATIVE":
            blockers.append("CRISIS_REGIME: Conservative blocks in crisis")
        hard_flags = {"DAILY_DD_WARNING", "WEEKLY_DD_WARNING", "STALE_DATA", "BROKER_FAILURE"}
        active = set(req.risk_flags) & hard_flags
        if active:
            blockers.append(f"RISK_FLAGS: {', '.join(active)}")

        # ── SOFT CONSTRAINTS ──
        if req.regime == "CRISIS" and not blockers:
            size_mult *= 0.5
            warnings.append("CRISIS: size halved")
        if req.disagreement_gate == "APPROVAL_ONLY":
            size_mult *= 0.5
            warnings.append(f"DISAGREEMENT: size halved (idx={req.disagreement_index:.3f})")
        if "HIGH_CORRELATION" in req.risk_flags:
            size_mult *= 0.7
            warnings.append("CORR: size -30%")
        if "HIGH_EXPOSURE" in req.risk_flags:
            size_mult *= 0.7
            warnings.append("EXPOSURE: size -30%")

        # System confidence constraints (composite: trust + disagreement + perf + calib)
        sc = req.system_confidence
        if sc < 0.25:
            blockers.append(f"LOW_CONFIDENCE: system={sc:.3f} < 0.25")
        elif sc < 0.40:
            warnings.append(f"LOW_CONFIDENCE: approval required (system={sc:.3f})")
        elif sc < 0.60:
            conf_size = 0.4 + sc  # 0.40→0.80, 0.50→0.90, 0.59→0.99
            size_mult *= conf_size
            warnings.append(f"CONFIDENCE: size x{conf_size:.2f} (system={sc:.3f})")

        # Raw trust floor — even if system_confidence is OK, collapsed trust is dangerous
        if req.mean_agent_trust < 0.5:
            blockers.append(f"TRUST_FLOOR: mean trust {req.mean_agent_trust:.2f} < 0.50")

        if blockers:
            return ExecutionDecision(allowed=False, mode="BLOCKED", reason=blockers[0],
                                     blockers=blockers, warnings=warnings, position_size_multiplier=0.0)

        if req.execution_mode_from_consensus == "WATCH":
            return ExecutionDecision(allowed=False, mode="BLOCKED", reason="WATCH mode",
                                     blockers=["WATCH_MODE"], warnings=warnings)

        approval = (not limits["auto_trade_allowed"]
                     or req.disagreement_gate == "APPROVAL_ONLY"
                     or req.execution_mode_from_consensus == "APPROVAL"
                     or req.system_confidence < 0.40)
        mode = "PAPER_APPROVAL" if approval else "PAPER_AUTO"
        size_mult = max(0.1, min(1.0, size_mult))

        logger.info("exec_policy", asset=req.asset, allowed=True, mode=mode,
                     size=size_mult, warnings=len(warnings))

        return ExecutionDecision(allowed=True, mode=mode, reason="All gates passed",
                                 warnings=warnings, position_size_multiplier=round(size_mult, 2),
                                 requires_approval=approval)


execution_policy = ExecutionPolicy()
