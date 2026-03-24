"""
Bahamut.AI — Training Operations API

Dedicated endpoint for the Training Operations page.
Returns comprehensive metrics, tables, and health indicators
for the 50-asset paper-training universe.

Completely isolated from production BTC/ETH data.
"""
import json
import os
import structlog
from datetime import datetime, timezone
from fastapi import APIRouter, Depends

from bahamut.auth.router import get_current_user

logger = structlog.get_logger()
router = APIRouter()


def _get_redis():
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        r.ping()
        return r
    except Exception:
        return None


@router.get("/operations")
async def get_training_operations(user=Depends(get_current_user)):
    """Full training operations dashboard data."""
    r = _get_redis()
    now = datetime.now(timezone.utc)

    result = {
        "generated_at": now.isoformat(),
        "kpi": _build_kpi(r),
        "cycle_health": _build_cycle_health(r),
        "positions": _build_positions(r),
        "closed_trades": _build_closed_trades(),
        "strategy_breakdown": _build_strategy_breakdown(r),
        "class_breakdown": _build_class_breakdown(r),
        "asset_rankings": _build_asset_rankings(),
        "learning": _build_learning_feed(),
        "exposure": _build_exposure(r),
        "alerts": _build_alerts(r),
    }
    return result


def _build_kpi(r) -> dict:
    """Top KPI row data."""
    from bahamut.config_assets import TRAINING_ASSETS, TRAINING_VIRTUAL_CAPITAL

    kpi = {
        "universe_size": len(TRAINING_ASSETS),
        "virtual_capital": TRAINING_VIRTUAL_CAPITAL,
        "assets_scanned": 0,
        "open_positions": 0,
        "closed_trades": 0,
        "net_pnl": 0,
        "win_rate": 0,
        "avg_duration_bars": 0,
        "last_cycle": None,
        "cycle_status": "unknown",
        "learning_samples": 0,
    }

    # From Redis cycle stats
    if r:
        try:
            raw = r.get("bahamut:training:last_cycle")
            if raw:
                lc = json.loads(raw)
                kpi["assets_scanned"] = lc.get("processed", 0)
                kpi["last_cycle"] = lc.get("last_cycle")
                kpi["cycle_status"] = "OK" if lc.get("processed", 0) > 0 else "IDLE"
        except Exception:
            pass

    # From Redis positions
    from bahamut.training.engine import get_open_position_count
    kpi["open_positions"] = get_open_position_count()

    # From DB aggregate
    try:
        from bahamut.db.query import run_query_one
        row = run_query_one("""
            SELECT COUNT(*) as cnt,
                   COALESCE(SUM(pnl), 0) as total_pnl,
                   SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                   COALESCE(AVG(bars_held), 0) as avg_bars
            FROM training_trades
        """)
        if row:
            kpi["closed_trades"] = int(row.get("cnt", 0))
            kpi["net_pnl"] = round(float(row.get("total_pnl", 0) or 0), 2)
            wins = int(row.get("wins", 0))
            kpi["win_rate"] = round(wins / max(1, kpi["closed_trades"]), 4)
            kpi["avg_duration_bars"] = round(float(row.get("avg_bars", 0) or 0), 1)
            kpi["learning_samples"] = kpi["closed_trades"]
    except Exception:
        pass

    # Fallback: Redis stats
    if kpi["closed_trades"] == 0 and r:
        try:
            total = 0
            for strat in ["v5_base", "v5_tuned", "v9_breakout"]:
                raw = r.get(f"bahamut:training:strategy_stats:{strat}")
                if raw:
                    s = json.loads(raw)
                    total += s.get("trades", 0)
                    kpi["net_pnl"] += s.get("total_pnl", 0)
            kpi["closed_trades"] = total
            kpi["learning_samples"] = total
        except Exception:
            pass

    return kpi


def _build_cycle_health(r) -> dict:
    """Training cycle health section."""
    health = {
        "status": "unknown",
        "duration_ms": 0,
        "assets_processed": 0,
        "assets_skipped": 0,
        "errors": 0,
        "signals_generated": 0,
        "trades_opened": 0,
        "trades_closed": 0,
        "last_run": None,
    }

    if not r:
        return health

    try:
        raw = r.get("bahamut:training:last_cycle")
        if raw:
            lc = json.loads(raw)
            from bahamut.config_assets import TRAINING_ASSETS
            processed = lc.get("processed", 0)
            errors = lc.get("errors", 0)
            health["status"] = "OK" if processed > 0 and errors == 0 else "DEGRADED" if processed > 0 else "FAILED"
            health["duration_ms"] = lc.get("duration_ms", 0)
            health["assets_processed"] = processed
            health["assets_skipped"] = len(TRAINING_ASSETS) - processed - errors
            health["errors"] = errors
            health["signals_generated"] = lc.get("signals", 0)
            health["trades_opened"] = lc.get("signals", 0)  # signals ≈ opened in training
            health["trades_closed"] = lc.get("trades_closed", 0)
            health["last_run"] = lc.get("last_cycle")
    except Exception:
        pass

    return health


def _build_positions(r) -> list[dict]:
    """Open positions table."""
    from bahamut.training.engine import _load_positions
    from dataclasses import asdict
    positions = _load_positions()
    return [
        {
            **asdict(p),
            "unrealized_pnl": round(p.unrealized_pnl, 2),
            "duration_bars": p.bars_held,
        }
        for p in positions
    ]


def _build_closed_trades() -> list[dict]:
    """Recent closed trades table (last 50)."""
    try:
        from bahamut.db.query import run_query
        rows = run_query("""
            SELECT trade_id, asset, asset_class, strategy, direction,
                   entry_price, exit_price, stop_price, tp_price,
                   pnl, pnl_pct, exit_reason, bars_held,
                   entry_time, exit_time, regime
            FROM training_trades
            ORDER BY created_at DESC LIMIT 50
        """)
        return [dict(r) for r in rows] if rows else []
    except Exception:
        pass

    # Fallback: Redis recent trades
    if _get_redis():
        try:
            from bahamut.training.engine import get_test_trades_from_redis
            return get_test_trades_from_redis()
        except Exception:
            pass
    return []


def _build_strategy_breakdown(r) -> dict:
    """Per-strategy breakdown."""
    strategies = {}
    for strat in ["v5_base", "v5_tuned", "v9_breakout"]:
        stats = {
            "open_trades": 0, "closed_trades": 0, "win_rate": 0,
            "profit_factor": 0, "avg_pnl": 0, "total_pnl": 0,
            "avg_hold_bars": 0, "provisional": True,
        }

        # DB stats
        try:
            from bahamut.db.query import run_query_one
            row = run_query_one("""
                SELECT COUNT(*) as cnt,
                       SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                       COALESCE(SUM(pnl), 0) as total_pnl,
                       COALESCE(AVG(pnl), 0) as avg_pnl,
                       COALESCE(AVG(bars_held), 0) as avg_bars,
                       COALESCE(SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END), 0) as gp,
                       COALESCE(SUM(CASE WHEN pnl < 0 THEN ABS(pnl) ELSE 0 END), 0) as gl
                FROM training_trades WHERE strategy = :s
            """, {"s": strat})
            if row and int(row.get("cnt", 0)) > 0:
                cnt = int(row["cnt"])
                wins = int(row.get("wins", 0))
                stats["closed_trades"] = cnt
                stats["win_rate"] = round(wins / max(1, cnt), 4)
                stats["total_pnl"] = round(float(row.get("total_pnl", 0) or 0), 2)
                stats["avg_pnl"] = round(float(row.get("avg_pnl", 0) or 0), 2)
                stats["avg_hold_bars"] = round(float(row.get("avg_bars", 0) or 0), 1)
                gp = float(row.get("gp", 0) or 0)
                gl = float(row.get("gl", 0) or 0)
                stats["profit_factor"] = round(gp / max(gl, 0.01), 2)
                stats["provisional"] = cnt < 10
        except Exception:
            pass

        # Redis fallback
        if stats["closed_trades"] == 0 and r:
            try:
                raw = r.get(f"bahamut:training:strategy_stats:{strat}")
                if raw:
                    s = json.loads(raw)
                    stats["closed_trades"] = s.get("trades", 0)
                    stats["win_rate"] = s.get("win_rate", 0)
                    stats["total_pnl"] = s.get("total_pnl", 0)
                    stats["provisional"] = s.get("trades", 0) < 10
            except Exception:
                pass

        # Count open positions for this strategy
        from bahamut.training.engine import _load_positions
        stats["open_trades"] = len([p for p in _load_positions() if p.strategy == strat])

        strategies[strat] = stats

    return strategies


def _build_class_breakdown(r) -> dict:
    """Per-asset-class breakdown."""
    classes = {}
    for cls in ["crypto", "forex", "index", "commodity", "stock"]:
        stats = {"open_trades": 0, "closed_trades": 0, "pnl": 0, "win_rate": 0, "signals": 0}

        try:
            from bahamut.db.query import run_query_one
            row = run_query_one("""
                SELECT COUNT(*) as cnt,
                       SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                       COALESCE(SUM(pnl), 0) as total_pnl
                FROM training_trades WHERE asset_class = :c
            """, {"c": cls})
            if row and int(row.get("cnt", 0)) > 0:
                cnt = int(row["cnt"])
                stats["closed_trades"] = cnt
                stats["pnl"] = round(float(row.get("total_pnl", 0) or 0), 2)
                stats["win_rate"] = round(int(row.get("wins", 0)) / max(1, cnt), 4)
                stats["signals"] = cnt
        except Exception:
            pass

        # Redis fallback
        if stats["closed_trades"] == 0 and r:
            try:
                raw = r.get(f"bahamut:training:class_stats:{cls}")
                if raw:
                    s = json.loads(raw)
                    stats["closed_trades"] = s.get("trades", 0)
                    stats["pnl"] = s.get("total_pnl", 0)
                    stats["win_rate"] = s.get("win_rate", 0)
            except Exception:
                pass

        # Open positions
        from bahamut.training.engine import _load_positions
        from bahamut.config_assets import ASSET_CLASS_MAP
        stats["open_trades"] = len([p for p in _load_positions() if ASSET_CLASS_MAP.get(p.asset) == cls])

        classes[cls] = stats

    return classes


def _build_asset_rankings() -> dict:
    """Best/worst/most active assets."""
    rankings = {"best": [], "worst": [], "most_active": []}
    try:
        from bahamut.db.query import run_query
        # Best by PnL (min 2 trades)
        best = run_query("""
            SELECT asset, asset_class, COUNT(*) as trades,
                   SUM(pnl) as total_pnl, AVG(pnl) as avg_pnl,
                   SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END)::float / COUNT(*) as wr
            FROM training_trades GROUP BY asset, asset_class
            HAVING COUNT(*) >= 2 ORDER BY total_pnl DESC LIMIT 10
        """)
        if best:
            rankings["best"] = [
                {"asset": r["asset"], "class": r.get("asset_class", ""), "trades": int(r["trades"]),
                 "pnl": round(float(r["total_pnl"]), 2), "avg_pnl": round(float(r.get("avg_pnl", 0)), 2),
                 "win_rate": round(float(r.get("wr", 0)), 3)}
                for r in best[:5]
            ]
            rankings["worst"] = [
                {"asset": r["asset"], "class": r.get("asset_class", ""), "trades": int(r["trades"]),
                 "pnl": round(float(r["total_pnl"]), 2), "avg_pnl": round(float(r.get("avg_pnl", 0)), 2),
                 "win_rate": round(float(r.get("wr", 0)), 3)}
                for r in reversed(best) if float(r["total_pnl"]) < 0
            ][:5]

        # Most active
        active = run_query("""
            SELECT asset, asset_class, COUNT(*) as trades
            FROM training_trades GROUP BY asset, asset_class
            ORDER BY trades DESC LIMIT 10
        """)
        if active:
            rankings["most_active"] = [
                {"asset": r["asset"], "class": r.get("asset_class", ""), "trades": int(r["trades"])}
                for r in active[:10]
            ]
    except Exception:
        pass

    return rankings


def _build_learning_feed() -> dict:
    """Learning feed section."""
    try:
        from bahamut.intelligence.learning_progress import get_learning_progress
        progress = get_learning_progress()
    except Exception:
        progress = {"status": "unknown", "closed_trades": 0, "milestones": []}

    feed = {
        "total_samples": progress.get("closed_trades", 0),
        "status": progress.get("status", "unknown"),
        "progress_pct": progress.get("progress", 0),
        "trust_ready": progress.get("trust_ready", False),
        "adaptive_ready": progress.get("adaptive_ready", False),
        "milestones": progress.get("milestones", []),
        "next_milestone": progress.get("next_milestone", ""),
        "by_strategy": {},
        "by_class": {},
    }

    # Per-strategy sample counts
    try:
        from bahamut.db.query import run_query
        rows = run_query("SELECT strategy, COUNT(*) as cnt FROM training_trades GROUP BY strategy")
        if rows:
            feed["by_strategy"] = {r["strategy"]: int(r["cnt"]) for r in rows}
    except Exception:
        pass

    # Per-class sample counts
    try:
        from bahamut.db.query import run_query
        rows = run_query("SELECT asset_class, COUNT(*) as cnt FROM training_trades GROUP BY asset_class")
        if rows:
            feed["by_class"] = {r["asset_class"]: int(r["cnt"]) for r in rows}
    except Exception:
        pass

    return feed


def _build_exposure(r) -> dict:
    """Training exposure/risk section."""
    from bahamut.training.engine import _load_positions
    from bahamut.config_assets import TRAINING_VIRTUAL_CAPITAL, TRAINING_MAX_POSITIONS

    positions = _load_positions()
    long_exposure = sum(p.entry_price * p.size for p in positions if p.direction == "LONG")
    short_exposure = sum(p.entry_price * p.size for p in positions if p.direction == "SHORT")
    total_risk = sum(p.risk_amount for p in positions)

    # Per-class exposure
    from bahamut.config_assets import ASSET_CLASS_MAP
    class_exposure = {}
    for p in positions:
        cls = ASSET_CLASS_MAP.get(p.asset, "unknown")
        class_exposure[cls] = class_exposure.get(cls, 0) + p.entry_price * p.size

    return {
        "gross_exposure": round(long_exposure + short_exposure, 2),
        "net_exposure": round(long_exposure - short_exposure, 2),
        "long_exposure": round(long_exposure, 2),
        "short_exposure": round(short_exposure, 2),
        "total_risk": round(total_risk, 2),
        "risk_pct": round(total_risk / max(1, TRAINING_VIRTUAL_CAPITAL) * 100, 2),
        "max_positions": TRAINING_MAX_POSITIONS,
        "current_positions": len(positions),
        "utilization_pct": round(len(positions) / max(1, TRAINING_MAX_POSITIONS) * 100, 1),
        "per_class": {k: round(v, 2) for k, v in class_exposure.items()},
    }


def _build_alerts(r) -> list[dict]:
    """Training-specific alerts/anomalies."""
    alerts = []

    # Check: no trades for too long
    try:
        from bahamut.db.query import run_query_one
        row = run_query_one("SELECT MAX(exit_time) as last_close FROM training_trades")
        if row and row.get("last_close"):
            from bahamut.monitoring.data_health import parse_bar_timestamp
            last = parse_bar_timestamp(row["last_close"])
            if last:
                hours_ago = (datetime.now(timezone.utc) - last).total_seconds() / 3600
                if hours_ago > 24:
                    alerts.append({"level": "WARNING", "message": f"No training trades closed in {hours_ago:.0f}h"})
    except Exception:
        pass

    # Check: cycle errors
    if r:
        try:
            raw = r.get("bahamut:training:last_cycle")
            if raw:
                lc = json.loads(raw)
                if lc.get("errors", 0) > 5:
                    alerts.append({"level": "WARNING", "message": f"{lc['errors']} assets failed in last cycle"})
        except Exception:
            pass

    # Check: one class dominating
    try:
        from bahamut.db.query import run_query
        rows = run_query("""
            SELECT asset_class, COUNT(*) as cnt FROM training_trades
            GROUP BY asset_class ORDER BY cnt DESC
        """)
        if rows and len(rows) >= 2:
            total = sum(int(r["cnt"]) for r in rows)
            top_pct = int(rows[0]["cnt"]) / max(1, total)
            if top_pct > 0.7 and total > 10:
                alerts.append({
                    "level": "INFO",
                    "message": f"{rows[0]['asset_class']} dominates training ({top_pct:.0%} of trades)"
                })
    except Exception:
        pass

    # Check: stalled training
    from bahamut.training.engine import get_open_position_count
    if get_open_position_count() == 0:
        alerts.append({"level": "INFO", "message": "No open training positions"})

    return alerts
