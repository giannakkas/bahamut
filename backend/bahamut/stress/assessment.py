"""
Bahamut.AI Stress Assessment

Reads recent stress_test_runs from DB and produces a structured assessment
that readiness, thresholds, and profile adapter can consume.

Key outputs:
  crisis_resilience: 0-1 — would the system survive a crisis?
  trust_fragility: 0-1 — how sensitive is the system to trust collapse?
  threshold_adequacy: 0-1 — are current thresholds filtering bad trades?
  decision_stability: 0-1 — how much do decisions change under stress?
  recommended_action: TIGHTEN / LOOSEN / HOLD / DOWNGRADE_PROFILE
"""
import structlog
from dataclasses import dataclass, field

logger = structlog.get_logger()


@dataclass
class StressAssessment:
    has_recent_results: bool = False
    crisis_resilience: float = 0.5       # would trades survive crisis regime?
    trust_fragility: float = 0.5         # how many trades break under trust collapse?
    threshold_adequacy: float = 0.5      # do tight thresholds improve simulated win rate?
    decision_stability: float = 0.5      # avg % of decisions unchanged across scenarios
    agent_redundancy: float = 0.5        # can the system survive correlated agent failure?
    overall_stress_score: float = 0.5    # composite 0-1
    recommended_actions: list = field(default_factory=list)
    scenario_summaries: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "has_recent_results": self.has_recent_results,
            "crisis_resilience": round(self.crisis_resilience, 3),
            "trust_fragility": round(self.trust_fragility, 3),
            "threshold_adequacy": round(self.threshold_adequacy, 3),
            "decision_stability": round(self.decision_stability, 3),
            "agent_redundancy": round(self.agent_redundancy, 3),
            "overall_stress_score": round(self.overall_stress_score, 3),
            "recommended_actions": self.recommended_actions,
            "scenario_summaries": self.scenario_summaries,
        }


_cache: dict = {"value": None, "computed_at": 0}
CACHE_TTL = 300  # 5 min


def get_stress_assessment() -> StressAssessment:
    """Get cached stress assessment (recomputes every 5 min)."""
    import time
    now = time.time()
    if _cache["value"] is not None and (now - _cache["computed_at"]) < CACHE_TTL:
        return _cache["value"]
    return compute_stress_assessment()


def compute_stress_assessment() -> StressAssessment:
    """Compute stress assessment from recent stress_test_runs."""
    import time
    sa = StressAssessment()

    results = _load_recent_by_scenario()
    if not results:
        _cache["value"] = sa
        _cache["computed_at"] = time.time()
        return sa

    sa.has_recent_results = True
    actions = []

    # ── Crisis resilience ──
    crisis = results.get("crisis_regime_shock")
    if crisis:
        sa.scenario_summaries["crisis_regime_shock"] = _summarize(crisis)
        total = crisis.get("total_signals", 0)
        if total > 0:
            block_rate = crisis.get("would_block", 0) / total
            # High block rate under crisis = system would protect itself = good
            sa.crisis_resilience = round(min(1.0, block_rate * 1.3), 3)
            if sa.crisis_resilience < 0.5:
                actions.append({"target": "profile", "action": "DOWNGRADE_PROFILE",
                                "reason": f"Crisis scenario: only {block_rate:.0%} of trades blocked"})

    # ── Trust fragility ──
    trust_col = results.get("trust_collapse")
    if trust_col:
        sa.scenario_summaries["trust_collapse"] = _summarize(trust_col)
        total = trust_col.get("total_signals", 0)
        if total > 0:
            block_rate = trust_col.get("would_block", 0) / total
            changed = trust_col.get("changed_decisions", 0) / total
            # If trust collapse blocks most trades → system is protected → low fragility
            sa.trust_fragility = round(max(0.0, 1.0 - block_rate), 3)
            if sa.trust_fragility > 0.6:
                actions.append({"target": "thresholds", "action": "TIGHTEN",
                                "reason": f"Trust collapse: {(1-block_rate):.0%} of trades still pass"})

    # ── Threshold adequacy ──
    tight = results.get("tight_thresholds")
    normal_wr = None
    if tight:
        sa.scenario_summaries["tight_thresholds"] = _summarize(tight)
        tight_wr = tight.get("win_rate_simulated", 0)
        # Compare with golden conditions or aggressive as baseline
        golden = results.get("golden_conditions")
        if golden and golden.get("win_rate_simulated", 0) > 0:
            normal_wr = golden.get("win_rate_simulated", 0)
            if tight_wr > normal_wr + 0.05:
                sa.threshold_adequacy = 0.3  # tight thresholds improve WR → current too loose
                actions.append({"target": "thresholds", "action": "TIGHTEN",
                                "reason": f"Tight thresholds WR {tight_wr:.1%} > normal {normal_wr:.1%}"})
            elif tight_wr < normal_wr - 0.10:
                sa.threshold_adequacy = 0.9  # tight thresholds hurt → current are good
            else:
                sa.threshold_adequacy = 0.6  # similar → current are adequate
        else:
            sa.threshold_adequacy = 0.5

    # ── Decision stability ──
    stability_scores = []
    for name, data in results.items():
        total = data.get("total_signals", 0)
        if total >= 3:
            unchanged_rate = 1.0 - (data.get("changed_decisions", 0) / total)
            stability_scores.append(unchanged_rate)
            sa.scenario_summaries.setdefault(name, _summarize(data))
    if stability_scores:
        sa.decision_stability = round(sum(stability_scores) / len(stability_scores), 3)
        if sa.decision_stability < 0.5:
            actions.append({"target": "thresholds", "action": "TIGHTEN",
                            "reason": f"Low decision stability: {sa.decision_stability:.1%} avg unchanged"})

    # ── Agent redundancy ──
    corr_fail = results.get("correlated_agent_failure")
    if corr_fail:
        sa.scenario_summaries["correlated_agent_failure"] = _summarize(corr_fail)
        total = corr_fail.get("total_signals", 0)
        if total > 0:
            still_open = corr_fail.get("would_open", 0) / total
            # If system still opens trades when 2 agents die → has redundancy
            # But opening too many is also bad (no quality control)
            if 0.2 <= still_open <= 0.6:
                sa.agent_redundancy = 0.8  # balanced — some filtered, some pass
            elif still_open < 0.2:
                sa.agent_redundancy = 0.4  # too dependent on failed agents
            else:
                sa.agent_redundancy = 0.3  # insufficient filtering when agents fail

    # ── Overall ──
    sa.overall_stress_score = round(
        0.25 * sa.crisis_resilience
        + 0.20 * (1.0 - sa.trust_fragility)  # invert: low fragility = good
        + 0.20 * sa.threshold_adequacy
        + 0.20 * sa.decision_stability
        + 0.15 * sa.agent_redundancy,
        3,
    )

    # Deduplicate actions by target+action
    seen = set()
    unique_actions = []
    for a in actions:
        key = f"{a['target']}:{a['action']}"
        if key not in seen:
            seen.add(key)
            unique_actions.append(a)
    sa.recommended_actions = unique_actions

    _cache["value"] = sa
    _cache["computed_at"] = __import__("time").time()

    logger.info("stress_assessment_computed", score=sa.overall_stress_score,
                 actions=len(sa.recommended_actions))
    return sa


def _load_recent_by_scenario() -> dict:
    """Load most recent stress result per scenario from DB."""
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT DISTINCT ON (scenario_name)
                    scenario_name, total_signals, would_open, would_block,
                    changed_decisions, avg_size_mult, blockers, warnings,
                    created_at
                FROM stress_test_runs
                WHERE created_at > NOW() - INTERVAL '7 days'
                ORDER BY scenario_name, created_at DESC
            """)).mappings().all()
            result = {}
            for r in rows:
                d = dict(r)
                d["win_rate_simulated"] = 0  # not stored in DB, but captured in memory results
                result[r["scenario_name"]] = d
            return result
    except Exception as e:
        logger.debug("stress_load_failed", error=str(e))
        return {}


def _summarize(data: dict) -> dict:
    total = data.get("total_signals", 0)
    return {
        "total": total,
        "would_open": data.get("would_open", 0),
        "would_block": data.get("would_block", 0),
        "changed": data.get("changed_decisions", 0),
        "change_rate": round(data.get("changed_decisions", 0) / total, 2) if total > 0 else 0,
    }
