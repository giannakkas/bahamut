"""Portfolio Intelligence API routes."""
from fastapi import APIRouter, Depends
from bahamut.auth.router import get_current_user

router = APIRouter()


@router.get("/snapshot")
async def get_snapshot(user=Depends(get_current_user)):
    """Get current portfolio snapshot with enriched position data."""
    from bahamut.portfolio.registry import load_portfolio_snapshot
    snap = load_portfolio_snapshot()
    return {
        "balance": round(snap.balance, 2),
        "position_count": snap.position_count,
        "total_value": round(snap.total_position_value, 2),
        "total_risk": round(snap.total_risk, 2),
        "positions": [{
            "id": p.id, "asset": p.asset, "direction": p.direction,
            "value": round(p.position_value, 2), "risk": round(p.risk_amount, 2),
            "unrealized_pnl": round(p.unrealized_pnl, 2),
            "asset_class": p.asset_class, "themes": p.themes,
            "consensus_score": round(p.consensus_score, 3),
        } for p in snap.positions],
    }


@router.get("/exposure")
async def get_exposure(user=Depends(get_current_user)):
    """Get current exposure breakdown."""
    from bahamut.portfolio.registry import load_portfolio_snapshot
    from bahamut.portfolio.engine import _compute_exposure
    snap = load_portfolio_snapshot()
    bal = snap.balance if snap.balance > 0 else 100000.0
    exp = _compute_exposure(snap, "", "LONG", 0, bal)
    return exp.to_dict()


@router.get("/fragility")
async def get_fragility(user=Depends(get_current_user)):
    """Get portfolio fragility assessment."""
    from bahamut.portfolio.registry import load_portfolio_snapshot
    from bahamut.portfolio.engine import _compute_fragility
    snap = load_portfolio_snapshot()
    bal = snap.balance if snap.balance > 0 else 100000.0
    return _compute_fragility(snap, bal).to_dict()


@router.get("/evaluate-impact")
async def evaluate_impact(
    asset: str, direction: str = "LONG", value: float = 2000,
    risk: float = 200, score: float = 0.65,
    user=Depends(get_current_user),
):
    """Simulate adding a trade and see its portfolio impact."""
    from bahamut.portfolio.registry import load_portfolio_snapshot
    from bahamut.portfolio.engine import evaluate_trade_for_portfolio
    snap = load_portfolio_snapshot()
    verdict = evaluate_trade_for_portfolio(snap, asset, direction, value, risk, score)
    return verdict.to_dict()


@router.get("/rankings")
async def get_rankings(user=Depends(get_current_user)):
    """Get all open positions ranked by quality score."""
    from bahamut.portfolio.allocator import get_position_rankings
    return get_position_rankings()


@router.get("/simulate-realloc")
async def simulate_realloc(
    asset: str, direction: str = "LONG",
    score: float = 0.70, label: str = "SIGNAL",
    user=Depends(get_current_user),
):
    """Simulate a reallocation decision without executing."""
    from bahamut.portfolio.allocator import evaluate_reallocation
    return evaluate_reallocation(asset, direction, score, label).to_dict()


@router.get("/reallocation-log")
async def get_realloc_log(limit: int = 20, user=Depends(get_current_user)):
    """Get recent reallocation history."""
    from bahamut.portfolio.allocator import get_reallocation_log
    return get_reallocation_log(limit)


@router.get("/adaptive-rules")
async def get_adaptive_rules(user=Depends(get_current_user)):
    """Get learned adaptive rules from portfolio patterns."""
    from bahamut.portfolio.learning import get_all_rules
    return get_all_rules()


@router.get("/decision-log")
async def get_decision_log_endpoint(limit: int = 20, user=Depends(get_current_user)):
    """Get portfolio decision log (entry/exit events with state snapshots)."""
    from bahamut.portfolio.learning import get_decision_log
    return get_decision_log(limit)


@router.post("/analyze-patterns")
async def trigger_analysis(user=Depends(get_current_user)):
    """Manually trigger portfolio pattern analysis."""
    from bahamut.portfolio.learning import analyze_patterns
    rules = analyze_patterns(lookback_days=30)
    return [r.to_dict() for r in rules]


@router.get("/health")
async def health():
    return {"status": "healthy", "service": "portfolio-intel-svc"}
