"""Learning service — real fitness metrics, trust data, calibration history."""
from fastapi import APIRouter, Depends
from bahamut.auth.router import get_current_user
from bahamut.consensus.trust_store import trust_store

router = APIRouter()

@router.get("/trust-scores")
async def get_all_trust(user=Depends(get_current_user)):
    return trust_store.get_all_scores()

@router.get("/trust-summary")
async def get_trust_summary(user=Depends(get_current_user)):
    return trust_store.get_trust_summary()

@router.get("/fitness")
async def strategy_fitness(user=Depends(get_current_user)):
    from bahamut.database import sync_engine
    from sqlalchemy import text
    try:
        with sync_engine.connect() as conn:
            r = conn.execute(text("""
                SELECT COUNT(*) FILTER (WHERE status!='OPEN') as closed,
                       COUNT(*) FILTER (WHERE realized_pnl>0) as wins,
                       COALESCE(SUM(realized_pnl) FILTER (WHERE realized_pnl>0),0) as gross_w,
                       COALESCE(ABS(SUM(realized_pnl) FILTER (WHERE realized_pnl<0)),0.01) as gross_l
                FROM paper_positions
            """)).mappings().first()
            closed = r["closed"] if r else 0
            wr = r["wins"]/closed if closed > 0 else 0
            pf = float(r["gross_w"])/float(r["gross_l"]) if r else 0

            tr = conn.execute(text("""
                SELECT AVG(score) as avg, MIN(score) as mn, MAX(score) as mx,
                       AVG(sample_count) as avg_n FROM trust_scores_live
            """)).mappings().first()
            avg_t = float(tr["avg"]) if tr and tr["avg"] else 1.0
            avg_n = float(tr["avg_n"]) if tr and tr["avg_n"] else 0
            freshness = "mature" if avg_n >= 50 else "learning" if avg_n >= 10 else "cold_start"

            return {"total_closed_trades": closed, "win_rate": round(wr, 3),
                    "profit_factor": round(pf, 2), "avg_trust_score": round(avg_t, 3),
                    "model_freshness": freshness, "avg_samples": round(avg_n, 1),
                    "trust_range": {"min": round(float(tr["mn"]),3) if tr and tr["mn"] else 1.0,
                                    "max": round(float(tr["mx"]),3) if tr and tr["mx"] else 1.0}}
    except Exception as e:
        return {"total_closed_trades": 0, "win_rate": 0, "profit_factor": 0,
                "model_freshness": "cold_start", "note": str(e)}

@router.get("/agent-leaderboard")
async def agent_leaderboard(regime: str = "all", user=Depends(get_current_user)):
    from bahamut.paper_trading.learning import get_agent_leaderboard
    return await get_agent_leaderboard(regime_filter=regime)

@router.get("/regime-performance")
async def regime_performance(user=Depends(get_current_user)):
    """Compare agent accuracy across all regimes."""
    from bahamut.paper_trading.learning import get_regime_performance_comparison
    return await get_regime_performance_comparison()

@router.get("/trust-history")
async def trust_history(agent_id: str = None, limit: int = 50, user=Depends(get_current_user)):
    from bahamut.database import sync_engine
    from sqlalchemy import text
    try:
        with sync_engine.connect() as conn:
            if agent_id:
                rows = conn.execute(text(
                    "SELECT agent_id, dimension, old_score, new_score, change_reason, trade_id, alpha_used, created_at "
                    "FROM trust_score_history_live WHERE agent_id=:a ORDER BY created_at DESC LIMIT :l"
                ), {"a": agent_id, "l": limit}).mappings().all()
            else:
                rows = conn.execute(text(
                    "SELECT agent_id, dimension, old_score, new_score, change_reason, trade_id, alpha_used, created_at "
                    "FROM trust_score_history_live ORDER BY created_at DESC LIMIT :l"
                ), {"l": limit}).mappings().all()
            return [dict(r) for r in rows]
    except Exception:
        return []

@router.get("/calibration-history")
async def calibration_history(limit: int = 10, user=Depends(get_current_user)):
    from bahamut.database import sync_engine
    from sqlalchemy import text
    try:
        with sync_engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT cadence, status, trades_analyzed, threshold_changes, precision_scores, notes, started_at "
                "FROM calibration_runs ORDER BY started_at DESC LIMIT :l"
            ), {"l": limit}).mappings().all()
            return [dict(r) for r in rows]
    except Exception:
        return []

@router.post("/emergency-recalibrate")
async def emergency_recalibrate(user=Depends(get_current_user)):
    from bahamut.learning.calibration import run_emergency_calibration
    result = run_emergency_calibration(reason="manual_api")
    return {"status": "applied", "notes": result.notes}

@router.get("/meta-evaluation")
async def meta_evaluation(user=Depends(get_current_user)):
    """Get latest system-level health report."""
    from bahamut.learning.meta import get_last_report, run_meta_evaluation
    report = get_last_report()
    if not report:
        report = run_meta_evaluation()
    return report.to_dict()

@router.get("/thresholds")
async def get_thresholds(user=Depends(get_current_user)):
    """Get current runtime consensus thresholds (may differ from defaults)."""
    from bahamut.learning.thresholds import get_current_thresholds, BASELINE_THRESHOLDS
    return {"current": get_current_thresholds(), "baseline": BASELINE_THRESHOLDS}

@router.post("/reset-thresholds")
async def reset_thresholds(user=Depends(get_current_user)):
    from bahamut.learning.thresholds import reset_to_defaults
    reset_to_defaults()
    return {"status": "reset_to_defaults"}

@router.get("/health")
async def health():
    return {"status": "healthy", "service": "learning-svc"}
