"""Stress testing API routes."""
from fastapi import APIRouter, Depends, BackgroundTasks
from bahamut.auth.router import get_current_user

router = APIRouter()


@router.post("/replay")
async def run_replay(
    trust_overrides: dict = None,
    profile: str = None,
    regime: str = None,
    max_traces: int = 50,
    user=Depends(get_current_user),
):
    """Replay recent decision traces with modified parameters."""
    from bahamut.stress.engine import replay_with_modified_params
    result = replay_with_modified_params(
        trust_overrides=trust_overrides,
        profile_override=profile,
        regime_override=regime,
        max_traces=max_traces,
    )
    return result.to_dict()


@router.post("/scenario/{name}")
async def run_single_scenario(name: str, user=Depends(get_current_user)):
    """Run a single named stress scenario."""
    from bahamut.stress.scenarios import SCENARIOS
    from bahamut.stress.engine import run_scenario
    scenario = next((s for s in SCENARIOS if s["name"] == name), None)
    if not scenario:
        return {"error": f"Unknown scenario: {name}",
                "available": [s["name"] for s in SCENARIOS]}
    result = run_scenario(scenario)
    result.scenario_name = name
    return result.to_dict()


@router.post("/run-all")
async def run_all(user=Depends(get_current_user)):
    """Run all predefined stress scenarios."""
    from bahamut.stress.engine import run_all_scenarios
    results = run_all_scenarios()
    return [r.to_dict() for r in results]


@router.get("/scenarios")
async def list_scenarios(user=Depends(get_current_user)):
    """List available stress scenarios."""
    from bahamut.stress.scenarios import SCENARIOS
    return [{"name": s["name"], "description": s["description"]} for s in SCENARIOS]


@router.get("/history")
async def get_history(limit: int = 10, user=Depends(get_current_user)):
    """Get recent stress test results."""
    from bahamut.stress.engine import get_recent_results
    return get_recent_results(limit)


@router.get("/health")
async def health():
    return {"status": "healthy", "service": "stress-test-svc"}
