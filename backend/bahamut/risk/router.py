"""Risk control API — real data from paper trading portfolio."""
from fastapi import APIRouter, Depends
from bahamut.auth.router import get_current_user

router = APIRouter()

@router.get("/dashboard")
async def risk_dashboard(user=Depends(get_current_user)):
    from bahamut.database import sync_engine
    from sqlalchemy import text
    try:
        with sync_engine.connect() as conn:
            p = conn.execute(text(
                "SELECT current_balance, initial_balance, peak_balance, max_drawdown, total_pnl "
                "FROM paper_portfolios WHERE name = 'SYSTEM_DEMO'"
            )).mappings().first()
            if not p:
                return _default()
            bal = float(p["current_balance"])
            peak = float(p["peak_balance"])
            cur_dd = (peak - bal) / peak if peak > 0 else 0

            pos = conn.execute(text(
                "SELECT direction, position_value, asset FROM paper_positions WHERE status = 'OPEN'"
            )).mappings().all()
            long_exp = sum(float(r["position_value"]) for r in pos if r["direction"] == "LONG")
            short_exp = sum(float(r["position_value"]) for r in pos if r["direction"] == "SHORT")
            net = (long_exp - short_exp) / bal if bal > 0 else 0

            daily_loss = abs(float(conn.execute(text(
                "SELECT COALESCE(SUM(realized_pnl),0) FROM paper_positions "
                "WHERE closed_at > NOW()-INTERVAL '24 hours' AND realized_pnl < 0"
            )).scalar() or 0))
            weekly_loss = abs(float(conn.execute(text(
                "SELECT COALESCE(SUM(realized_pnl),0) FROM paper_positions "
                "WHERE closed_at > NOW()-INTERVAL '7 days' AND realized_pnl < 0"
            )).scalar() or 0))
            dd_d = daily_loss / bal if bal > 0 else 0
            dd_w = weekly_loss / bal if bal > 0 else 0

            return {
                "drawdown": {"daily": round(dd_d, 4), "weekly": round(dd_w, 4),
                             "total": round(cur_dd, 4), "max_historical": round(float(p["max_drawdown"])/100, 4)},
                "limits": {"daily": 0.030, "weekly": 0.060, "total": 0.150},
                "exposure": {"net": round(net, 4),
                             "long": round(long_exp/bal, 4) if bal else 0,
                             "short": round(short_exp/bal, 4) if bal else 0},
                "open_positions": len(pos),
                "open_assets": [r["asset"] for r in pos],
                "circuit_breakers": [
                    {"name": "Drawdown Lock", "active": dd_d > 0.03, "value": round(dd_d, 4), "threshold": 0.03},
                    {"name": "Weekly Drawdown", "active": dd_w > 0.06, "value": round(dd_w, 4), "threshold": 0.06},
                    {"name": "Max Positions", "active": len(pos) >= 5, "value": len(pos), "threshold": 5},
                ],
                "portfolio": {"balance": round(bal, 2), "peak": round(peak, 2),
                              "total_pnl": round(float(p["total_pnl"]), 2)},
            }
    except Exception as e:
        return {**_default(), "note": str(e)}

def _default():
    return {"drawdown": {"daily": 0, "weekly": 0, "total": 0, "max_historical": 0},
            "limits": {"daily": 0.030, "weekly": 0.060, "total": 0.150},
            "exposure": {"net": 0, "long": 0, "short": 0}, "open_positions": 0,
            "open_assets": [], "circuit_breakers": [],
            "portfolio": {"balance": 100000, "peak": 100000, "total_pnl": 0}}

@router.get("/health")
async def health():
    return {"status": "healthy", "service": "risk-svc"}
