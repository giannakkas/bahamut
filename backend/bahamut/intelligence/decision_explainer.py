"""
Bahamut.AI — Decision Explainability Engine

Generates deterministic, structured explanations for every trade decision,
block, or kill-switch event. All reasoning derived from real signals — no hallucination.
"""
import structlog

logger = structlog.get_logger()


def explain_trade_decision(decision: dict, verdict: dict = None,
                            agent_outputs: list = None) -> dict:
    """Generate structured explanation for a trade decision.

    Args:
        decision: consensus decision dict (direction, final_score, decision label, etc.)
        verdict: portfolio verdict dict (if available)
        agent_outputs: list of agent output dicts
    """
    direction = decision.get("direction", "NONE")
    score = decision.get("final_score", 0)
    label = decision.get("decision", "NO_TRADE")
    agreement = decision.get("agreement_pct", 0)
    regime = decision.get("regime", "unknown")

    key_factors = []
    risk_flags = []

    # ── Agent consensus analysis ──
    if agreement >= 0.8:
        key_factors.append("Strong multi-agent agreement ({:.0%})".format(agreement))
    elif agreement >= 0.6:
        key_factors.append("Moderate agent agreement ({:.0%})".format(agreement))
    else:
        risk_flags.append("Low agent agreement ({:.0%}) — high disagreement".format(agreement))

    # ── Score analysis ──
    if score >= 0.72:
        key_factors.append("High confidence score ({:.2f})".format(score))
    elif score >= 0.58:
        key_factors.append("Acceptable confidence score ({:.2f})".format(score))
    else:
        risk_flags.append("Below-threshold confidence ({:.2f})".format(score))

    # ── Regime context ──
    safe_regimes = {"RISK_ON", "LOW_VOL", "TREND_CONTINUATION"}
    if regime in safe_regimes:
        key_factors.append("Favorable market regime ({})".format(regime))
    elif regime in {"HIGH_VOL", "RISK_OFF"}:
        risk_flags.append("Elevated risk regime ({})".format(regime))
    elif regime in {"CRISIS", "EVENT_DRIVEN"}:
        risk_flags.append("Crisis/event regime ({}) — heightened caution".format(regime))

    # ── Portfolio verdict analysis ──
    if verdict:
        if verdict.get("allowed") is False:
            blockers = verdict.get("blockers", [])
            for b in blockers[:3]:
                risk_flags.append(b)

        impact = verdict.get("impact_score", 0)
        if impact > 0.2:
            key_factors.append("Trade improves portfolio diversification (impact {:.2f})".format(impact))
        elif impact < -0.2:
            risk_flags.append("Trade increases portfolio concentration (impact {:.2f})".format(impact))

        size_mult = verdict.get("size_multiplier", 1.0)
        if size_mult < 0.8:
            risk_flags.append("Position size reduced to {:.0%} by portfolio engine".format(size_mult))

        ks = verdict.get("kill_switch_state", {})
        if ks.get("kill_switch_active"):
            risk_flags.append("Kill switch active — all new trades blocked")
        elif ks.get("safe_mode_active"):
            risk_flags.append("Safe mode active — tighter position limits")

    # ── Agent-level analysis ──
    if agent_outputs:
        bullish = sum(1 for a in agent_outputs if a.get("directional_bias") == "LONG")
        bearish = sum(1 for a in agent_outputs if a.get("directional_bias") == "SHORT")
        if bullish > bearish + 2:
            key_factors.append("{} of {} agents bullish".format(bullish, len(agent_outputs)))
        elif bearish > bullish + 2:
            key_factors.append("{} of {} agents bearish".format(bearish, len(agent_outputs)))

        high_conf = [a for a in agent_outputs if a.get("confidence", 0) >= 0.8]
        if high_conf:
            names = [a.get("agent_id", "?") for a in high_conf[:3]]
            key_factors.append("High-confidence agents: {}".format(", ".join(names)))

    # ── Decision type mapping ──
    if label in ("STRONG_SIGNAL", "SIGNAL"):
        decision_type = "approve_trade"
        summary = _build_approve_summary(direction, score, key_factors, risk_flags)
    elif label == "NO_TRADE":
        decision_type = "reject_trade"
        summary = _build_reject_summary(risk_flags, score)
    else:
        decision_type = "reject_trade"
        summary = "Trade not executed: {}".format(label.replace("_", " ").lower())

    return {
        "decision": decision_type,
        "direction": direction,
        "confidence_score": round(score, 3),
        "risk_score": round(1.0 - score, 3),
        "key_factors": key_factors[:5],
        "risk_flags": risk_flags[:5],
        "summary": summary,
        "regime": regime,
        "agreement_pct": round(agreement, 3),
    }


def explain_kill_switch(state: dict) -> dict:
    """Generate explanation for kill switch activation."""
    triggers = state.get("triggers", [])
    key_factors = []
    for t in triggers[:3]:
        key_factors.append(t)

    return {
        "decision": "kill_switch_trigger",
        "confidence_score": 0,
        "risk_score": 1.0,
        "key_factors": [],
        "risk_flags": key_factors,
        "summary": "Kill switch activated: {}".format(
            triggers[0] if triggers else "portfolio risk exceeded safety thresholds"),
    }


def _build_approve_summary(direction, score, factors, flags):
    parts = ["Trade {} approved".format(direction)]
    if factors:
        parts.append("due to " + factors[0].lower())
    if flags:
        parts.append("despite " + flags[0].lower())
    return ". ".join(parts) + "."


def _build_reject_summary(flags, score):
    if flags:
        return "Trade blocked: {}.".format(flags[0])
    return "Trade not executed: confidence score {:.2f} below threshold.".format(score)
