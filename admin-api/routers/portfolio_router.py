from typing import Annotated, Any

from fastapi import APIRouter, Depends

from auth import get_current_user
from models.portfolio import KillSwitchToggle, MarginalRiskData
from services import store

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

User = Annotated[str, Depends(get_current_user)]


@router.get("/marginal-risk", response_model=MarginalRiskData)
async def get_marginal_risk(user: User) -> MarginalRiskData:
    """
    GET /portfolio/marginal-risk
    Response: MarginalRiskData
    """
    return store.get_marginal_risk()


@router.get("/kill-switch")
async def get_kill_switch(user: User) -> dict[str, Any]:
    """
    GET /portfolio/kill-switch
    Response: { active: bool, reason: string | null }
    """
    return store.get_kill_switch()


@router.post("/kill-switch", status_code=200)
async def toggle_kill_switch(body: KillSwitchToggle, user: User) -> dict[str, str]:
    """
    POST /portfolio/kill-switch
    Request:  { active: bool }
    Response: { status: "ok" }
    """
    store.toggle_kill_switch(body.active)
    return {"status": "ok"}
