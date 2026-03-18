"""Consensus service API routes."""
from fastapi import APIRouter, Depends
from bahamut.auth.router import get_current_user
from bahamut.consensus.engine import PROFILE_THRESHOLDS, BASE_WEIGHTS
from bahamut.consensus.disagreement import GATE_THRESHOLDS, COMPONENT_WEIGHTS
from bahamut.consensus.weights import weight_resolver

router = APIRouter()

@router.get("/thresholds")
async def get_thresholds(user=Depends(get_current_user)):
    return PROFILE_THRESHOLDS

@router.get("/weights/{asset_class}")
async def get_weights(asset_class: str, user=Depends(get_current_user)):
    return BASE_WEIGHTS.get(asset_class, BASE_WEIGHTS["fx"])

@router.get("/weights-dynamic/{asset_class}")
async def get_dynamic_weights(asset_class: str, regime: str = "RISK_ON",
                               timeframe: str = "4H", user=Depends(get_current_user)):
    from bahamut.consensus.trust_store import trust_store
    ts = trust_store.get_scores_for_context(regime, asset_class, timeframe)
    return {
        "resolved": weight_resolver.resolve_weights(asset_class, regime, timeframe, ts),
        "explanation": weight_resolver.get_weight_explanation(asset_class, regime, timeframe, ts),
    }

@router.get("/disagreement-config")
async def get_disagreement_config(user=Depends(get_current_user)):
    return {"gate_thresholds": GATE_THRESHOLDS, "component_weights": COMPONENT_WEIGHTS}

@router.get("/health")
async def health():
    return {"status": "healthy", "service": "consensus-svc"}
