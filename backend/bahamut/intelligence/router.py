"""
Bahamut.AI — Trust & Intelligence API

Exposes structured endpoints for transparency:
  - Decision explanations
  - Agent leaderboard
  - Learning progress
  - Risk adaptation state
  - Kill switch recovery status
"""
import structlog
from fastapi import APIRouter, Depends, HTTPException

from bahamut.auth.router import get_current_user

logger = structlog.get_logger()
router = APIRouter()


@router.get("/decision/{cycle_id}")
async def get_decision_explanation(cycle_id: str, user=Depends(get_current_user)):
    """Get structured explanation for a specific trade decision."""
    try:
        from bahamut.db.query import run_query_one
        from bahamut.intelligence.decision_explainer import explain_trade_decision

        # Load decision from DB
        decision = run_query_one("""
            SELECT asset, direction, final_score, decision, agreement_pct, regime,
                   execution_mode, agent_contributions, risk_flags
            FROM consensus_decisions WHERE cycle_id = :cid
        """, {"cid": cycle_id})

        if not decision:
            raise HTTPException(status_code=404, detail="Decision not found")

        # Load agent outputs
        import json
        agents = []
        contribs = decision.get("agent_contributions")
        if contribs:
            if isinstance(contribs, str):
                contribs = json.loads(contribs)
            if isinstance(contribs, list):
                agents = contribs

        explanation = explain_trade_decision(decision, agent_outputs=agents)
        explanation["cycle_id"] = cycle_id
        explanation["asset"] = decision.get("asset", "")
        return explanation

    except HTTPException:
        raise
    except Exception as e:
        logger.error("decision_explanation_failed", cycle_id=cycle_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to generate explanation")


@router.get("/agent-leaderboard")
async def get_agent_leaderboard(user=Depends(get_current_user)):
    """Get ranked agent performance leaderboard."""
    try:
        from bahamut.intelligence.agent_performance import get_agent_leaderboard
        return get_agent_leaderboard()
    except Exception as e:
        logger.error("agent_leaderboard_failed", error=str(e))
        return []


@router.get("/learning-progress")
async def get_learning_progress(user=Depends(get_current_user)):
    """Get structured learning progress with milestones."""
    try:
        from bahamut.intelligence.learning_progress import get_learning_progress
        return get_learning_progress()
    except Exception as e:
        logger.error("learning_progress_failed", error=str(e))
        return {
            "status": "unknown",
            "progress": 0,
            "patterns_detected": 0,
            "samples_collected": 0,
            "next_milestone": "Data unavailable",
        }


@router.get("/risk-adaptation")
async def get_risk_adaptation(user=Depends(get_current_user)):
    """Get current adaptive risk state and adjustments."""
    try:
        from bahamut.intelligence.adaptive_risk import compute_adaptive_adjustments
        return compute_adaptive_adjustments()
    except Exception as e:
        logger.error("risk_adaptation_failed", error=str(e))
        return {"conditions": {}, "adjustments": {}, "error": str(e)[:100]}


@router.get("/kill-switch-status")
async def get_kill_switch_recovery(user=Depends(get_current_user)):
    """Get kill switch recovery status including cooldown and gradual re-entry."""
    try:
        from bahamut.intelligence.kill_switch_recovery import get_recovery_status
        return get_recovery_status()
    except Exception as e:
        logger.error("kill_switch_recovery_failed", error=str(e))
        return {"status": "unknown", "error": str(e)[:100]}


@router.get("/ai-reviewer-status")
async def get_ai_reviewer_status(user=Depends(get_current_user)):
    """Get AI consensus reviewer circuit breaker and provider status."""
    from bahamut.consensus.ai_reviewer import get_reviewer_status
    return get_reviewer_status()
