"""
Bahamut.AI Adaptive Profile — adjusts trading behavior at runtime.

Rules:
  1. CRISIS regime → auto-downgrade to CONSERVATIVE (if auto_downgrade_on_crisis set)
  2. Losing streak ≥ streak_tighten_after → tighten one level
  3. Winning streak ≥ streak_loosen_after → loosen one level
  4. Meta-learning CRITICAL risk → force CONSERVATIVE
  5. Disallowed regime for current profile → skip trades

All changes are temporary and logged. Profile reverts when conditions normalize.
"""
import structlog
from dataclasses import dataclass

logger = structlog.get_logger()

PROFILE_ORDER = ["CONSERVATIVE", "BALANCED", "AGGRESSIVE"]


@dataclass
class ProfileAdjustment:
    base_profile: str
    effective_profile: str
    adjusted: bool = False
    reasons: list = None

    def __post_init__(self):
        self.reasons = self.reasons or []

    def to_dict(self):
        return {
            "base_profile": self.base_profile,
            "effective_profile": self.effective_profile,
            "adjusted": self.adjusted,
            "reasons": self.reasons,
        }


def resolve_effective_profile(
    base_profile: str,
    regime: str,
    meta_risk_level: str = "NORMAL",
    recent_streak: int = 0,
    profile_config: dict = None,
) -> ProfileAdjustment:
    """
    Resolve the effective trading profile given current conditions.
    May downgrade (never upgrade beyond base).
    """
    profile_config = profile_config or {}
    effective = base_profile
    reasons = []
    idx = PROFILE_ORDER.index(base_profile) if base_profile in PROFILE_ORDER else 1

    # Rule 1: Crisis auto-downgrade
    if regime == "CRISIS" and profile_config.get("auto_downgrade_on_crisis", False):
        effective = "CONSERVATIVE"
        reasons.append(f"CRISIS regime → CONSERVATIVE")
        idx = 0

    # Rule 2: Losing streak tightens
    streak_tighten = profile_config.get("streak_tighten_after", 3)
    if recent_streak <= -streak_tighten and idx > 0:
        idx = max(0, idx - 1)
        effective = PROFILE_ORDER[idx]
        reasons.append(f"Losing streak {recent_streak} ≥ {streak_tighten} → {effective}")

    # Rule 3: Winning streak loosens (only up to base, never beyond)
    streak_loosen = profile_config.get("streak_loosen_after", 7)
    base_idx = PROFILE_ORDER.index(base_profile) if base_profile in PROFILE_ORDER else 1
    if recent_streak >= streak_loosen and idx < base_idx:
        idx = min(base_idx, idx + 1)
        effective = PROFILE_ORDER[idx]
        reasons.append(f"Winning streak {recent_streak} ≥ {streak_loosen} → {effective}")

    # Rule 4: Meta-learning CRITICAL → force CONSERVATIVE
    if meta_risk_level == "CRITICAL":
        effective = "CONSERVATIVE"
        reasons.append("Meta-learning CRITICAL → CONSERVATIVE")

    # Rule 5: Disallowed regime
    allowed = profile_config.get("allowed_regimes", [])
    if allowed and regime not in allowed and regime != "UNKNOWN":
        effective = "CONSERVATIVE"
        reasons.append(f"Regime {regime} not in allowed {allowed} → CONSERVATIVE")

    adjusted = effective != base_profile
    if adjusted:
        logger.info("profile_adjusted", base=base_profile, effective=effective, reasons=reasons)

    return ProfileAdjustment(
        base_profile=base_profile,
        effective_profile=effective,
        adjusted=adjusted,
        reasons=reasons,
    )


def get_recent_streak() -> int:
    """Get current win/loss streak from recent trades."""
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT realized_pnl FROM paper_positions
                WHERE status != 'OPEN'
                ORDER BY closed_at DESC LIMIT 20
            """)).all()
            if not rows:
                return 0
            streak = 0
            first_sign = 1 if float(rows[0][0]) > 0 else -1
            for row in rows:
                if (float(row[0]) > 0) == (first_sign > 0):
                    streak += first_sign
                else:
                    break
            return streak
    except Exception:
        return 0
