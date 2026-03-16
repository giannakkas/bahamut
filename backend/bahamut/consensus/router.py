"""Consensus service API routes."""
from fastapi import APIRouter, Depends
from bahamut.auth.router import get_current_user
from bahamut.consensus.engine import PROFILE_THRESHOLDS, BASE_WEIGHTS

router = APIRouter()

@router.get("/thresholds")
async def get_thresholds(user=Depends(get_current_user)):
    return PROFILE_THRESHOLDS

@router.get("/weights/{asset_class}")
async def get_weights(asset_class: str, user=Depends(get_current_user)):
    return BASE_WEIGHTS.get(asset_class, BASE_WEIGHTS["fx"])

@router.get("/health")
async def health():
    return {"status": "healthy", "service": "consensus-svc"}
