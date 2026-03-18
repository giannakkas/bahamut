"""
Bahamut.AI Stress Scenarios — 13 predefined conditions.

Original 8: static overrides (trust, regime, profile, thresholds).
New 5: use mutator functions that modify agent outputs and disagreement
       per-trace during replay, simulating dynamic failure modes.

Mutator signature:
    fn(trace_idx: int, total: int, agents: list[AgentOutputSchema],
       disagree: dict, trace: dict) -> None
    Modifies agents list and disagree dict in place.
"""
import random

# ═══════════════════════════════════════════════════════
# MUTATOR FUNCTIONS (used by advanced scenarios)
# ═══════════════════════════════════════════════════════

def _mutate_regime_flip(trace_idx, total, agents, disagree, trace):
    """
    Regime flips mid-replay: first half RISK_ON, second half CRISIS.
    Simulates a market regime change while positions are open.
    The consensus engine + execution policy see different regimes
    for trades that were originally opened under stable conditions.
    """
    if trace_idx >= total // 2:
        trace["regime"] = "CRISIS"
    else:
        trace["regime"] = "RISK_ON"


def _mutate_stale_agents(trace_idx, total, agents, disagree, trace):
    """
    Progressive agent staleness: agents increasingly time out.
    At trace 0: all agents respond.
    By trace N: 2-3 agents have timed_out=True in meta, reducing
    the pool of directional opinions available to consensus.
    Also reduces confidence of remaining agents by 20% to simulate
    data lag (agent analyzing stale candles).
    """
    progress = trace_idx / max(1, total - 1)  # 0.0 → 1.0
    stale_count = int(progress * 3)  # 0 → 3 agents go stale

    # Deterministic order: liquidity first, then sentiment, then volatility
    stale_order = ["liquidity_agent", "sentiment_agent", "volatility_agent"]
    stale_set = set(stale_order[:stale_count])

    for agent in agents:
        if agent.agent_id in stale_set:
            agent.meta["timed_out"] = True
            agent.confidence = 0.1
        elif stale_count > 0:
            # Remaining agents have slightly degraded confidence (stale data)
            agent.confidence = max(0.3, agent.confidence * (1.0 - progress * 0.2))


def _mutate_disagreement_drift(trace_idx, total, agents, disagree, trace):
    """
    Disagreement index rises linearly from stored value to 0.85.
    Simulates agents gradually losing consensus — like a trend that's
    weakening and agents start disagreeing about direction.
    Gate escalates: CLEAR → APPROVAL_ONLY → BLOCKED over the replay.
    """
    progress = trace_idx / max(1, total - 1)
    base_idx = disagree.get("disagreement_index", 0)
    target = 0.85
    new_idx = base_idx + (target - base_idx) * progress
    disagree["disagreement_index"] = round(new_idx, 4)

    if new_idx >= 0.60:
        disagree["execution_gate"] = "BLOCKED"
        disagree["gate_reasons"] = [f"Drift: idx={new_idx:.3f} >= 0.60"]
    elif new_idx >= 0.40:
        disagree["execution_gate"] = "APPROVAL_ONLY"
        disagree["gate_reasons"] = [f"Drift: idx={new_idx:.3f} >= 0.40"]

    # Also flip some agents to opposing direction to make it realistic
    if progress > 0.3:
        flipped = 0
        for agent in agents:
            if agent.agent_id == "risk_agent":
                continue
            if flipped < int(progress * 2) and agent.directional_bias == "LONG":
                agent.directional_bias = "SHORT"
                flipped += 1


def _mutate_correlated_failure(trace_idx, total, agents, disagree, trace):
    """
    Two correlated agents fail simultaneously: technical + macro both
    go to NEUTRAL with near-zero confidence, and their meta gets
    a STALE_DATA flag. This simulates a data provider outage that
    affects multiple agents sharing the same upstream (e.g. Twelve Data
    goes down, killing both price-based and macro-based analysis).

    The remaining 3 agents still produce opinions, but the system
    has lost its two highest-weighted agents.
    """
    for agent in agents:
        if agent.agent_id in ("technical_agent", "macro_agent"):
            agent.directional_bias = "NEUTRAL"
            agent.confidence = 0.1
            agent.meta["timed_out"] = True
            agent.meta["stale_data"] = True

    # Disagreement rises because only 3 agents contribute
    disagree["disagreement_index"] = max(
        disagree.get("disagreement_index", 0), 0.45)
    if disagree["disagreement_index"] >= 0.40:
        disagree["execution_gate"] = "APPROVAL_ONLY"
        disagree["gate_reasons"].append("Correlated agent failure")


def _mutate_false_high_confidence(trace_idx, total, agents, disagree, trace):
    """
    Inject false high-confidence signals: one agent claims 0.95 confidence
    in the WRONG direction (opposing the majority). The other agents keep
    their original opinions.

    Tests: does the system correctly penalize the overconfident dissenter?
    Does disagreement engine catch the contradiction? Does the consensus
    score drop appropriately despite one very loud agent?

    Rotates the "liar" agent each trace to test all of them.
    """
    agent_order = ["technical_agent", "macro_agent", "sentiment_agent",
                   "volatility_agent", "liquidity_agent"]
    liar_idx = trace_idx % len(agent_order)
    liar_id = agent_order[liar_idx]

    # Find majority direction
    dirs = [a.directional_bias for a in agents
            if a.agent_id != "risk_agent" and a.directional_bias in ("LONG", "SHORT")]
    if not dirs:
        return
    majority = max(set(dirs), key=dirs.count)
    opposite = "SHORT" if majority == "LONG" else "LONG"

    for agent in agents:
        if agent.agent_id == liar_id:
            agent.directional_bias = opposite
            agent.confidence = 0.95
            agent.meta["injected_false_signal"] = True

    # Boost disagreement to reflect the contradiction
    disagree["disagreement_index"] = max(
        disagree.get("disagreement_index", 0), 0.35)


# ═══════════════════════════════════════════════════════
# SCENARIO DEFINITIONS
# ═══════════════════════════════════════════════════════

SCENARIOS = [
    # ── Original 8: static overrides ──
    {
        "name": "crisis_regime_shock",
        "description": "All traces replayed as if CRISIS regime was active. "
                       "Tests: crisis size reduction, CONSERVATIVE auto-downgrade, "
                       "regime-disallowed blocking.",
        "regime": "CRISIS",
        "trust_overrides": None, "profile": None,
        "threshold_overrides": None, "max_traces": 50,
    },
    {
        "name": "trust_collapse",
        "description": "All agent trust scores set to 0.3 (near minimum). "
                       "Tests: trust dampening in consensus, LOW_TRUST execution block.",
        "trust_overrides": {
            "technical_agent": 0.3, "macro_agent": 0.3,
            "sentiment_agent": 0.3, "volatility_agent": 0.3,
            "liquidity_agent": 0.3,
        },
        "regime": None, "profile": None,
        "threshold_overrides": None, "max_traces": 50,
    },
    {
        "name": "conservative_mode",
        "description": "All traces replayed under CONSERVATIVE profile. "
                       "Tests: higher thresholds, no auto-trade, tighter limits.",
        "profile": "CONSERVATIVE",
        "regime": None, "trust_overrides": None,
        "threshold_overrides": None, "max_traces": 50,
    },
    {
        "name": "aggressive_mode",
        "description": "All traces replayed under AGGRESSIVE. "
                       "Tests: would more trades have opened? What P&L?",
        "profile": "AGGRESSIVE",
        "regime": None, "trust_overrides": None,
        "threshold_overrides": None, "max_traces": 50,
    },
    {
        "name": "tight_thresholds",
        "description": "Signal thresholds raised +0.10 across all profiles. "
                       "Tests: how many marginal signals filtered out.",
        "threshold_overrides": {
            "BALANCED": {"strong_signal": 0.82, "signal": 0.68, "weak_signal": 0.55},
            "AGGRESSIVE": {"strong_signal": 0.72, "signal": 0.58, "weak_signal": 0.45},
            "CONSERVATIVE": {"strong_signal": 0.92, "signal": 0.80, "weak_signal": 0.65},
        },
        "regime": None, "trust_overrides": None, "profile": None, "max_traces": 50,
    },
    {
        "name": "technical_agent_failure",
        "description": "Technical agent trust set to 0.1 (effectively removed). "
                       "Tests: system without highest-weighted agent.",
        "trust_overrides": {"technical_agent": 0.1},
        "regime": None, "profile": None,
        "threshold_overrides": None, "max_traces": 50,
    },
    {
        "name": "high_vol_regime",
        "description": "All traces replayed as HIGH_VOL. Volatility agent boosted, "
                       "technical dampened. Tests regime-aware weight shifting.",
        "regime": "HIGH_VOL",
        "trust_overrides": None, "profile": None,
        "threshold_overrides": None, "max_traces": 50,
    },
    {
        "name": "golden_conditions",
        "description": "All trust 1.5, AGGRESSIVE, RISK_ON. "
                       "Tests: maximum throughput and exposure.",
        "regime": "RISK_ON",
        "trust_overrides": {
            "technical_agent": 1.5, "macro_agent": 1.5,
            "sentiment_agent": 1.5, "volatility_agent": 1.5,
            "liquidity_agent": 1.5,
        },
        "profile": "AGGRESSIVE",
        "threshold_overrides": None, "max_traces": 50,
    },

    # ── New 5: dynamic mutator-based scenarios ──
    {
        "name": "regime_flip_mid_trade",
        "description": "Regime flips from RISK_ON to CRISIS halfway through replay. "
                       "First 50%% of traces stay RISK_ON, second 50%% switch to CRISIS. "
                       "Tests: how many trades opened under calm conditions would have been "
                       "blocked or sized down if the regime shifted while positions were open. "
                       "Reveals exposure to regime transition risk.",
        "regime": None, "trust_overrides": None, "profile": None,
        "threshold_overrides": None, "max_traces": 50,
        "mutators": [_mutate_regime_flip],
    },
    {
        "name": "stale_agent_inputs",
        "description": "Agents progressively time out over the replay window. "
                       "At start: all 5 respond. By end: only 2 agents active. "
                       "Remaining agents have degraded confidence (-20%%). "
                       "Simulates data provider outage or API rate limiting "
                       "causing stale/missing inputs. Tests: consensus with "
                       "incomplete information, disagreement engine sensitivity.",
        "regime": None, "trust_overrides": None, "profile": None,
        "threshold_overrides": None, "max_traces": 50,
        "mutators": [_mutate_stale_agents],
    },
    {
        "name": "disagreement_drift",
        "description": "Disagreement index rises linearly from stored value to 0.85 "
                       "over the replay. Gate escalates: CLEAR → APPROVAL_ONLY → BLOCKED. "
                       "Agents gradually flip direction (simulating weakening trend). "
                       "Tests: at what point does the system stop trading? How many "
                       "marginal trades get caught by the escalating gate?",
        "regime": None, "trust_overrides": None, "profile": None,
        "threshold_overrides": None, "max_traces": 50,
        "mutators": [_mutate_disagreement_drift],
    },
    {
        "name": "correlated_agent_failure",
        "description": "Technical + Macro agents fail simultaneously (both go NEUTRAL "
                       "with 0.1 confidence, timed_out=True). Simulates upstream data "
                       "provider outage affecting price and economic data feeds. "
                       "System loses its two highest-weighted agents. "
                       "Tests: can remaining 3 agents carry decisions? Does disagreement "
                       "engine detect reduced input quality?",
        "regime": None, "trust_overrides": None, "profile": None,
        "threshold_overrides": None, "max_traces": 50,
        "mutators": [_mutate_correlated_failure],
    },
    {
        "name": "false_high_confidence",
        "description": "One agent per trace injects 0.95 confidence in the WRONG "
                       "direction (opposing majority). Rotates the 'liar' agent each "
                       "trace. Tests: does consensus correctly downweight the dissenter? "
                       "Does disagreement catch the contradiction? Does a single loud "
                       "wrong voice override 4 correct quiet voices?",
        "regime": None, "trust_overrides": None, "profile": None,
        "threshold_overrides": None, "max_traces": 50,
        "mutators": [_mutate_false_high_confidence],
    },
]
