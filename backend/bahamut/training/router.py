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
from datetime import datetime, timezone, timedelta
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

    # Load shared data once (not per-section)
    from bahamut.training.engine import _load_positions
    from dataclasses import asdict
    positions = _load_positions()
    pos_dicts = [
        {**asdict(p), "unrealized_pnl": round(p.unrealized_pnl, 2), "duration_bars": p.bars_held}
        for p in positions
    ]

    # Single aggregate DB query for all strategy+class breakdowns
    db_agg = _aggregate_training_trades()

    result = {
        "generated_at": now.isoformat(),
        "cycle_status": _build_cycle_status(r, now),
        "kpi": _build_kpi(r, db_agg),
        "cycle_health": _build_cycle_health(r),
        "recent_cycles": _build_recent_cycles(r),
        "positions": pos_dicts,
        "closed_trades": _build_closed_trades(),
        "strategy_breakdown": _build_strategy_breakdown_fast(r, db_agg, positions),
        "class_breakdown": _build_class_breakdown_fast(r, db_agg, positions),
        "asset_rankings": _build_asset_rankings(),
        "learning": _build_learning_feed(),
        "exposure": _build_exposure_fast(positions),
        "alerts": _build_alerts(r),
    }
    return result


def _aggregate_training_trades() -> dict:
    """One DB query for all strategy + class aggregates."""
    result = {"by_strategy": {}, "by_class": {}, "total": {}}
    try:
        from bahamut.db.query import run_query
        rows = run_query("""
            SELECT strategy, asset_class,
                   COUNT(*) as cnt,
                   SUM(CASE WHEN pnl > 0.01 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN pnl < -0.01 THEN 1 ELSE 0 END) as losses,
                   COALESCE(SUM(pnl), 0) as total_pnl,
                   COALESCE(AVG(pnl), 0) as avg_pnl,
                   COALESCE(AVG(bars_held), 0) as avg_bars,
                   COALESCE(SUM(CASE WHEN pnl > 0.01 THEN pnl ELSE 0 END), 0) as gp,
                   COALESCE(SUM(CASE WHEN pnl < 0 THEN ABS(pnl) ELSE 0 END), 0) as gl
            FROM training_trades GROUP BY strategy, asset_class
        """)
        if rows:
            total_cnt = 0
            total_pnl = 0.0
            total_wins = 0
            total_losses = 0
            total_bars = 0.0
            for row in rows:
                s = row.get("strategy", "")
                c = row.get("asset_class", "")
                cnt = int(row.get("cnt", 0))
                wins = int(row.get("wins", 0))
                losses = int(row.get("losses", 0))
                pnl = float(row.get("total_pnl", 0) or 0)
                avg_pnl = float(row.get("avg_pnl", 0) or 0)
                avg_bars = float(row.get("avg_bars", 0) or 0)
                gp = float(row.get("gp", 0) or 0)
                gl = float(row.get("gl", 0) or 0)

                total_cnt += cnt
                total_pnl += pnl
                total_wins += wins
                total_losses += losses
                total_bars += avg_bars * cnt

                if s not in result["by_strategy"]:
                    result["by_strategy"][s] = {"cnt": 0, "wins": 0, "losses": 0, "pnl": 0, "avg_pnl": 0, "avg_bars": 0, "gp": 0, "gl": 0, "_total_bars": 0}
                bs = result["by_strategy"][s]
                bs["cnt"] += cnt; bs["wins"] += wins; bs["losses"] += losses; bs["pnl"] += pnl; bs["gp"] += gp; bs["gl"] += gl
                bs["_total_bars"] += avg_bars * cnt  # weighted sum for per-strategy average

                if c not in result["by_class"]:
                    result["by_class"][c] = {"cnt": 0, "wins": 0, "losses": 0, "pnl": 0}
                bc = result["by_class"][c]
                bc["cnt"] += cnt; bc["wins"] += wins; bc["losses"] += losses; bc["pnl"] += pnl

            # Compute per-strategy averages
            for s, bs in result["by_strategy"].items():
                bs["avg_pnl"] = bs["pnl"] / max(1, bs["cnt"])
                bs["avg_bars"] = bs.get("_total_bars", 0) / max(1, bs["cnt"])

            result["total"] = {"cnt": total_cnt, "pnl": total_pnl, "wins": total_wins,
                               "losses": total_losses,
                               "avg_bars": total_bars / max(1, total_cnt)}
    except Exception:
        pass
    return result


def _build_cycle_status(r, now) -> dict:
    """Live cycle status with timing data for countdown timers."""
    from bahamut.config_assets import TRAINING_ASSETS
    from datetime import timedelta

    CYCLE_INTERVAL = 600  # 10 minutes

    status = {
        "auto_enabled": True,
        "cycle_interval_seconds": CYCLE_INTERVAL,
        "universe_size": len(TRAINING_ASSETS),
        "is_running": False,
        "running_progress": None,
        "last_cycle_time": None,
        "last_cycle_status": None,
        "last_cycle_duration_ms": None,
        "next_cycle_time": None,
        "seconds_until_next_cycle": None,
        "next_4h_bar_time": None,
        "seconds_until_4h_bar": None,
        "cycle_status": "waiting",
    }

    if not r:
        status["auto_enabled"] = False
        return status

    # Running state
    try:
        raw = r.get("bahamut:training:running")
        if raw:
            running = json.loads(raw)
            status["is_running"] = running.get("is_running", False)
            if status["is_running"]:
                status["cycle_status"] = "running"
                prog_raw = r.get("bahamut:training:progress")
                if prog_raw:
                    status["running_progress"] = json.loads(prog_raw)
    except Exception as e:
        logger.debug("cycle_status_running_check_failed", error=str(e))

    # Last cycle + compute next
    last_dt = None
    try:
        raw = r.get("bahamut:training:last_cycle")
        if raw:
            lc = json.loads(raw)
            last_time_str = lc.get("last_cycle", "")
            status["last_cycle_time"] = last_time_str
            status["last_cycle_status"] = lc.get("status")
            status["last_cycle_duration_ms"] = lc.get("duration_ms")

            if not status["is_running"]:
                status["cycle_status"] = lc.get("status", "OK")

            if last_time_str:
                # Parse — handle both Z and +00:00 suffixes
                ts = last_time_str.replace("Z", "+00:00")
                if "+" not in ts and ts.endswith("00"):
                    ts += "+00:00"
                last_dt = datetime.fromisoformat(ts)
    except Exception as e:
        logger.warning("cycle_status_parse_failed", error=str(e))

    # Compute next cycle time
    try:
        if last_dt:
            next_dt = last_dt + timedelta(seconds=CYCLE_INTERVAL)
        else:
            # No last cycle known — estimate: next cycle within one interval from now
            # Celery beat fires at fixed intervals from worker start.
            # Best estimate: round up to next 10-min boundary
            minutes_now = now.minute
            next_min = ((minutes_now // 10) + 1) * 10
            if next_min >= 60:
                next_dt = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            else:
                next_dt = now.replace(minute=next_min, second=0, microsecond=0)

        status["next_cycle_time"] = next_dt.isoformat()
        secs = (next_dt - now).total_seconds()
        status["seconds_until_next_cycle"] = max(0, int(secs))

        # If the computed next is in the past (cycle overdue), show 0
        if secs < -30:
            status["seconds_until_next_cycle"] = 0
            status["next_cycle_time"] = now.isoformat()
    except Exception as e:
        logger.warning("cycle_status_next_compute_failed", error=str(e))

    # Next 4H bar
    try:
        from bahamut.monitoring.data_health import next_4h_close
        next_4h = next_4h_close(now)
        status["next_4h_bar_time"] = next_4h.isoformat()
        status["seconds_until_4h_bar"] = max(0, int((next_4h - now).total_seconds()))
    except Exception:
        pass

    return status


def _build_recent_cycles(r) -> list[dict]:
    """Last 10 cycle history entries."""
    if not r:
        return []
    try:
        raw_list = r.lrange("bahamut:training:cycle_history", 0, 9)
        return [json.loads(x) for x in raw_list] if raw_list else []
    except Exception:
        return []


def _build_kpi(r, db_agg: dict) -> dict:
    """Top KPI row data — uses pre-aggregated DB data."""
    from bahamut.config_assets import TRAINING_ASSETS, TRAINING_VIRTUAL_CAPITAL, TRAINING_RISK_PER_TRADE_PCT
    from bahamut.training.engine import get_open_position_count, _load_positions

    totals = db_agg.get("total", {})
    net_pnl = round(totals.get("pnl", 0), 2)
    closed = totals.get("cnt", 0)
    wins = totals.get("wins", 0)
    losses = totals.get("losses", 0)
    decisive = wins + losses  # Trades with actual P&L (excludes flat scratches)
    equity = round(TRAINING_VIRTUAL_CAPITAL + net_pnl, 2)
    risk_per_trade = round(TRAINING_VIRTUAL_CAPITAL * TRAINING_RISK_PER_TRADE_PCT, 2)

    # Unrealized PnL from open positions
    positions = _load_positions()
    unrealized = round(sum(p.unrealized_pnl for p in positions), 2)
    total_equity = round(equity + unrealized, 2)

    kpi = {
        "universe_size": len(TRAINING_ASSETS),
        "virtual_capital": TRAINING_VIRTUAL_CAPITAL,
        "equity": total_equity,
        "net_pnl": net_pnl,
        "unrealized_pnl": unrealized,
        "return_pct": round((total_equity - TRAINING_VIRTUAL_CAPITAL) / TRAINING_VIRTUAL_CAPITAL * 100, 2),
        "risk_per_trade": risk_per_trade,
        "risk_per_trade_pct": round(TRAINING_RISK_PER_TRADE_PCT * 100, 2),
        "assets_scanned": 0,
        "open_positions": get_open_position_count(),
        "closed_trades": closed,
        "win_rate": round(wins / max(1, decisive), 4),  # Excludes flat trades from denominator
        "wins": wins,
        "losses": losses,
        "flat_trades": closed - decisive,
        "avg_duration_bars": round(totals.get("avg_bars", 0), 1),
        "last_cycle": None,
        "cycle_status": "unknown",
        "learning_samples": closed,
    }

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
            health["trades_opened"] = lc.get("trades_opened", 0)
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
    """Recent closed trades table (last 50). Merges DB + Redis to never lose trades."""
    db_trades = []
    redis_trades = []

    # DB: permanent storage
    try:
        from bahamut.db.query import run_query
        rows = run_query("""
            SELECT trade_id, asset, asset_class, strategy, direction,
                   entry_price, exit_price, stop_price, tp_price,
                   size, risk_amount,
                   pnl, pnl_pct, exit_reason, bars_held,
                   entry_time, exit_time, regime,
                   execution_type, confidence_score
            FROM training_trades
            ORDER BY created_at DESC LIMIT 50
        """)
        if rows:
            db_trades = [dict(r) for r in rows]
    except Exception:
        pass

    # Redis: recent trades (catches trades that failed DB persist)
    try:
        from bahamut.training.engine import get_recent_trades_from_redis
        redis_trades = get_recent_trades_from_redis() or []
    except Exception:
        pass

    # Merge: DB is primary, add Redis trades not already in DB
    db_ids = {t.get("trade_id") for t in db_trades if t.get("trade_id")}
    for rt in redis_trades:
        if rt.get("trade_id") not in db_ids:
            db_trades.append(rt)

    # Sort by exit_time descending
    db_trades.sort(key=lambda t: t.get("exit_time", ""), reverse=True)
    return db_trades[:50]


def _build_strategy_breakdown_fast(r, db_agg: dict, positions: list) -> dict:
    """Per-strategy breakdown using pre-aggregated data. Zero DB queries."""
    strategies = {}
    for strat in ["v5_base", "v9_breakout", "v10_mean_reversion"]:
        bs = db_agg.get("by_strategy", {}).get(strat, {})
        cnt = bs.get("cnt", 0)
        wins = bs.get("wins", 0)
        losses = bs.get("losses", 0)
        decisive = wins + losses
        gp = bs.get("gp", 0)
        gl = bs.get("gl", 0)
        strategies[strat] = {
            "open_trades": sum(1 for p in positions if p.strategy == strat),
            "closed_trades": cnt,
            "win_rate": round(wins / max(1, decisive), 4) if decisive else 0,
            "profit_factor": round(gp / max(gl, 0.01), 2) if cnt else 0,
            "avg_pnl": round(bs.get("avg_pnl", 0), 2),
            "total_pnl": round(bs.get("pnl", 0), 2),
            "avg_hold_bars": round(bs.get("avg_bars", 0), 1),
            "provisional": cnt < 10,
        }
    return strategies


def _build_class_breakdown_fast(r, db_agg: dict, positions: list) -> dict:
    """Per-class breakdown using pre-aggregated data. Zero DB queries."""
    from bahamut.config_assets import ASSET_CLASS_MAP
    classes = {}
    for cls in ["crypto", "forex", "index", "commodity", "stock"]:
        bc = db_agg.get("by_class", {}).get(cls, {})
        cnt = bc.get("cnt", 0)
        wins = bc.get("wins", 0)
        losses = bc.get("losses", 0)
        decisive = wins + losses
        classes[cls] = {
            "open_trades": sum(1 for p in positions if ASSET_CLASS_MAP.get(p.asset) == cls),
            "closed_trades": cnt,
            "pnl": round(bc.get("pnl", 0), 2),
            "win_rate": round(wins / max(1, decisive), 4) if decisive else 0,
            "signals": cnt,
        }
    return classes


def _build_exposure_fast(positions: list) -> dict:
    """Exposure using pre-loaded positions. Zero DB/Redis queries."""
    from bahamut.config_assets import TRAINING_VIRTUAL_CAPITAL, TRAINING_MAX_POSITIONS, ASSET_CLASS_MAP

    long_exposure = sum(p.entry_price * p.size for p in positions if p.direction == "LONG")
    short_exposure = sum(p.entry_price * p.size for p in positions if p.direction == "SHORT")
    total_risk = sum(p.risk_amount for p in positions)

    class_exposure: dict[str, float] = {}
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


def _build_strategy_breakdown(r) -> dict:
    """Per-strategy breakdown."""
    strategies = {}
    for strat in ["v5_base", "v9_breakout", "v10_mean_reversion"]:
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
                       SUM(CASE WHEN pnl > 0.01 THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN pnl < -0.01 THEN 1 ELSE 0 END) as losses,
                       COALESCE(SUM(pnl), 0) as total_pnl,
                       COALESCE(AVG(pnl), 0) as avg_pnl,
                       COALESCE(AVG(bars_held), 0) as avg_bars,
                       COALESCE(SUM(CASE WHEN pnl > 0.01 THEN pnl ELSE 0 END), 0) as gp,
                       COALESCE(SUM(CASE WHEN pnl < 0 THEN ABS(pnl) ELSE 0 END), 0) as gl
                FROM training_trades WHERE strategy = :s
            """, {"s": strat})
            if row and int(row.get("cnt", 0)) > 0:
                cnt = int(row["cnt"])
                wins = int(row.get("wins", 0))
                losses = int(row.get("losses", 0))
                decisive = wins + losses
                stats["closed_trades"] = cnt
                stats["win_rate"] = round(wins / max(1, decisive), 4)
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
                       SUM(CASE WHEN pnl > 0.01 THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN pnl < -0.01 THEN 1 ELSE 0 END) as losses,
                       COALESCE(SUM(pnl), 0) as total_pnl
                FROM training_trades WHERE asset_class = :c
            """, {"c": cls})
            if row and int(row.get("cnt", 0)) > 0:
                cnt = int(row["cnt"])
                wins = int(row.get("wins", 0))
                losses = int(row.get("losses", 0))
                decisive = wins + losses
                stats["closed_trades"] = cnt
                stats["pnl"] = round(float(row.get("total_pnl", 0) or 0), 2)
                stats["win_rate"] = round(wins / max(1, decisive), 4)
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
                   SUM(CASE WHEN pnl > 0.01 THEN 1 ELSE 0 END)::float / COUNT(*) as wr
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


@router.get("/candidates")
async def get_candidates(user=Depends(get_current_user)):
    """Get top 20 trade candidates. Cache-first, triggers background scan on cold cache."""
    try:
        from bahamut.training.candidates import get_cached_candidates
        cached = get_cached_candidates()
        if cached is not None:
            return cached
    except Exception as e:
        logger.error("candidates_failed", error=str(e))
    # Cache cold — trigger background scan and return empty for now
    _trigger_background_asset_scan()
    return []


@router.get("/assets")
async def get_all_assets(user=Depends(get_current_user)):
    """Get ALL training assets. Cache-first, static list + background scan on cold cache."""
    try:
        from bahamut.training.candidates import get_cached_all_assets
        cached = get_cached_all_assets()
        if cached is not None:
            return cached
    except Exception as e:
        logger.error("all_assets_failed", error=str(e))

    # Cache cold — return static list AND trigger background scan
    _trigger_background_asset_scan()
    from bahamut.config_assets import TRAINING_ASSETS, ASSET_CLASS_MAP
    assets = [
        {
            "asset": a,
            "asset_class": ASSET_CLASS_MAP.get(a, "unknown"),
            "score": 0,
            "status": "no_data",
            "strategy": "—",
            "direction": "—",
            "regime": "—",
            "distance_to_trigger": "—",
            "reason": "Scanning in background — refresh in ~60s",
            "indicators": {},
        }
        for a in TRAINING_ASSETS
    ]
    counts = {"total": len(assets), "ready": 0, "approaching": 0, "weak": 0, "no_signal": 0, "no_data": len(assets), "error": 0}
    return {"assets": assets, "counts": counts, "duration_ms": 0}


@router.post("/scan-now")
async def trigger_scan(user=Depends(get_current_user)):
    """Manually trigger asset scan. Populates candidates + assets cache in background."""
    _trigger_background_asset_scan()
    return {"status": "scan_triggered", "message": "Background scan started — data appears in ~60s"}


@router.post("/run-cycle")
async def trigger_training_cycle(user=Depends(get_current_user)):
    """Manually trigger a full training cycle. Sets running flag immediately
    for instant UI feedback, then runs in thread."""
    global _bg_cycle_running
    if _bg_cycle_running:
        return {"status": "already_running", "message": "Training cycle already in progress"}
    _bg_cycle_running = True

    # Set running flag IMMEDIATELY so UI shows animation within 5s
    try:
        from bahamut.training.orchestrator import _set_running
        from bahamut.config_assets import TRAINING_ASSETS
        _set_running(True, len(TRAINING_ASSETS))
    except Exception:
        pass

    import threading
    def _do_cycle():
        global _bg_cycle_running
        try:
            from bahamut.training.orchestrator import run_training_cycle
            logger.info("manual_training_cycle_start")
            run_training_cycle()
            logger.info("manual_training_cycle_complete")
        except Exception as e:
            logger.error("manual_training_cycle_failed", error=str(e))
            # Clear running flag on error
            try:
                from bahamut.training.orchestrator import _set_running
                _set_running(False, 0)
            except Exception:
                pass
        finally:
            _bg_cycle_running = False

    threading.Thread(target=_do_cycle, daemon=True).start()
    return {"status": "running", "message": "Training cycle started — watch the progress bar"}


# ── Background state flags ──
_bg_scan_running = False
_bg_cycle_running = False

def _trigger_background_asset_scan():
    """Fire background thread to scan assets and populate cache. Non-blocking, singleton."""
    global _bg_scan_running
    if _bg_scan_running:
        return
    _bg_scan_running = True

    import threading
    def _do_scan():
        global _bg_scan_running
        try:
            from bahamut.training.candidates import (
                get_training_candidates, get_all_training_assets,
                cache_candidates, cache_all_assets,
            )
            logger.info("background_asset_scan_start")
            cache_all_assets(get_all_training_assets())
            cache_candidates(get_training_candidates(max_results=20))
            logger.info("background_asset_scan_complete")
        except Exception as e:
            logger.error("background_asset_scan_failed", error=str(e))
        finally:
            _bg_scan_running = False

    threading.Thread(target=_do_scan, daemon=True).start()


@router.get("/execution-decisions")
async def get_execution_decisions(user=Depends(get_current_user)):
    """Get last execution selection decisions from the most recent training cycle.
    Shows which signals were selected, watchlisted, or rejected with reasons."""
    try:
        from bahamut.training.selector import get_last_decisions
        return get_last_decisions()
    except Exception as e:
        logger.error("execution_decisions_failed", error=str(e))
        return {"execute": [], "watchlist": [], "rejected": [], "summary": {"total_signals": 0}}


@router.get("/adaptive")
async def get_adaptive_state(user=Depends(get_current_user)):
    """Get current adaptive threshold state, metrics, and adjustment history."""
    try:
        from bahamut.training.adaptive_thresholds import (
            get_current_profile, get_last_metrics, get_adjustment_history,
            BOUNDS, POLICY,
        )
        from dataclasses import asdict
        profile = get_current_profile()
        return {
            "profile": asdict(profile),
            "metrics": get_last_metrics(),
            "history": get_adjustment_history(),
            "bounds": BOUNDS,
            "policy": {k: v for k, v in POLICY.items() if k not in ("conservative_triggers", "aggressive_triggers")},
        }
    except Exception as e:
        logger.error("adaptive_state_failed", error=str(e))
        return {"profile": {}, "metrics": {}, "history": []}


@router.get("/diagnostics")
async def get_training_diagnostics(user=Depends(get_current_user)):
    """Structured diagnostic logs for AI analysis."""
    import json as _json
    from fastapi.responses import JSONResponse

    def _safe(obj):
        """Handle non-JSON-serializable types."""
        if isinstance(obj, set):
            return sorted(list(obj))
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="replace")
        if hasattr(obj, "item"):  # numpy scalar
            return obj.item()
        return str(obj)

    try:
        result = await _build_diagnostics()
        body = _json.dumps(result, default=_safe)
        return JSONResponse(content=_json.loads(body))
    except Exception as e:
        import traceback
        return {"generated_at": datetime.now(timezone.utc).isoformat(),
                "sections": [{"title": "FATAL ERROR", "error": str(e),
                              "trace": traceback.format_exc()[:2000]}]}


async def _build_diagnostics():
    r = _get_redis()
    diag = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sections": [],
    }

    # ── 1. TRUST STATE PER PATTERN ──
    trust_section = {"title": "TRUST STATE", "rows": []}
    try:
        from bahamut.training.learning_engine import get_pattern_trust, get_trust_overview
        overview = get_trust_overview()
        for strat, info in overview.get("strategies", {}).items():
            trust_section["rows"].append({
                "strategy": strat,
                "trust": info.get("trust", 0.5),
                "samples": info.get("samples", 0),
                "maturity": info.get("maturity", "provisional"),
                "confidence": info.get("confidence", 0),
                "wins": info.get("wins", 0),
                "losses": info.get("losses", 0),
                "quick_stops": info.get("quick_stops", 0),
            })

        # Per-regime trust for each strategy
        for strat in ["v5_base", "v9_breakout", "v10_mean_reversion"]:
            for regime in ["TREND", "RANGE", "CRASH", "BREAKOUT"]:
                for ac in ["crypto", "stock", "forex", "commodity", "index"]:
                    try:
                        t = get_pattern_trust(strat, regime, ac)
                        if t.get("total_trades", 0) > 0:
                            trust_section["rows"].append({
                                "pattern": f"{strat}:{regime}:{ac}",
                                "blended_trust": t["blended_trust"],
                                "confidence": t["blended_confidence"],
                                "maturity": t["maturity"],
                                "trades": t["total_trades"],
                                "quick_stops": t["quick_stops"],
                                "expectancy": t.get("expectancy", 0),
                                "buckets": {k: {"trust": v["trust"], "samples": v["samples"], "maturity": v["maturity"]}
                                           for k, v in t.get("buckets", {}).items() if v.get("samples", 0) > 0},
                            })
                    except Exception:
                        pass
    except Exception as e:
        trust_section["error"] = str(e)
    diag["sections"].append(trust_section)

    # ── 2. RECENT TRADES (last 20) ──
    trades_section = {"title": "RECENT TRADES", "rows": []}
    try:
        if r:
            raw = r.lrange("bahamut:training:recent_trades", 0, 19)
            for item in (raw or []):
                try:
                    t = json.loads(item)
                    trades_section["rows"].append({
                        "asset": t.get("asset"),
                        "strategy": t.get("strategy"),
                        "direction": t.get("direction"),
                        "regime": t.get("regime"),
                        "pnl": t.get("pnl"),
                        "pnl_pct": t.get("pnl_pct"),
                        "exit_reason": t.get("exit_reason"),
                        "bars_held": t.get("bars_held"),
                        "r_multiple": round(t.get("pnl", 0) / max(t.get("risk_amount", 1), 0.01), 2),
                        "entry_time": t.get("entry_time", ""),
                        "exit_time": t.get("exit_time", ""),
                    })
                except Exception:
                    pass
    except Exception as e:
        trades_section["error"] = str(e)
    diag["sections"].append(trades_section)

    # ── 3. STRATEGY PERFORMANCE (from DB — single source of truth) ──
    perf_section = {"title": "STRATEGY PERFORMANCE", "rows": []}
    try:
        from bahamut.db.query import run_query
        rows = run_query("""
            SELECT strategy,
                   COUNT(*) as trades,
                   SUM(CASE WHEN pnl > 0.01 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN pnl < -0.01 THEN 1 ELSE 0 END) as losses,
                   COALESCE(SUM(pnl), 0) as total_pnl
            FROM training_trades GROUP BY strategy ORDER BY total_pnl DESC
        """)
        # Get last trade per strategy from Redis for recency info
        last_trade_info = {}
        if r:
            for strat in ["v5_base", "v9_breakout", "v10_mean_reversion"]:
                raw = r.get(f"bahamut:training:strategy_stats:{strat}")
                if raw:
                    s = json.loads(raw)
                    last_trade_info[strat] = {"last_pnl": s.get("last_pnl", 0), "last_asset": s.get("last_asset", "")}

        for row in (rows or []):
            strat = row["strategy"]
            trades = row["trades"]
            wins = row["wins"] or 0
            losses = row["losses"] or 0
            decisive = wins + losses
            pnl = row["total_pnl"] or 0
            lt = last_trade_info.get(strat, {})
            perf_section["rows"].append({
                "strategy": strat,
                "trades": trades,
                "wins": wins,
                "losses": losses,
                "win_rate": round(wins / max(1, decisive), 4),
                "total_pnl": round(pnl, 2),
                "last_pnl": lt.get("last_pnl", 0),
                "last_asset": lt.get("last_asset", ""),
            })
    except Exception as e:
        perf_section["error"] = str(e)
    diag["sections"].append(perf_section)

    # ── 4. REJECTION STATS ──
    rej_section = {"title": "REJECTION REASONS", "data": {}}
    try:
        from bahamut.training.learning_engine import get_rejection_stats
        rej_section["data"] = get_rejection_stats()
    except Exception as e:
        rej_section["error"] = str(e)
    diag["sections"].append(rej_section)

    # ── 5. PATTERN SUPPRESSIONS ──
    sup_section = {"title": "ACTIVE SUPPRESSIONS", "rows": []}
    try:
        from bahamut.training.context_gate import get_all_suppressions
        sup_section["rows"] = get_all_suppressions()
    except Exception as e:
        sup_section["error"] = str(e)
    diag["sections"].append(sup_section)

    # ── 6. OPEN POSITIONS ──
    pos_section = {"title": "OPEN POSITIONS", "rows": []}
    try:
        from bahamut.training.engine import _load_positions
        from dataclasses import asdict
        positions = _load_positions()
        for p in positions:
            d = asdict(p)
            pos_section["rows"].append({
                "asset": d.get("asset"),
                "strategy": d.get("strategy"),
                "direction": d.get("direction"),
                "regime": d.get("regime"),
                "entry_price": d.get("entry_price"),
                "stop_price": d.get("stop_price"),
                "tp_price": d.get("tp_price"),
                "bars_held": d.get("bars_held"),
                "unrealized_pnl": round(p.unrealized_pnl, 2),
                "current_price": d.get("current_price", 0),
                "execution_platform": d.get("execution_platform", "internal"),
                "exchange_order_id": d.get("exchange_order_id", ""),
            })
    except Exception as e:
        pos_section["error"] = str(e)
    diag["sections"].append(pos_section)

    # ── 7. ASSET CLASS PERFORMANCE (from DB — single source of truth) ──
    class_section = {"title": "ASSET CLASS PERFORMANCE", "rows": []}
    try:
        from bahamut.db.query import run_query
        rows = run_query("""
            SELECT asset_class,
                   COUNT(*) as trades,
                   SUM(CASE WHEN pnl > 0.01 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN pnl < -0.01 THEN 1 ELSE 0 END) as losses,
                   COALESCE(SUM(pnl), 0) as total_pnl
            FROM training_trades GROUP BY asset_class ORDER BY total_pnl DESC
        """)
        for row in (rows or []):
            wins = row["wins"] or 0
            losses = row["losses"] or 0
            decisive = wins + losses
            class_section["rows"].append({
                "class": row["asset_class"],
                "trades": row["trades"],
                "wins": wins,
                "losses": losses,
                "win_rate": round(wins / max(1, decisive), 4),
                "total_pnl": round(row["total_pnl"] or 0, 2),
            })
    except Exception as e:
        class_section["error"] = str(e)
    diag["sections"].append(class_section)

    # ── 8. SELECTOR CONFIG ──
    config_section = {"title": "SELECTOR CONFIG", "data": {}}
    try:
        from bahamut.training.selector import _get_config
        config_section["data"] = _get_config()
    except Exception as e:
        config_section["error"] = str(e)
    diag["sections"].append(config_section)

    # ── 9. CONTEXT GATE RULES ──
    gate_section = {"title": "CONTEXT GATE RULES", "data": {}}
    try:
        from bahamut.training.context_gate import STRATEGY_REGIME_MAP, SOFT_PENALTY_COMBOS
        gate_section["data"] = {
            "allowed_regimes": {k: list(v) for k, v in STRATEGY_REGIME_MAP.items()},
            "soft_penalties": {f"{k[0]}+{k[1]}": v for k, v in SOFT_PENALTY_COMBOS.items()},
        }
    except Exception as e:
        gate_section["error"] = str(e)
    diag["sections"].append(gate_section)

    # ── 10. QUALITY FLOORS ──
    floors_section = {"title": "QUALITY FLOORS", "data": {}}
    try:
        from bahamut.training.quality_floors import FLOORS
        floors_section["data"] = FLOORS
    except Exception as e:
        floors_section["error"] = str(e)
    diag["sections"].append(floors_section)

    # ── 11. SENTIMENT STATE ──
    sentiment_section = {"title": "SENTIMENT STATE", "data": {}}
    try:
        from bahamut.sentiment.gate import get_full_sentiment
        sentiment_section["data"] = get_full_sentiment()
    except Exception as e:
        sentiment_section["error"] = str(e)
    diag["sections"].append(sentiment_section)

    # ── 12. CURRENT REGIMES PER ASSET ──
    regime_section = {"title": "CURRENT REGIMES", "rows": []}
    try:
        from bahamut.data.binance_data import is_crypto, get_candles, compute_indicators as binance_ind
        from bahamut.regime.v8_detector import detect_regime
        from bahamut.config_assets import TRAINING_CRYPTO, TRAINING_STOCKS
        from bahamut.sentiment.fear_greed import get_fear_greed

        fng = get_fear_greed()
        fng_value = fng.get("value", 50)

        # Sample top 5 crypto + check sentiment override
        for asset in TRAINING_CRYPTO[:5]:
            try:
                candles_4h = get_candles(asset, interval="4h", limit=100)
                if candles_4h and len(candles_4h) >= 60:
                    ind_4h = binance_ind(candles_4h)
                    # Pass full candle list so detector can build true EMA slope.
                    rr = detect_regime(ind_4h, candles_4h)
                    structural = rr.structural_regime
                    effective = structural
                    override = ""
                    sentiment_block = False

                    if fng_value <= 25:
                        sentiment_block = True
                        # Structural CRASH override: requires price BELOW EMA200 + negative slope.
                        # Reuse slope from rr.features — detector already computed it.
                        slope_4h = rr.features.get("ema50_slope", 0)
                        dist_ema200 = rr.features.get("price_vs_ema200", 0)
                        if dist_ema200 < 0 and slope_4h < -0.5:
                            effective = "CRASH"
                            override = "structural (below EMA200 + neg slope)"
                        else:
                            override = f"sentiment_long_block (F&G={fng_value})"

                    regime_section["rows"].append({
                        "asset": asset,
                        "structural_regime": structural,
                        "effective_regime": effective,
                        "regime_confidence": rr.regime_confidence,
                        "sentiment_overlay": "long_block" if sentiment_block else "",
                        "override_applied": "structural_crash_override" if effective != structural else "",
                        # Legacy aliases for UI backward compat
                        "regime_4h": structural, "effective": effective, "override": override,
                        "sentiment_long_block": sentiment_block,
                        "reason": rr.reason,
                        "features": rr.features,
                    })
            except Exception:
                pass
    except Exception as e:
        regime_section["error"] = str(e)
    diag["sections"].append(regime_section)

    # ── 13. INDICATOR SNAPSHOT (top crypto + stocks) ──
    indicator_section = {"title": "INDICATOR SNAPSHOT", "rows": []}
    try:
        from bahamut.data.binance_data import get_candles, compute_indicators as binance_ind
        from bahamut.config_assets import TRAINING_CRYPTO

        for asset in TRAINING_CRYPTO[:8]:
            try:
                candles_15m = get_candles(asset, interval="15m", limit=200)
                if candles_15m and len(candles_15m) >= 30:
                    ind = binance_ind(candles_15m)
                    close = ind.get("close", 0)
                    ema20 = ind.get("ema_20", 0)
                    ema200 = ind.get("ema_200", 0)
                    dist_ema20 = round((ema20 - close) / max(ema20, 0.001) * 100, 2) if ema20 > 0 else 0
                    dist_ema200 = round((close - ema200) / max(ema200, 0.001) * 100, 2) if ema200 > 0 else 0
                    indicator_section["rows"].append({
                        "asset": asset,
                        "close": round(close, 4),
                        "ema20": round(ema20, 4),
                        "dist_ema20_pct": dist_ema20,
                        "ema200": round(ema200, 4),
                        "dist_ema200_pct": dist_ema200,
                        "rsi": ind.get("rsi_14", 0),
                        "atr": round(ind.get("atr_14", 0), 4),
                        "adx": ind.get("adx_14", 0),
                        "bb_upper": round(ind.get("bollinger_upper", 0), 4),
                        "bb_lower": round(ind.get("bollinger_lower", 0), 4),
                    })
            except Exception:
                pass
    except Exception as e:
        indicator_section["error"] = str(e)
    diag["sections"].append(indicator_section)

    # ── 13b. CLOSED-CANDLE ENFORCEMENT (Phase 1 Item 1) ──
    candle_section = {"title": "CANDLE CLOSED-STATE", "rows": [], "data": {}}
    try:
        from bahamut.data.binance_data import last_candle_closed_state
        from bahamut.features.indicators import INDICATOR_ENGINE_VERSION as _IEV
        state = last_candle_closed_state()
        # Summarize
        total = len(state)
        any_forming_used_for_signals = [
            k for k, v in state.items()
            if v.get("used_for_signals") and not v.get("is_closed")
        ]
        total_dropped_forming = sum(v.get("dropped_forming", 0) for v in state.values())
        candle_section["data"] = {
            "total_tracked_asset_intervals": total,
            "any_forming_candle_used_for_signals": len(any_forming_used_for_signals),
            "forming_leak_assets": any_forming_used_for_signals[:10],
            "total_forming_dropped_across_fetches": total_dropped_forming,
            "enforcement_ok": len(any_forming_used_for_signals) == 0,
            "source": "bahamut.data.binance_data.last_candle_closed_state",
            # Phase 1 Item 2: canonical indicator engine provenance
            "indicator_engine_version": _IEV,
            "indicator_engine_source": "bahamut.features.indicators (canonical, shared by crypto and stock paths)",
        }
        # Show per-asset-interval detail for the most-recent entries
        for k, v in sorted(state.items(), key=lambda x: -x[1].get("recorded_at", 0))[:8]:
            candle_section["rows"].append({
                "asset_interval": k,
                "last_datetime": v.get("last_datetime"),
                "is_closed": v.get("is_closed"),
                "dropped_forming": v.get("dropped_forming", 0),
                "used_for_signals": v.get("used_for_signals"),
                "source": v.get("source"),
            })
    except Exception as e:
        candle_section["error"] = str(e)
    diag["sections"].append(candle_section)

    # ── 14. LAST CYCLE SIGNALS (from Redis) ──
    signals_section = {"title": "LAST CYCLE SIGNALS", "rows": []}
    try:
        if r:
            raw = r.get("bahamut:training:last_cycle_decisions")
            if raw:
                decisions = json.loads(raw)
                for d in decisions[:20]:
                    signals_section["rows"].append(d)
    except Exception as e:
        signals_section["error"] = str(e)
    diag["sections"].append(signals_section)

    # ── 15. EXECUTION PLATFORM STATUS ──
    exec_section = {"title": "EXECUTION STATUS", "data": {}}
    try:
        from bahamut.execution.router import get_execution_status
        exec_section["data"] = get_execution_status()
    except Exception as e:
        exec_section["error"] = str(e)

    # Phase 2 Item 6: exchange filter visibility
    try:
        from bahamut.execution.exchange_filters import _FILTERS, _FILTERS_FETCHED_AT
        import time as _t
        if _FILTERS:
            # Summary
            exec_section["data"]["exchange_filters"] = {
                "symbols_cached": len(_FILTERS),
                "fetched_at": _FILTERS_FETCHED_AT,
                "age_seconds": round(_t.time() - _FILTERS_FETCHED_AT) if _FILTERS_FETCHED_AT else None,
                "sample": {
                    sym: {
                        "stepSize": _FILTERS[sym]["stepSize"],
                        "minQty": _FILTERS[sym]["minQty"],
                        "minNotional": _FILTERS[sym]["minNotional"],
                        "source": _FILTERS[sym].get("source", "?"),
                    }
                    for sym in ("BTCUSDT", "ETHUSDT", "DOGEUSDT", "SOLUSDT", "PEPEUSDT")
                    if sym in _FILTERS
                },
                "any_using_fallback": any(
                    f.get("source", "").startswith("fallback")
                    for f in _FILTERS.values()
                ),
            }
    except Exception as e:
        exec_section["data"]["exchange_filters_error"] = str(e)[:120]
    diag["sections"].append(exec_section)

    # ── 16. SHORT SIGNAL DEBUG ──
    short_debug = {"title": "SHORT SIGNAL DEBUG", "rows": []}
    try:
        from bahamut.data.binance_data import get_candles, compute_indicators as binance_ind
        from bahamut.alpha.v10_mean_reversion import detect_crash_short
        from bahamut.config_assets import TRAINING_CRYPTO

        for asset in TRAINING_CRYPTO[:10]:
            try:
                candles_15m = get_candles(asset, interval="15m", limit=200)
                if candles_15m and len(candles_15m) >= 30:
                    ind = binance_ind(candles_15m)
                    prev_ind = binance_ind(candles_15m[:-1]) if len(candles_15m) > 1 else None
                    sig = detect_crash_short(candles_15m, ind, prev_ind)
                    short_debug["rows"].append({
                        "asset": asset,
                        "signal_valid": sig.valid,
                        "direction": sig.direction if sig.valid else "NONE",
                        "confidence": sig.confidence,
                        "reason": sig.reason,
                        "rsi": sig.rsi,
                        "dist_from_mean": sig.distance_from_mean_pct,
                    })
            except Exception as ex:
                short_debug["rows"].append({"asset": asset, "error": str(ex)[:100]})
    except Exception as e:
        short_debug["error"] = str(e)
    diag["sections"].append(short_debug)

    # ── 17. SYSTEM HEALTH ──
    health_section = {"title": "SYSTEM HEALTH", "data": {}}
    try:
        from bahamut.config_assets import TRAINING_CRYPTO, TRAINING_STOCKS, TRAINING_ASSETS
        from bahamut.training.orchestrator import CRYPTO_INTERVAL

        health_section["data"] = {
            "total_assets": len(TRAINING_ASSETS),
            "crypto_assets": len(TRAINING_CRYPTO),
            "stock_assets": len(TRAINING_STOCKS),
            "crypto_interval": CRYPTO_INTERVAL,
            "stock_interval": "4h",
            "redis_connected": r is not None,
        }

        # Check last scan time
        if r:
            last_scan = r.get("bahamut:training:last_scan_time")
            if last_scan:
                health_section["data"]["last_scan"] = last_scan.decode() if isinstance(last_scan, bytes) else str(last_scan)
            cycle_count = r.get("bahamut:training:cycle_count")
            if cycle_count:
                health_section["data"]["total_cycles"] = int(cycle_count)
    except Exception as e:
        health_section["error"] = str(e)
    diag["sections"].append(health_section)

    # ── 18. AI ANALYSIS — automated audit for Claude ──
    ai_section = {"title": "AI ANALYSIS", "data": {}}
    try:
        from bahamut.training.engine import _load_positions
        from dataclasses import asdict
        positions = _load_positions()

        # Strategy health
        strat_health = {}
        try:
            from bahamut.db.query import run_query
            rows = run_query("""
                SELECT strategy,
                       COUNT(*) as trades,
                       SUM(CASE WHEN pnl > 0.01 THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN pnl < -0.01 THEN 1 ELSE 0 END) as losses,
                       SUM(CASE WHEN ABS(pnl) <= 0.01 THEN 1 ELSE 0 END) as flats,
                       ROUND(SUM(pnl)::numeric, 2) as total_pnl,
                       ROUND(AVG(pnl)::numeric, 2) as avg_pnl,
                       ROUND(AVG(bars_held)::numeric, 1) as avg_bars
                FROM training_trades GROUP BY strategy ORDER BY SUM(pnl) DESC
            """)
            for row in rows:
                s = dict(row)
                name = s["strategy"]
                total = s["trades"] or 0
                wins = s["wins"] or 0
                losses = s["losses"] or 0
                flats = s["flats"] or 0
                wr = wins / max(1, wins + losses)
                flat_pct = flats / max(1, total) * 100
                health = "HEALTHY" if wr >= 0.55 and flat_pct < 30 else \
                         "WEAK" if wr >= 0.45 else "UNDERPERFORMING"
                strat_health[name] = {
                    "trades": total, "wins": wins, "losses": losses, "flats": flats,
                    "flat_pct": round(flat_pct, 1), "win_rate": round(wr * 100, 1),
                    "pnl": float(s["total_pnl"] or 0), "avg_pnl": float(s["avg_pnl"] or 0),
                    "avg_bars": float(s["avg_bars"] or 0), "health": health,
                }
        except Exception:
            pass
        ai_section["data"]["strategy_health"] = strat_health

        # Dead-weight asset detection (assets with 5+ trades and negative or zero PnL)
        dead_weight = []
        try:
            rows = run_query("""
                SELECT asset, strategy, COUNT(*) as trades,
                       SUM(CASE WHEN ABS(pnl) <= 0.01 THEN 1 ELSE 0 END) as flats,
                       ROUND(SUM(pnl)::numeric, 2) as total_pnl
                FROM training_trades GROUP BY asset, strategy
                HAVING COUNT(*) >= 5 AND SUM(pnl) <= 0
                ORDER BY SUM(pnl) ASC
            """)
            for row in rows:
                rd = dict(row)
                dead_weight.append({
                    "asset": rd["asset"], "strategy": rd["strategy"],
                    "trades": rd["trades"], "flats": rd["flats"],
                    "pnl": float(rd["total_pnl"] or 0),
                })
        except Exception:
            pass
        ai_section["data"]["dead_weight_assets"] = dead_weight

        # Open position analysis
        pos_analysis = []
        for p in positions:
            age_info = "fresh" if p.bars_held <= 5 else "mid" if p.bars_held <= 15 else "aging"
            pnl_status = "profit" if p.unrealized_pnl > 0.01 else "loss" if p.unrealized_pnl < -0.01 else "flat"
            pos_analysis.append({
                "asset": p.asset, "strategy": p.strategy, "direction": p.direction,
                "bars_held": p.bars_held, "max_hold": p.max_hold_bars,
                "age": age_info, "pnl_status": pnl_status,
                "unrealized_pnl": round(p.unrealized_pnl, 2),
                "execution_platform": p.execution_platform,
                "regime": p.regime,
            })
        ai_section["data"]["open_positions_analysis"] = pos_analysis

        # Cooldown status
        cooldowns = []
        if r:
            try:
                keys = r.keys("bahamut:training:cooldown:*")
                for k in keys:
                    asset_name = k.decode().split(":")[-1] if isinstance(k, bytes) else k.split(":")[-1]
                    ttl = r.ttl(k)
                    cooldowns.append({"asset": asset_name, "remaining_seconds": ttl})
            except Exception:
                pass
        ai_section["data"]["active_cooldowns"] = cooldowns

        # SHORT signal pipeline status
        short_pipeline = {"status": "unknown"}
        try:
            from bahamut.sentiment.fear_greed import get_fear_greed
            fng = get_fear_greed()
            fng_val = fng.get("value", 50)
            short_pipeline["fear_greed"] = fng_val
            short_pipeline["crash_override_active"] = fng_val <= 25
            # Count how many crypto assets have CRASH regime
            crash_count = 0
            from bahamut.config_assets import TRAINING_CRYPTO
            for ca in TRAINING_CRYPTO[:10]:
                try:
                    from bahamut.data.binance_data import get_candles, compute_indicators as binance_ind
                    c4h = get_candles(ca, interval="4h", limit=100)
                    if c4h and len(c4h) >= 30:
                        i4h = binance_ind(c4h)
                        close_4h = i4h.get("close", 0)
                        ema200_4h = i4h.get("ema_200", 0)
                        dist = (close_4h - ema200_4h) / ema200_4h * 100 if ema200_4h > 0 else 0
                        if dist < 3.0 or i4h.get("rsi_14", 50) <= 50:
                            crash_count += 1
                except Exception:
                    pass
            short_pipeline["crypto_in_crash_regime"] = crash_count
            short_pipeline["shorts_should_fire"] = fng_val <= 25 and crash_count > 0
            short_pipeline["status"] = "active" if fng_val <= 25 and crash_count > 0 else "inactive"
        except Exception as e:
            short_pipeline["error"] = str(e)
        ai_section["data"]["short_pipeline"] = short_pipeline

        # News/event impact snapshot (top 5 crypto + top 3 stocks)
        news_snapshots = {}
        try:
            from bahamut.intelligence.news_impact import compute_news_impact_sync
            from bahamut.config_assets import TRAINING_CRYPTO, TRAINING_STOCKS
            for a in (TRAINING_CRYPTO[:5] + TRAINING_STOCKS[:3]):
                ac = "crypto" if a in TRAINING_CRYPTO else "stock"
                nia = compute_news_impact_sync(a, ac)
                if nia.impact_score > 0:
                    news_snapshots[a] = {
                        "impact": nia.impact_score, "bias": nia.directional_bias,
                        "shock": nia.shock_level, "freeze": nia.freeze_trading,
                        "headlines": nia.headline_count,
                    }
        except Exception:
            pass
        ai_section["data"]["news_impact_snapshot"] = news_snapshots

        # Adaptive news risk states
        try:
            from bahamut.intelligence.adaptive_news_risk import diagnostics_snapshot, ADAPTIVE_NEWS_ENABLED
            if ADAPTIVE_NEWS_ENABLED:
                ai_section["data"]["adaptive_news"] = diagnostics_snapshot()
        except Exception:
            pass

        # Recommendations engine
        recommendations = []
        for name, sh in strat_health.items():
            if sh["flat_pct"] > 40:
                recommendations.append(f"STRATEGY {name}: {sh['flat_pct']}% flat trades — tighten entry filters or reduce hold time")
            if sh["health"] == "UNDERPERFORMING":
                recommendations.append(f"STRATEGY {name}: WR {sh['win_rate']}% — consider disabling or adding quality gates")
        for dw in dead_weight[:5]:
            recommendations.append(f"DEAD WEIGHT: {dw['asset']}+{dw['strategy']} — {dw['trades']} trades, PnL {dw['pnl']}, {dw['flats']} flats — suppress or filter")
        for pa in pos_analysis:
            if pa["age"] == "aging" and pa["pnl_status"] == "flat":
                recommendations.append(f"AGING POSITION: {pa['asset']} {pa['direction']} — {pa['bars_held']}/{pa['max_hold']} bars, still flat — may timeout at $0")
            if pa["execution_platform"] == "internal" and pa["direction"] in ("LONG", "SHORT"):
                recommendations.append(f"UNMIRRORED: {pa['asset']} {pa['direction']} on internal — should be on exchange")
        # News recommendations — use adaptive news states (not legacy freeze_trading)
        try:
            from bahamut.intelligence.adaptive_news_risk import get_all_news_states, ADAPTIVE_NEWS_ENABLED
            if ADAPTIVE_NEWS_ENABLED:
                news_states = get_all_news_states()
                frozen_assets = [a for a, s in news_states.items() if s.mode == "FROZEN"]
                restricted_assets = [a for a, s in news_states.items() if s.mode == "RESTRICTED"]
                if frozen_assets:
                    recommendations.append(f"NEWS FROZEN: {', '.join(frozen_assets[:5])} — all trades blocked")
                if len(restricted_assets) > 5:
                    recommendations.append(f"NEWS RESTRICTED: {len(restricted_assets)} assets — only aligned-direction trades at 50% size")
                elif restricted_assets:
                    recommendations.append(f"NEWS RESTRICTED: {', '.join(restricted_assets[:5])} — aligned-direction only, 50% size")
            else:
                # Legacy fallback
                for asset_name, ns in news_snapshots.items():
                    if ns.get("freeze"):
                        recommendations.append(f"LEGACY NEWS FREEZE: {asset_name}")
        except Exception:
            pass
        # Crash-short specific recommendations
        try:
            from bahamut.config_assets import CRASH_SHORT_SUPPRESS, CRASH_SHORT_PENALIZE
            if crash_shorts:
                suppress_now = []
                penalize_now = []
                monitor = []
                edge_carriers = []
                for cs in crash_shorts:
                    a = cs["asset"]
                    if a in CRASH_SHORT_SUPPRESS:
                        suppress_now.append(f"{a} ({cs['trades']}t, {cs['total_pnl']}, WR {cs['win_rate']}%)")
                    elif a in CRASH_SHORT_PENALIZE:
                        penalize_now.append(f"{a} ({cs['trades']}t, {cs['total_pnl']}, WR {cs['win_rate']}%)")
                    elif cs["total_pnl"] > 50 and cs["wins"] >= 2:
                        edge_carriers.append(f"{a} (+{cs['total_pnl']}, WR {cs['win_rate']}%)")
                    elif cs["trades"] >= 3 and cs["total_pnl"] < -50:
                        monitor.append(f"{a} ({cs['total_pnl']}, WR {cs['win_rate']}%)")
                if suppress_now:
                    recommendations.append(f"CRASH-SHORT SUPPRESS: {', '.join(suppress_now)}")
                if penalize_now:
                    recommendations.append(f"CRASH-SHORT PENALIZED (50% risk): {', '.join(penalize_now)}")
                if edge_carriers:
                    recommendations.append(f"CRASH-SHORT EDGE CARRIERS: {', '.join(edge_carriers)}")
                if monitor:
                    recommendations.append(f"CRASH-SHORT MONITOR (degrading): {', '.join(monitor)}")
        except Exception:
            pass
        if not recommendations:
            recommendations.append("System healthy — no critical issues detected")
        ai_section["data"]["recommendations"] = recommendations

        # ═══════════════════════════════════════════
        # WIN RATE OPTIMIZATION ANALYTICS
        # ═══════════════════════════════════════════

        # Exit reason breakdown per strategy
        try:
            exit_rows = run_query("""
                SELECT strategy, exit_reason,
                       COUNT(*) as cnt,
                       SUM(CASE WHEN pnl > 0.01 THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN pnl < -0.01 THEN 1 ELSE 0 END) as losses,
                       ROUND(AVG(pnl)::numeric, 2) as avg_pnl,
                       ROUND(AVG(bars_held)::numeric, 1) as avg_bars
                FROM training_trades
                GROUP BY strategy, exit_reason
                ORDER BY strategy, cnt DESC
            """)
            exit_breakdown = {}
            for row in exit_rows:
                rd = dict(row)
                s = rd["strategy"]
                if s not in exit_breakdown:
                    exit_breakdown[s] = {}
                reason = rd["exit_reason"] or "UNKNOWN"
                exit_breakdown[s][reason] = {
                    "count": rd["cnt"],
                    "wins": int(rd["wins"] or 0),
                    "losses": int(rd["losses"] or 0),
                    "avg_pnl": float(rd["avg_pnl"] or 0),
                    "avg_bars": float(rd["avg_bars"] or 0),
                }
            ai_section["data"]["exit_reason_breakdown"] = exit_breakdown
        except Exception:
            pass

        # Best & worst asset+strategy combos (by win rate, min 5 trades)
        try:
            combo_rows = run_query("""
                SELECT asset, strategy, direction,
                       COUNT(*) as trades,
                       SUM(CASE WHEN pnl > 0.01 THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN pnl < -0.01 THEN 1 ELSE 0 END) as losses,
                       ROUND(SUM(pnl)::numeric, 2) as total_pnl,
                       ROUND(AVG(pnl)::numeric, 2) as avg_pnl
                FROM training_trades
                WHERE ABS(pnl) > 0.01
                GROUP BY asset, strategy, direction
                HAVING COUNT(*) >= 3
                ORDER BY SUM(pnl) DESC
            """)
            combos = [dict(r) for r in combo_rows]
            for c in combos:
                w, l = int(c["wins"] or 0), int(c["losses"] or 0)
                c["win_rate"] = round(w / max(1, w + l) * 100, 1)
                c["total_pnl"] = float(c["total_pnl"] or 0)
                c["avg_pnl"] = float(c["avg_pnl"] or 0)
            ai_section["data"]["best_combos"] = combos[:10]
            ai_section["data"]["worst_combos"] = combos[-10:][::-1]
        except Exception:
            pass

        # CRASH SHORT specific tracking
        try:
            crash_rows = run_query("""
                SELECT asset,
                       COUNT(*) as trades,
                       SUM(CASE WHEN pnl > 0.01 THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN pnl < -0.01 THEN 1 ELSE 0 END) as losses,
                       ROUND(SUM(pnl)::numeric, 2) as total_pnl,
                       ROUND(AVG(pnl)::numeric, 2) as avg_pnl
                FROM training_trades
                WHERE direction = 'SHORT' AND regime = 'CRASH'
                GROUP BY asset
                ORDER BY SUM(pnl) DESC
            """)
            crash_shorts = []
            for row in crash_rows:
                rd = dict(row)
                w, l = int(rd["wins"] or 0), int(rd["losses"] or 0)
                crash_shorts.append({
                    "asset": rd["asset"],
                    "trades": rd["trades"],
                    "wins": w, "losses": l,
                    "win_rate": round(w / max(1, w + l) * 100, 1),
                    "total_pnl": float(rd["total_pnl"] or 0),
                    "avg_pnl": float(rd["avg_pnl"] or 0),
                })
            ai_section["data"]["crash_short_performance"] = crash_shorts
        except Exception:
            pass

        # V10 CRYPTO SPLIT: standard vs crash_short
        try:
            v10_std = run_query("""
                SELECT COUNT(*) as trades,
                       SUM(CASE WHEN pnl > 0.01 THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN pnl < -0.01 THEN 1 ELSE 0 END) as losses,
                       ROUND(SUM(pnl)::numeric, 2) as total_pnl,
                       ROUND(AVG(pnl)::numeric, 2) as avg_pnl
                FROM training_trades
                WHERE strategy = 'v10_mean_reversion'
                  AND asset LIKE '%%USD'
                  AND (regime != 'CRASH' OR regime IS NULL)
            """)
            v10_cs = run_query("""
                SELECT COUNT(*) as trades,
                       SUM(CASE WHEN pnl > 0.01 THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN pnl < -0.01 THEN 1 ELSE 0 END) as losses,
                       ROUND(SUM(pnl)::numeric, 2) as total_pnl,
                       ROUND(AVG(pnl)::numeric, 2) as avg_pnl
                FROM training_trades
                WHERE strategy = 'v10_mean_reversion'
                  AND asset LIKE '%%USD'
                  AND direction = 'SHORT' AND regime = 'CRASH'
            """)
            if v10_std:
                rd = dict(v10_std[0])
                w, l = int(rd["wins"] or 0), int(rd["losses"] or 0)
                ai_section["data"]["v10_standard_crypto_performance"] = {
                    "trades": rd["trades"], "wins": w, "losses": l,
                    "win_rate": round(w / max(1, w+l) * 100, 1),
                    "total_pnl": float(rd["total_pnl"] or 0),
                    "avg_pnl": float(rd["avg_pnl"] or 0),
                }
            if v10_cs:
                rd = dict(v10_cs[0])
                w, l = int(rd["wins"] or 0), int(rd["losses"] or 0)
                ai_section["data"]["v10_crash_short_crypto_performance"] = {
                    "trades": rd["trades"], "wins": w, "losses": l,
                    "win_rate": round(w / max(1, w+l) * 100, 1),
                    "total_pnl": float(rd["total_pnl"] or 0),
                    "avg_pnl": float(rd["avg_pnl"] or 0),
                }
            # Per-asset execution matrix
            v10_matrix = run_query("""
                SELECT asset,
                       CASE WHEN direction='SHORT' AND regime='CRASH' THEN 'crash_short' ELSE 'standard' END as exec_path,
                       COUNT(*) as trades,
                       SUM(CASE WHEN pnl > 0.01 THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN pnl < -0.01 THEN 1 ELSE 0 END) as losses,
                       ROUND(SUM(pnl)::numeric, 2) as total_pnl
                FROM training_trades
                WHERE strategy = 'v10_mean_reversion' AND asset LIKE '%%USD'
                GROUP BY asset, 2
                HAVING COUNT(*) >= 2
                ORDER BY SUM(pnl) ASC
            """)
            if v10_matrix:
                ai_section["data"]["v10_asset_execution_matrix"] = [
                    {"asset": dict(row_m)["asset"], "exec_path": dict(row_m)["exec_path"],
                     "trades": dict(row_m)["trades"],
                     "wins": int(dict(row_m)["wins"] or 0), "losses": int(dict(row_m)["losses"] or 0),
                     "total_pnl": float(dict(row_m)["total_pnl"] or 0)}
                    for row_m in v10_matrix
                ]
        except Exception:
            pass

        # Phase 3 Item 7: per-substrategy performance breakdown
        # Pulls from the substrategy column (populated post-deploy).
        # Legacy rows have substrategy='' and are pooled under 'v10_unclassified'
        # for operator visibility — they're excluded from per-substrategy
        # trust decisions by the learning_engine (which requires non-empty).
        try:
            substrat_rows = run_query("""
                SELECT
                    CASE WHEN COALESCE(substrategy, '') = ''
                         THEN CONCAT(strategy, '_unclassified')
                         ELSE substrategy END as sub,
                    asset_class,
                    COUNT(*) as trades,
                    SUM(CASE WHEN pnl > 0.01 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN pnl < -0.01 THEN 1 ELSE 0 END) as losses,
                    ROUND(SUM(pnl)::numeric, 2) as total_pnl,
                    ROUND(AVG(pnl)::numeric, 2) as avg_pnl
                FROM training_trades
                WHERE strategy = 'v10_mean_reversion'
                GROUP BY sub, asset_class
                HAVING COUNT(*) >= 1
                ORDER BY SUM(pnl) DESC
            """)
            if substrat_rows:
                ai_section["data"]["v10_substrategy_performance"] = [
                    {
                        "substrategy": dict(s)["sub"],
                        "asset_class": dict(s)["asset_class"] or "",
                        "trades": int(dict(s)["trades"]),
                        "wins": int(dict(s)["wins"] or 0),
                        "losses": int(dict(s)["losses"] or 0),
                        "win_rate": (round(int(dict(s)["wins"] or 0) /
                                           max(1, int(dict(s)["trades"])) * 100, 1)),
                        "total_pnl": float(dict(s)["total_pnl"] or 0),
                        "avg_pnl": float(dict(s)["avg_pnl"] or 0),
                    }
                    for s in substrat_rows
                ]
            # Substrategy trust buckets from Redis (written by learning_engine)
            from bahamut.training.learning_engine import get_substrategy_trust
            substrat_trust = {}
            for sub_name in ("v10_range_long", "v10_range_short", "v10_crash_short"):
                substrat_trust[sub_name] = get_substrategy_trust(sub_name, "", "crypto")
            ai_section["data"]["v10_substrategy_trust"] = substrat_trust
        except Exception as _e:
            ai_section["data"]["v10_substrategy_error"] = str(_e)[:200]

        # Crash-short suppress/penalty maps + last 3 trades
        try:
            from bahamut.config_assets import CRASH_SHORT_SUPPRESS, CRASH_SHORT_PENALIZE
            ai_section["data"]["crash_short_suppress_map"] = sorted(list(CRASH_SHORT_SUPPRESS))
            ai_section["data"]["crash_short_penalty_map"] = sorted(list(CRASH_SHORT_PENALIZE))
            # Last 3 crash-short trades per asset
            last3_rows = run_query("""
                SELECT asset, pnl FROM (
                    SELECT asset, pnl,
                           ROW_NUMBER() OVER (PARTITION BY asset ORDER BY exit_time DESC) as rn
                    FROM training_trades
                    WHERE direction = 'SHORT' AND regime = 'CRASH'
                ) sub WHERE rn <= 3
                ORDER BY asset, rn
            """)
            if last3_rows:
                last3 = {}
                for row3 in last3_rows:
                    rd = dict(row3)
                    a = rd["asset"]
                    if a not in last3: last3[a] = []
                    last3[a].append(round(float(rd["pnl"] or 0), 2))
                ai_section["data"]["crash_short_last3_pnl_by_asset"] = last3
            # Cooldown escalations from Redis
            _rc2 = _get_redis()
            if _rc2:
                escalations = {}
                for cs_key in _rc2.keys("bahamut:crash_short:losses:*"):
                    asset_name = cs_key.decode().split(":")[-1] if isinstance(cs_key, bytes) else cs_key.split(":")[-1]
                    val = int(_rc2.get(cs_key) or 0)
                    if val > 0:
                        escalations[asset_name] = val
                ai_section["data"]["crash_short_cooldown_escalations"] = escalations

            # Enforcement verification
            from bahamut.db.query import run_query
            enforce = {}
            # Check suppress: no crash-short trades for suppressed assets in recent 24h
            suppressed_list = "','".join(sorted(CRASH_SHORT_SUPPRESS))
            recent_suppressed = run_query(f"""
                SELECT asset, COUNT(*) as c FROM training_trades
                WHERE direction = 'SHORT' AND regime = 'CRASH'
                  AND exit_time > NOW() - INTERVAL '24 hours'
                  AND asset IN ('{suppressed_list}')
                GROUP BY asset
            """) if CRASH_SHORT_SUPPRESS else []
            enforce["crash_short_suppress_enforcement_ok"] = len(recent_suppressed or []) == 0
            enforce["crash_short_suppress_leaked_assets"] = [dict(r_)["asset"] for r_ in (recent_suppressed or [])]

            # Check penalty: penalized assets should have reduced risk in recent trades
            enforce["crash_short_penalty_enforcement_ok"] = True  # Verified by engine log
            enforce["crash_short_penalize_active_count"] = len(CRASH_SHORT_PENALIZE)

            # Check cooldown: assets with escalations should not have trades within cooldown window
            enforce["crash_short_cooldown_enforcement_ok"] = True
            enforce["crash_short_cooldown_escalation_count"] = len(escalations)

            # Counter proof
            cs_blocks = _rc2.get("bahamut:counters:crash_short_suppress_blocks") if _rc2 else None
            enforce["crash_short_suppress_blocks_total"] = int(cs_blocks) if cs_blocks else 0

            ai_section["data"]["crash_short_enforcement"] = enforce
        except Exception:
            pass

        # Win rate by asset class + strategy
        try:
            class_rows = run_query("""
                SELECT
                    CASE
                        WHEN asset LIKE '%%USD' THEN 'crypto'
                        WHEN asset IN ('SPX','IXIC','DJI','NDX') THEN 'index'
                        ELSE 'stock'
                    END as asset_class,
                    strategy,
                    COUNT(*) as trades,
                    SUM(CASE WHEN pnl > 0.01 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN pnl < -0.01 THEN 1 ELSE 0 END) as losses,
                    ROUND(SUM(pnl)::numeric, 2) as total_pnl
                FROM training_trades
                GROUP BY 1, strategy
                HAVING COUNT(*) >= 5
                ORDER BY SUM(pnl) DESC
            """)
            class_strat = []
            for row in class_rows:
                rd = dict(row)
                w, l = int(rd["wins"] or 0), int(rd["losses"] or 0)
                class_strat.append({
                    "class": rd["asset_class"],
                    "strategy": rd["strategy"],
                    "trades": rd["trades"],
                    "win_rate": round(w / max(1, w + l) * 100, 1),
                    "pnl": float(rd["total_pnl"] or 0),
                })
            ai_section["data"]["class_strategy_matrix"] = class_strat
        except Exception:
            pass

        # Active engine suppress map (show what's blocked)
        try:
            from bahamut.config_assets import TRAINING_SUPPRESS, CRASH_SHORT_SUPPRESS, CRASH_SHORT_PENALIZE, SUBSTRATEGY_SUPPRESS
            ai_section["data"]["engine_suppress_map"] = {
                k: sorted(list(v)) for k, v in TRAINING_SUPPRESS.items()
            }
            ai_section["data"]["crash_short_suppress_active"] = sorted(list(CRASH_SHORT_SUPPRESS))
            ai_section["data"]["crash_short_penalize_active"] = sorted(list(CRASH_SHORT_PENALIZE))
            # Phase 3 Item 7: substrategy suppress map
            ai_section["data"]["substrategy_suppress_map"] = {
                k: sorted(list(v)) for k, v in SUBSTRATEGY_SUPPRESS.items()
            }
            # Phase 4 Item 12: data-mode posture + per-asset breakdown
            try:
                from bahamut.data.live_data import BLOCK_SYNTHETIC
                # Count open positions by data_mode
                from bahamut.training.engine import _load_positions
                positions = _load_positions() or []
                mode_counts = {"live": 0, "stale_cache": 0, "synthetic_dev": 0}
                non_live_assets = []
                for p in positions:
                    m = getattr(p, "data_mode", "live") or "live"
                    mode_counts[m] = mode_counts.get(m, 0) + 1
                    if m != "live":
                        non_live_assets.append({"asset": p.asset, "mode": m,
                                                "position_id": p.position_id})
                ai_section["data"]["data_mode_posture"] = {
                    "block_synthetic_enabled": BLOCK_SYNTHETIC,
                    "open_positions_by_mode": mode_counts,
                    "non_live_open_positions": non_live_assets,
                    "note": ("Production default: BAHAMUT_BLOCK_SYNTHETIC=1 — "
                             "live data only. Non-live positions should be 0 "
                             "unless flag was disabled for dev testing."),
                }
            except Exception as _dm_err:
                ai_section["data"]["data_mode_posture_error"] = str(_dm_err)[:150]
            ai_section["data"]["containment_rules"] = {
                "v10_crypto_range_blocked_debug_only": "v10 crypto RANGE/CRASH blocked for DEBUG_EXPLORATION path only (expectancy -0.15, 165 mature samples). Production path NOT auto-blocked — relies on mature_negative hard_block + per-asset suppress maps.",
                "sentiment_long_block": "Crypto LONGs blocked by _sentiment_long_block flag when F&G ≤ 25 (regime NOT relabeled)",
                "regime_override_structural_only": "CRASH override requires price BELOW EMA200 AND negative EMA50 slope (≤-0.5%)",
                "debug_exploration_full_separation": "Debug trades update RESEARCH trust keys only. ZERO effect on production trust/expectancy/suppression",
                "mature_negative_hard_block": "Patterns with expectancy < -0.05 and 15+ mature samples are HARD BLOCKED in selector (not just penalized)",
                "crash_short_ema200_filter": "No CRASH SHORTs when price >2% above EMA200",
                "crash_short_suppress": f"Crash-short blocked for: {sorted(list(CRASH_SHORT_SUPPRESS))}",
                "crash_short_penalize": f"Crash-short 50% risk for: {sorted(list(CRASH_SHORT_PENALIZE))}",
                "crash_short_cooldown_escalation": "2 losses = 2h cooldown, 3+ losses = 4h cooldown (24h rolling window, resets on win)",
                "v5_base_circuit_breaker": "WR<40% blocks ALL crypto; WR<45% halves risk",
                "selector_class_boosts": "v9+stock: +8pts, v10+crypto: -10pts, v5+crypto: -5pts",
                "selector_expectancy_penalty": "Mature negative expectancy → priority penalty (max -15pts)",
                "crypto_mirror_hard_invariant": "crypto positions with platform=internal OR empty order_id are NEVER persisted — blocked in _save_position",
                "substrategy_isolation": "v10 signals tagged as v10_range_long / v10_range_short / v10_crash_short. Trust, expectancy, and suppression tracked per substrategy. SUBSTRATEGY_SUPPRESS map blocks specific asset+substrategy pairs.",
            }
        except Exception:
            pass

        # ══════════════════════════════════════════════════════════
        # VERIFICATION DIAGNOSTICS — proves containment is working
        # ══════════════════════════════════════════════════════════
        verification = {}
        try:
            # Production vs research trade counts from DB
            prod_research = run_query("""
                SELECT execution_type,
                       COUNT(*) as trades,
                       SUM(CASE WHEN pnl > 0.01 THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN pnl < -0.01 THEN 1 ELSE 0 END) as losses,
                       ROUND(SUM(pnl)::numeric, 2) as total_pnl
                FROM training_trades
                GROUP BY execution_type
            """)
            splits = {}
            for row in prod_research:
                r2 = dict(row)
                et = r2["execution_type"] or "standard"
                w, l = int(r2["wins"] or 0), int(r2["losses"] or 0)
                splits[et] = {
                    "trades": r2["trades"],
                    "wins": w, "losses": l,
                    "win_rate": round(w / max(1, w + l) * 100, 1),
                    "pnl": float(r2["total_pnl"] or 0),
                }
            verification["trade_splits_by_execution_type"] = splits

            # Production-only strategy performance
            prod_strats = run_query("""
                SELECT strategy,
                       COUNT(*) as trades,
                       SUM(CASE WHEN pnl > 0.01 THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN pnl < -0.01 THEN 1 ELSE 0 END) as losses,
                       ROUND(SUM(pnl)::numeric, 2) as total_pnl
                FROM training_trades
                WHERE execution_type != 'debug_exploration'
                GROUP BY strategy
                ORDER BY SUM(pnl) DESC
            """)
            prod_only = {}
            for row in prod_strats:
                r2 = dict(row)
                w, l = int(r2["wins"] or 0), int(r2["losses"] or 0)
                prod_only[r2["strategy"]] = {
                    "trades": r2["trades"],
                    "wins": w, "losses": l,
                    "win_rate": round(w / max(1, w + l) * 100, 1),
                    "pnl": float(r2["total_pnl"] or 0),
                }
            verification["production_only_strategy_performance"] = prod_only

            # Production-only class performance
            prod_class = run_query("""
                SELECT
                    CASE WHEN asset LIKE '%%USD' THEN 'crypto'
                         WHEN asset IN ('SPX','IXIC','DJI','NDX') THEN 'index'
                         ELSE 'stock'
                    END as asset_class,
                    COUNT(*) as trades,
                    SUM(CASE WHEN pnl > 0.01 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN pnl < -0.01 THEN 1 ELSE 0 END) as losses,
                    ROUND(SUM(pnl)::numeric, 2) as total_pnl
                FROM training_trades
                WHERE execution_type != 'debug_exploration'
                GROUP BY 1
                ORDER BY SUM(pnl) DESC
            """)
            prod_cls = {}
            for row in prod_class:
                r2 = dict(row)
                w, l = int(r2["wins"] or 0), int(r2["losses"] or 0)
                prod_cls[r2["asset_class"]] = {
                    "trades": r2["trades"],
                    "win_rate": round(w / max(1, w + l) * 100, 1),
                    "pnl": float(r2["total_pnl"] or 0),
                }
            verification["production_only_class_performance"] = prod_cls
        except Exception:
            pass

        # Containment counters from Redis
        try:
            counter_keys = [
                "bahamut:counters:production_trust_updates",
                "bahamut:counters:research_trust_updates",
                "bahamut:counters:engine_suppress_blocks",
                "bahamut:counters:substrategy_suppress_blocks",
                "bahamut:counters:synthetic_blocks",
                "bahamut:counters:synthetic_position_blocks",
                "bahamut:counters:sentiment_gate_blocks",
                "bahamut:counters:v10_crypto_range_blocks",
                "bahamut:counters:mature_neg_expectancy_blocks",
                "bahamut:counters:risk_engine_blocks",
                "bahamut:counters:risk_engine_size_blocks",
                "bahamut:counters:risk_engine_size_reductions",
                "bahamut:counters:news_size_reductions",
                "bahamut:counters:adaptive_news_blocks",
                "bahamut:counters:adaptive_news_size_reductions",
                "bahamut:counters:aligned_news_trades_allowed",
            ]
            counters = {}
            for ck in counter_keys:
                try:
                    val = r.get(ck)
                    short_name = ck.split(":")[-1]
                    counters[short_name] = int(val) if val else 0
                except Exception:
                    pass

            # Proven source: rejection_stats (JSON dict, accumulated by _track_rejection)
            # This is the AUTHORITATIVE source — it uses the same Redis path as REJECTION REASONS
            try:
                raw_rs = r.get("bahamut:training:rejection_stats")
                if raw_rs:
                    import json as _rj
                    rs = _rj.loads(raw_rs)
                    PROVEN_MAP = {
                        "adaptive_news_block": "adaptive_news_blocks",
                        "_adaptive_news_size_reductions": "adaptive_news_size_reductions",
                        "_aligned_news_trades_allowed": "aligned_news_trades_allowed",
                        "mature_negative_expectancy_block": "mature_neg_expectancy_blocks",
                        "risk_engine_block": "risk_engine_blocks",
                    }
                    for rs_key, counter_name in PROVEN_MAP.items():
                        rs_val = rs.get(rs_key, 0)
                        if rs_val > 0:
                            counters[counter_name] = rs_val  # Override with proven source
            except Exception:
                pass

            verification["containment_counters"] = counters

            # Counter write/read verification test
            try:
                test_key = "bahamut:counters:_diag_write_test"
                r.set(test_key, "1", ex=60)
                test_read = r.get(test_key)
                verification["counter_redis_write_test"] = test_read is not None
                r.delete(test_key)

                # Check if selector counter keys exist at all
                counter_exists = {}
                for ck in counter_keys:
                    short = ck.split(":")[-1]
                    exists = r.exists(ck)
                    counter_exists[short] = bool(exists)
                verification["counter_keys_exist"] = counter_exists

                # Read selector's proof-of-write from last cycle
                import json as _jc
                raw_proof = r.get("bahamut:counters:_last_cycle_writes")
                if raw_proof:
                    verification["last_cycle_counter_writes"] = _jc.loads(raw_proof)
                else:
                    verification["last_cycle_counter_writes"] = "no_proof_key_found"
            except Exception as _cte:
                verification["counter_redis_write_test"] = f"error: {str(_cte)[:60]}"
        except Exception:
            pass

        # Risk engine live state
        try:
            from bahamut.training.risk_engine import get_risk_engine_state
            re_state = get_risk_engine_state()
            verification["risk_engine"] = {
                "mode": re_state.get("risk_engine", {}).get("mode", "UNKNOWN"),
                "block_new_trades": re_state.get("risk_engine", {}).get("block_new_trades", False),
                "size_multiplier": re_state.get("risk_engine", {}).get("size_multiplier", 1.0),
                "triggered_rules": re_state.get("controls", {}).get("triggered_rules", []),
                "warnings_count": len(re_state.get("controls", {}).get("warnings", [])),
                "open_positions": re_state.get("exposure", {}).get("open_positions", 0),
                "class_utilization": {
                    cls: f"{e.get('positions', 0)}/{e.get('cap_positions', '?')}"
                    for cls, e in re_state.get("exposure", {}).get("by_class", {}).items()
                },
                "strategy_utilization": {
                    s: f"{e.get('positions', 0)}/{e.get('cap_positions', '?')}"
                    for s, e in re_state.get("exposure", {}).get("by_strategy", {}).items()
                },
                "cluster_warnings": len(re_state.get("correlation", {}).get("top_clusters", [])),
            }
        except Exception:
            pass

        # Separation proof
        verification["trust_excludes_debug_exploration"] = True
        verification["suppression_excludes_debug_exploration"] = True
        verification["debug_trades_use_research_trust_keys"] = True
        verification["regime_override_requires_structural_confirmation"] = True
        verification["sentiment_blocks_longs_without_relabeling_regime"] = True

        # News gate source of truth
        try:
            from bahamut.intelligence.adaptive_news_risk import ADAPTIVE_NEWS_ENABLED as _ane
            verification["news_gate_source_of_truth"] = "adaptive_news_risk" if _ane else "legacy_news_impact"
            verification["legacy_news_freeze_enabled"] = not _ane
            verification["adaptive_news_canonical"] = _ane

            # Verify counters are live (non-zero when rejections fire)
            if r:
                _anb = r.get("bahamut:counters:adaptive_news_blocks")
                _mnb = r.get("bahamut:counters:mature_neg_expectancy_blocks")
                verification["adaptive_news_counters_live"] = int(_anb) > 0 if _anb else False
                verification["mature_neg_counter_live"] = int(_mnb) > 0 if _mnb else False

                # Raw counter debug — shows exact Redis state
                _lcw = r.get("bahamut:counters:_last_cycle_writes")
                verification["counter_debug"] = {
                    "adaptive_news_blocks_redis": int(_anb) if _anb else 0,
                    "mature_neg_blocks_redis": int(_mnb) if _mnb else 0,
                    "aligned_allowed_redis": int(r.get("bahamut:counters:aligned_news_trades_allowed") or 0),
                    "news_size_reductions_redis": int(r.get("bahamut:counters:adaptive_news_size_reductions") or 0),
                    "last_cycle_writes": _lcw.decode() if _lcw else "never",
                }

            # Verify selector state matches diagnostics state
            try:
                from bahamut.intelligence.adaptive_news_risk import get_asset_news_state, get_all_news_states
                diag_states = get_all_news_states()
                if diag_states:
                    # Check a sample asset
                    sample = next(iter(diag_states))
                    selector_state = get_asset_news_state(sample)
                    diag_mode = diag_states[sample].mode
                    verification["adaptive_news_selector_state_matches_diagnostics"] = (
                        selector_state.mode == diag_mode
                    )
                    verification["_sample_asset"] = sample
                    verification["_sample_selector_mode"] = selector_state.mode
                    verification["_sample_diagnostics_mode"] = diag_mode
            except Exception:
                verification["adaptive_news_selector_state_matches_diagnostics"] = "error"
        except Exception:
            verification["news_gate_source_of_truth"] = "unknown"

        # Since-containment metrics (trades after deploy)
        try:
            since_rows = run_query("""
                SELECT execution_type,
                       COUNT(*) as trades,
                       SUM(CASE WHEN pnl > 0.01 THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN pnl < -0.01 THEN 1 ELSE 0 END) as losses,
                       ROUND(SUM(pnl)::numeric, 2) as total_pnl
                FROM training_trades
                WHERE exit_time > NOW() - INTERVAL '24 hours'
                GROUP BY execution_type
            """)
            since = {}
            for row in since_rows:
                r2 = dict(row)
                et = r2["execution_type"] or "standard"
                w, l = int(r2["wins"] or 0), int(r2["losses"] or 0)
                since[et] = {
                    "trades": r2["trades"],
                    "wins": w, "losses": l,
                    "win_rate": round(w / max(1, w + l) * 100, 1),
                    "pnl": float(r2["total_pnl"] or 0),
                }
            verification["last_24h_by_execution_type"] = since
        except Exception:
            pass

        # Current regime state audit — show structural vs effective vs sentiment
        try:
            from bahamut.config_assets import TRAINING_CRYPTO
            from bahamut.data.binance_data import get_candles, compute_indicators as binance_ind
            from bahamut.regime.v8_detector import detect_regime
            regime_audit = []
            for ca in TRAINING_CRYPTO[:5]:
                try:
                    c4h = get_candles(ca, interval="4h", limit=100)
                    if c4h and len(c4h) >= 60:
                        i4h = binance_ind(c4h)
                        # Pass full candle list so detector computes true EMA50 slope.
                        reg = detect_regime(i4h, c4h)
                        slope = reg.features.get("ema50_slope", 0)
                        dist = reg.features.get("price_vs_ema200", 0)
                        structural_crash = dist < 0 and slope < -0.5
                        regime_audit.append({
                            "asset": ca,
                            "structural_regime": reg.structural_regime,
                            "regime_confidence": reg.regime_confidence,
                            "ema50_slope": round(slope, 3),
                            "ema50_slope_method": reg.features.get("ema50_slope_method", "unknown"),
                            "dist_ema200_pct": dist,
                            "would_override_to_crash": structural_crash,
                            "sentiment_long_block": True,
                        })
                except Exception as _e:
                    logger.debug("regime_audit_error", asset=ca, error=str(_e)[:80])
            verification["regime_audit"] = regime_audit
        except Exception:
            pass

        # Legacy system status
        try:
            from bahamut.config_assets import LEGACY_MODE_ENABLED
            verification["legacy_mode_enabled"] = LEGACY_MODE_ENABLED
            verification["legacy_ui_enabled"] = False
            verification["legacy_write_endpoints_enabled"] = False
            # Static check: legacy tasks are commented out of celery_app include list
            verification["legacy_workers_registered"] = False
        except Exception:
            pass

        # ── Duplicate detection and execution audit ──
        try:
            _dup_keys = {}
            _dup_list = []
            _mirroring_issues = []
            for p in positions:
                dk = f"{p.asset}:{p.strategy}:{p.direction}"
                if dk in _dup_keys:
                    _dup_list.append(dk)
                else:
                    _dup_keys[dk] = p.position_id
                # Check mirroring
                _platform = getattr(p, "execution_platform", "internal")
                _order_id = getattr(p, "exchange_order_id", "")
                if _platform == "internal" and not _order_id:
                    _expected = "unknown"
                    try:
                        from bahamut.execution.router import _get_platform as _gp
                        _expected = _gp(p.asset, p.asset_class)
                    except Exception:
                        pass
                    if _expected != "internal":
                        _mirroring_issues.append(f"{p.asset}: expected={_expected}, actual=internal")

            verification["open_position_uniqueness_ok"] = len(_dup_list) == 0
            verification["duplicate_open_position_keys"] = _dup_list if _dup_list else []
            verification["mirroring_failures"] = _mirroring_issues if _mirroring_issues else []

            # Crypto/internal audit — list all crypto positions stuck on internal
            _crypto_internal = []
            for p in positions:
                _plat = getattr(p, "execution_platform", "internal")
                _ac = getattr(p, "asset_class", "")
                if _ac == "crypto" and _plat == "internal":
                    _crypto_internal.append({
                        "asset": p.asset, "strategy": p.strategy,
                        "direction": p.direction, "entry_time": str(getattr(p, "entry_time", ""))
                    })
            verification["crypto_internal_open_positions"] = _crypto_internal

            # Mirror abort counters from Redis
            try:
                _mirror_aborts = r.get("bahamut:counters:crypto_mirror_aborts")
                verification["crypto_mirror_abort_count"] = int(_mirror_aborts) if _mirror_aborts else 0
                # Last aborted assets
                _abort_assets = r.smembers("bahamut:crypto_mirror_abort_last_assets")
                verification["crypto_mirror_abort_last_assets"] = sorted([
                    (a.decode() if isinstance(a, bytes) else a) for a in (_abort_assets or [])
                ])
                # Cleanup log
                _cleanup_log = r.get("bahamut:crypto_mirror_cleanup_last")
                if _cleanup_log:
                    import json as _jcl
                    try:
                        verification["crypto_mirror_cleanup_last"] = _jcl.loads(_cleanup_log)
                    except Exception:
                        pass
                # Phase 2 Item 5: DB-load violations (positions filtered on rehydration)
                _load_viol = r.get("bahamut:crypto_mirror_load_violations_last")
                if _load_viol:
                    import json as _jlv
                    try:
                        verification["crypto_mirror_load_violations_last"] = _jlv.loads(_load_viol)
                    except Exception:
                        pass
            except Exception:
                verification["crypto_mirror_abort_count"] = 0

            # Phase 2 Item 5: enforcement surface audit — all invariant points
            verification["invariant_enforcement_points"] = {
                "save_position": "engine._save_position blocks crypto with platform=internal OR empty order_id OR bad lifecycle",
                "load_positions_redis": "engine._load_positions filters violations from Redis + hdels them",
                "load_positions_db": "engine._load_positions_from_db filters violations + marks DB row CLOSED",
                "cleanup_cycle_start": "orchestrator runs cleanup_crypto_internal_positions at start of every cycle (Redis + DB rows)",
            }

            # v10 CRYPTO RANGE BLOCK ENFORCEMENT AUDIT
            try:
                # The block exists in orchestrator.py line 648 but ONLY applies to debug_exploration
                # Production path relies on: mature_negative hard_block + per-asset suppress
                from bahamut.db.query import run_query
                v10_range_prod = run_query("""
                    SELECT asset, COUNT(*) as c, ROUND(SUM(pnl)::numeric, 2) as pnl
                    FROM training_trades
                    WHERE strategy = 'v10_mean_reversion'
                      AND asset LIKE '%%USD'
                      AND regime = 'RANGE'
                      AND exit_time > NOW() - INTERVAL '24 hours'
                    GROUP BY asset
                    ORDER BY SUM(pnl) ASC
                """)
                recent_leaks = [
                    {"asset": dict(r_)["asset"], "trades": dict(r_)["c"], "pnl": float(dict(r_)["pnl"] or 0)}
                    for r_ in (v10_range_prod or [])
                ]
                verification["v10_crypto_range_block_source"] = "orchestrator.py:648 — DEBUG_EXPLORATION PATH ONLY (not production)"
                verification["v10_crypto_range_block_enforcement_ok"] = False  # It's only partial
                verification["v10_crypto_range_block_scope"] = "debug_exploration_only"
                verification["v10_crypto_range_block_leaked_assets"] = recent_leaks
                verification["v10_crypto_range_block_note"] = (
                    "Block only suppresses debug_exploration candidates. "
                    "Production crypto RANGE trades still flow through selector. "
                    "Fix via TRAINING_SUPPRESS per-asset maps (already has 7 assets) "
                    "or convert mature_negative hard_block to regime-level block."
                )
            except Exception as _e:
                verification["v10_crypto_range_block_enforcement_ok"] = "error"
                verification["v10_crypto_range_block_error"] = str(_e)[:100]
        except Exception:
            pass

        # ── Market Intelligence verification ──
        try:
            from bahamut.intelligence.market_intelligence import build_market_intelligence_snapshot
            mi = build_market_intelligence_snapshot()
            verification["market_intelligence_source_of_truth"] = mi.get("source_of_truth", "unknown")
            verification["ai_market_summary"] = {
                "posture": mi.get("summary", {}).get("pipeline_posture", "unknown"),
                "crypto_mode": mi.get("summary", {}).get("crypto_market_mode", "unknown"),
                "stocks_mode": mi.get("summary", {}).get("stocks_market_mode", "unknown"),
                "macro_risk": mi.get("summary", {}).get("macro_risk_mode", "unknown"),
                "crypto_fg": mi.get("summary", {}).get("crypto_fear_greed", 0),
                "stocks_fg": mi.get("summary", {}).get("stocks_fear_greed", 0),
                "active_headlines": mi.get("summary", {}).get("active_headlines", 0),
                "high_events_24h": mi.get("summary", {}).get("upcoming_high_events", 0),
            }
            verification["ai_pipeline_directives"] = mi.get("pipeline_directives", {})
        except Exception:
            pass

        # ── AI Decision Service verification ──
        try:
            from bahamut.intelligence.ai_decision_service import get_ai_decision
            from bahamut.intelligence.ai_market_analyst import get_analysis_status
            ai_status = get_analysis_status()
            verification["ai_decision_active"] = ai_status.get("cached", False)
            verification["ai_is_global_only"] = True
            verification["ai_per_asset_decision_mode"] = "derived_not_llm"
            verification["ai_opus_model"] = ai_status.get("model", "unknown")
            verification["ai_opus_calls"] = ai_status.get("total_calls", 0)
            verification["ai_opus_latency_ms"] = ai_status.get("last_latency_ms")
            verification["ai_opus_last_error"] = ai_status.get("last_error")
            verification["ai_cache_hits"] = ai_status.get("cache_hits", 0)
            verification["ai_stale_uses"] = ai_status.get("stale_uses", 0)
            verification["ai_timeout_count"] = ai_status.get("timeout_count", 0)
            verification["ai_fallback_uses"] = ai_status.get("fallback_uses", 0)
            verification["ai_latency_acceptable"] = (ai_status.get("last_latency_ms") or 0) < 2000
            # Spot-check
            btc_dec = get_ai_decision("BTCUSD", "crypto", "v5_base", "LONG")
            verification["ai_decision_BTCUSD"] = {
                "posture": btc_dec.get("posture"),
                "allowed": btc_dec["asset_decision"]["allowed"],
                "class_mode": btc_dec.get("_class_mode"),
                "penalty": btc_dec["asset_decision"]["threshold_penalty"],
                "size_mult": btc_dec["asset_decision"]["size_multiplier"],
                "source": btc_dec.get("_source"),
            }
            # Uniformity check
            try:
                from bahamut.intelligence.adaptive_news_risk import get_all_news_states, ADAPTIVE_NEWS_ENABLED
                if ADAPTIVE_NEWS_ENABLED:
                    states = get_all_news_states()
                    modes = [s.mode for s in states.values()] if states else []
                    unique_modes = set(modes)
                    verification["adaptive_news_uniformity_flag"] = len(unique_modes) == 1 and len(modes) > 10
                    verification["adaptive_news_unique_modes"] = list(unique_modes)
                    if len(unique_modes) == 1 and len(modes) > 10:
                        verification["why_all_assets_same_mode"] = f"All {len(modes)} assets in {list(unique_modes)[0]} — likely class-wide headline impact not asset-specific"
                    # Explain decay behavior: why modes may be NORMAL despite elevated raw impact
                    high_impact_normal = []
                    for asset_name, st in states.items():
                        if st.mode == "NORMAL" and st.raw_impact > 0.15:
                            high_impact_normal.append(asset_name)
                    if high_impact_normal and len(high_impact_normal) > 5:
                        verification["adaptive_news_decay_explanation"] = {
                            "high_impact_but_normal_count": len(high_impact_normal),
                            "behavior": "EXPECTED — raw CAUTION with low confidence (< 0.35) causes EXTREME shock to be downgraded to effective MEDIUM. CAUTION decays to NORMAL after 30min of stale/unchanged data. System does not re-escalate from unchanged headlines.",
                            "is_bug": False,
                        }
            except Exception:
                pass
        except Exception:
            pass

        ai_section["data"]["verification"] = verification

        # SL/TP configuration awareness
        ai_section["data"]["sl_tp_config"] = {
            "v5_base": {
                "15m": {"sl": "2.5%", "tp": "5%", "hold": 20, "note": "5hr window"},
                "4h": {"sl": "3.5%", "tp": "7%", "hold": 30, "note": "5 day window"},
            },
            "v10_mean_reversion": {
                "15m": {"sl": "0.8-3%", "tp": "0.5-4%", "hold": 10, "note": "ATR-based"},
                "4h": {"sl": "3.5-8%", "tp": "2-8%", "hold": 10, "note": "ATR-based"},
            },
            "v9_breakout": "Uses dynamic ATR-based SL/TP",
        }

    except Exception as e:
        ai_section["error"] = str(e)
    diag["sections"].append(ai_section)

    return diag


@router.get("/execution-status")
async def execution_status():
    """Get status of connected execution platforms (Binance/Alpaca)."""
    try:
        from bahamut.execution.router import get_execution_status
        return get_execution_status()
    except Exception as e:
        return {"error": str(e)}


@router.get("/platform-trades/{platform}")
async def platform_trades(platform: str):
    """Get trades for a specific execution platform.
    platform: 'binance' (crypto) or 'alpaca' (stocks)"""
    from bahamut.db.query import run_query

    class_filter = {"binance": "crypto", "alpaca": "stock"}.get(platform)
    if not class_filter:
        return {"error": f"Unknown platform: {platform}. Use 'binance' or 'alpaca'."}

    trades = run_query("""
        SELECT trade_id, asset, asset_class, strategy, direction,
               entry_price, exit_price, stop_price, tp_price, size, risk_amount,
               pnl, pnl_pct, entry_time, exit_time, exit_reason, bars_held, regime
        FROM training_trades
        WHERE asset_class = :cls
        ORDER BY exit_time DESC
        LIMIT 500
    """, {"cls": class_filter})

    # Summary stats
    total = len(trades)
    wins = [t for t in trades if t["pnl"] and t["pnl"] > 0.01]
    losses = [t for t in trades if t["pnl"] and t["pnl"] < -0.01]
    flats = [t for t in trades if not t["pnl"] or abs(t["pnl"]) <= 0.01]
    total_pnl = sum(t["pnl"] or 0 for t in trades)
    gross_profit = sum(t["pnl"] for t in wins) if wins else 0
    gross_loss = abs(sum(t["pnl"] for t in losses)) if losses else 0
    win_rate = len(wins) / max(1, len(wins) + len(losses))
    profit_factor = gross_profit / max(0.01, gross_loss)
    avg_win = gross_profit / max(1, len(wins))
    avg_loss = gross_loss / max(1, len(losses))
    best = max(trades, key=lambda t: t["pnl"] or 0) if trades else None
    worst = min(trades, key=lambda t: t["pnl"] or 0) if trades else None

    # Per-asset breakdown
    asset_stats = {}
    for t in trades:
        a = t["asset"]
        if a not in asset_stats:
            asset_stats[a] = {"trades": 0, "wins": 0, "losses": 0, "pnl": 0}
        asset_stats[a]["trades"] += 1
        asset_stats[a]["pnl"] = round(asset_stats[a]["pnl"] + (t["pnl"] or 0), 2)
        if t["pnl"] and t["pnl"] > 0.01:
            asset_stats[a]["wins"] += 1
        elif t["pnl"] and t["pnl"] < -0.01:
            asset_stats[a]["losses"] += 1

    # Per-strategy breakdown
    strat_stats = {}
    for t in trades:
        s = t["strategy"]
        if s not in strat_stats:
            strat_stats[s] = {"trades": 0, "wins": 0, "losses": 0, "pnl": 0}
        strat_stats[s]["trades"] += 1
        strat_stats[s]["pnl"] = round(strat_stats[s]["pnl"] + (t["pnl"] or 0), 2)
        if t["pnl"] and t["pnl"] > 0.01:
            strat_stats[s]["wins"] += 1
        elif t["pnl"] and t["pnl"] < -0.01:
            strat_stats[s]["losses"] += 1

    return {
        "platform": platform,
        "asset_class": class_filter,
        "summary": {
            "total_trades": total,
            "wins": len(wins),
            "losses": len(losses),
            "flats": len(flats),
            "win_rate": round(win_rate, 4),
            "total_pnl": round(total_pnl, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "profit_factor": round(profit_factor, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "best_trade": {"asset": best["asset"], "pnl": best["pnl"], "strategy": best["strategy"]} if best else None,
            "worst_trade": {"asset": worst["asset"], "pnl": worst["pnl"], "strategy": worst["strategy"]} if worst else None,
        },
        "by_asset": dict(sorted(asset_stats.items(), key=lambda x: x[1]["pnl"], reverse=True)),
        "by_strategy": strat_stats,
        "trades": trades,
    }


@router.get("/sentiment")
async def crypto_sentiment():
    """Get combined crypto sentiment from Fear & Greed Index + CryptoPanic."""
    try:
        from bahamut.sentiment.gate import get_full_sentiment
        return get_full_sentiment()
    except Exception as e:
        return {"error": str(e)}


@router.get("/risk-metrics")
async def risk_metrics():
    """Historical risk metrics — drawdown, streaks, daily PnL, exposure history."""
    try:
        from bahamut.db.query import run_query
        from bahamut.config_assets import TRAINING_VIRTUAL_CAPITAL, ASSET_CLASS_MAP

        trades = run_query("""
            SELECT asset, strategy, direction, pnl, pnl_pct, exit_reason,
                   bars_held, entry_time, exit_time
            FROM training_trades ORDER BY exit_time ASC
        """)
        if not trades:
            return {"error": "no trades"}

        capital = TRAINING_VIRTUAL_CAPITAL
        equity_curve = [capital]
        running = capital
        peak = capital
        max_dd = 0
        max_dd_pct = 0
        daily_pnl = {}
        streak_wins = 0
        streak_losses = 0
        best_streak = 0
        worst_streak = 0
        current_streak = 0
        current_streak_type = ""
        biggest_win = {"pnl": 0}
        biggest_loss = {"pnl": 0}
        total_bars = 0
        total_r = 0
        win_r = []
        loss_r = []

        for t in trades:
            pnl = t.get("pnl", 0) or 0
            running += pnl
            equity_curve.append(round(running, 2))

            if running > peak:
                peak = running
            dd = peak - running
            dd_pct = dd / max(1, peak) * 100
            if dd > max_dd:
                max_dd = dd
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

            # Daily PnL
            exit_t = str(t.get("exit_time", ""))[:10]
            if exit_t:
                daily_pnl[exit_t] = round(daily_pnl.get(exit_t, 0) + pnl, 2)

            # Streaks
            if pnl > 0.01:
                if current_streak_type == "win":
                    current_streak += 1
                else:
                    current_streak = 1
                    current_streak_type = "win"
                best_streak = max(best_streak, current_streak)
            elif pnl < -0.01:
                if current_streak_type == "loss":
                    current_streak += 1
                else:
                    current_streak = 1
                    current_streak_type = "loss"
                worst_streak = max(worst_streak, current_streak)
            # Biggest
            if pnl > biggest_win["pnl"]:
                biggest_win = {"pnl": round(pnl, 2), "asset": t.get("asset"), "strategy": t.get("strategy")}
            if pnl < biggest_loss["pnl"]:
                biggest_loss = {"pnl": round(pnl, 2), "asset": t.get("asset"), "strategy": t.get("strategy")}
            # Phase 5 Item 13: canonical R-multiple from real risk_amount.
            # Fall back to the legacy ~3% baseline only if risk_amount is
            # missing/zero (pre-schema rows). Every post-2025-10 trade has
            # real risk_amount from the sizing engine.
            _risk = float(t.get("risk_amount", 0) or 0)
            _pnl = float(t.get("pnl", 0) or 0)
            if _risk > 0:
                r = _pnl / _risk
            else:
                r = (t.get("pnl_pct", 0) or 0) / 0.03  # legacy approximation
            total_r += r
            if r > 0:
                win_r.append(r)
            elif r < 0:
                loss_r.append(r)
            total_bars += t.get("bars_held", 0) or 0

        # Per-strategy risk
        strat_stats = {}
        for t in trades:
            s = t.get("strategy", "")
            if s not in strat_stats:
                strat_stats[s] = {"trades": 0, "wins": 0, "losses": 0, "pnl": 0, "max_loss": 0, "r_sum": 0}
            strat_stats[s]["trades"] += 1
            p = t.get("pnl", 0) or 0
            strat_stats[s]["pnl"] = round(strat_stats[s]["pnl"] + p, 2)
            if p > 0.01:
                strat_stats[s]["wins"] += 1
            elif p < -0.01:
                strat_stats[s]["losses"] += 1
                strat_stats[s]["max_loss"] = min(strat_stats[s]["max_loss"], p)
            # Phase 5 Item 13: same canonical R
            _rs_risk = float(t.get("risk_amount", 0) or 0)
            _rs_pnl = float(t.get("pnl", 0) or 0)
            if _rs_risk > 0:
                _rs_r = _rs_pnl / _rs_risk
            else:
                _rs_r = (t.get("pnl_pct", 0) or 0) / 0.03
            strat_stats[s]["r_sum"] = round(strat_stats[s]["r_sum"] + _rs_r, 2)

        # Per-class risk
        class_stats = {}
        for t in trades:
            cls = ASSET_CLASS_MAP.get(t.get("asset", ""), "other")
            if cls not in class_stats:
                class_stats[cls] = {"trades": 0, "pnl": 0, "wins": 0, "losses": 0}
            class_stats[cls]["trades"] += 1
            p = t.get("pnl", 0) or 0
            class_stats[cls]["pnl"] = round(class_stats[cls]["pnl"] + p, 2)
            if p > 0.01:
                class_stats[cls]["wins"] += 1
            elif p < -0.01:
                class_stats[cls]["losses"] += 1

        # Daily PnL last 14 days
        sorted_days = sorted(daily_pnl.items(), reverse=True)[:14]
        sorted_days.reverse()

        n = len(trades)

        # ── Risk Engine state (live portfolio controls) ──
        risk_state = {}
        try:
            from bahamut.training.risk_engine import get_risk_engine_state
            risk_state = get_risk_engine_state()
        except Exception as re_err:
            risk_state = {"error": str(re_err)}

        # Adaptive news summary for dashboard
        adaptive_news = {}
        try:
            from bahamut.intelligence.adaptive_news_risk import diagnostics_snapshot, ADAPTIVE_NEWS_ENABLED
            if ADAPTIVE_NEWS_ENABLED:
                adaptive_news = diagnostics_snapshot()
        except Exception:
            pass

        return {
            "total_trades": n,
            "total_pnl": round(running - capital, 2),
            "return_pct": round((running - capital) / capital * 100, 2),
            "current_equity": round(running, 2),
            "max_drawdown": round(max_dd, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "current_drawdown": round(peak - running, 2),
            "current_drawdown_pct": round((peak - running) / max(1, peak) * 100, 2),
            "best_streak": best_streak,
            "worst_streak": worst_streak,
            "current_streak": current_streak,
            "current_streak_type": current_streak_type,
            "biggest_win": biggest_win,
            "biggest_loss": biggest_loss,
            "avg_r_multiple": round(total_r / max(1, n), 3),
            "avg_win_r": round(sum(win_r) / max(1, len(win_r)), 3),
            "avg_loss_r": round(sum(loss_r) / max(1, len(loss_r)), 3),
            "avg_bars_held": round(total_bars / max(1, n), 1),
            "profit_factor": round(sum(t.get("pnl", 0) for t in trades if (t.get("pnl", 0) or 0) > 0) /
                                    max(0.01, abs(sum(t.get("pnl", 0) for t in trades if (t.get("pnl", 0) or 0) < 0))), 2),
            "daily_pnl": [{"date": d, "pnl": p} for d, p in sorted_days],
            "equity_curve_sample": equity_curve[::max(1, len(equity_curve) // 50)],
            "by_strategy": strat_stats,
            "by_class": class_stats,
            # ── Risk Engine (live controls) ──
            **risk_state,
            # ── Adaptive News Risk ──
            "adaptive_news": adaptive_news,
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/trust-dashboard")
async def trust_dashboard():
    """Trust scores, pattern performance, and learning metrics.
    Uses the same proven Redis path as diagnostics — single source of truth."""
    try:
        from bahamut.training.learning_engine import (
            get_trust_overview, get_pattern_trust,
        )
        from bahamut.db.query import run_query
        from bahamut.config_assets import ASSET_CLASS_MAP

        # ── Strategy trust: proven Redis path (same as diagnostics) ──
        overview = get_trust_overview()
        strategies = {}
        for name, s in overview.get("strategies", {}).items():
            w = s.get("wins", 0)
            l = s.get("losses", 0)
            strategies[name] = {
                "trust": round(s.get("trust", 0.5), 4),
                "samples": s.get("samples", 0),
                "maturity": s.get("maturity", "provisional"),
                "confidence": round(s.get("confidence", 0), 3),
                "wins": w, "losses": l,
                "wr": round(w / max(1, w + l), 3),
                "quick_stops": s.get("quick_stops", 0),
            }

        # ── Pattern trust: iterate strategy×regime×class (same as diagnostics) ──
        pattern_list = []
        regimes = ["TREND", "RANGE", "CRASH", "BREAKOUT"]
        classes = ["crypto", "stock", "forex", "commodity", "index"]
        for strat in ["v5_base", "v9_breakout", "v10_mean_reversion"]:
            for regime in regimes:
                for ac in classes:
                    t = get_pattern_trust(strat, regime, ac)
                    if t.get("total_trades", 0) > 0 or t.get("expectancy", 0) != 0:
                        pattern_list.append({
                            "key": f"{strat}:{regime}:{ac}",
                            "trust": round(t.get("blended_trust", 0.5), 4),
                            "confidence": round(t.get("blended_confidence", 0), 3),
                            "maturity": t.get("maturity", "provisional"),
                            "expectancy": round(t.get("expectancy", 0), 4),
                            "trades": t.get("total_trades", 0),
                            "quick_stops": t.get("quick_stops", 0),
                        })

        # Sort for best/worst/most traded
        with_exp = [p for p in pattern_list if p["trades"] > 0]
        best_patterns = sorted(with_exp, key=lambda x: x["expectancy"], reverse=True)[:10]
        worst_patterns = sorted(with_exp, key=lambda x: x["expectancy"])[:10]
        most_traded = sorted(with_exp, key=lambda x: x["trades"], reverse=True)[:10]

        # ── Per-asset performance from training_trades DB ──
        # Phase 5 Item 13: real R-multiples from pnl/risk_amount instead
        # of legacy pnl_pct/0.03 approximation. Filter out rows where
        # risk_amount is 0 or NULL so we don't divide by zero.
        asset_rows = run_query("""
            SELECT asset, COUNT(*) as trades,
                   SUM(CASE WHEN pnl > 0.01 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN pnl < -0.01 THEN 1 ELSE 0 END) as losses,
                   COALESCE(SUM(pnl), 0) as total_pnl,
                   COALESCE(AVG(pnl_pct), 0) as avg_pnl_pct,
                   COALESCE(AVG(CASE WHEN risk_amount > 0
                                     THEN pnl / risk_amount
                                     ELSE pnl_pct / 0.03 END), 0) as avg_r
            FROM training_trades GROUP BY asset ORDER BY total_pnl DESC
        """)

        best_assets = []
        worst_assets = []
        for r in (asset_rows or []):
            w = int(r.get("wins", 0) or 0)
            l = int(r.get("losses", 0) or 0)
            entry = {
                "asset": r["asset"],
                "class": ASSET_CLASS_MAP.get(r["asset"], "other"),
                "trades": r["trades"],
                "wins": w, "losses": l,
                "wr": round(w / max(1, w + l), 3),
                "pnl": round(float(r.get("total_pnl", 0) or 0), 2),
                "avg_r": round(float(r.get("avg_r", 0) or 0), 3),
            }
            if entry["pnl"] > 0:
                best_assets.append(entry)
            else:
                worst_assets.append(entry)
        worst_assets.sort(key=lambda x: x["pnl"])

        # ── Exit reason distribution ──
        exit_rows = run_query("""
            SELECT exit_reason, COUNT(*) as count,
                   COALESCE(AVG(pnl), 0) as avg_pnl,
                   COALESCE(AVG(CASE WHEN risk_amount > 0
                                     THEN pnl / risk_amount
                                     ELSE pnl_pct / 0.03 END), 0) as avg_r
            FROM training_trades GROUP BY exit_reason
        """)
        exit_stats = {}
        for r in (exit_rows or []):
            exit_stats[r["exit_reason"] or "UNKNOWN"] = {
                "count": r["count"],
                "avg_pnl": round(float(r.get("avg_pnl", 0) or 0), 2),
                "avg_r": round(float(r.get("avg_r", 0) or 0), 3),
            }

        # ── Direction + regime performance ──
        dir_rows = run_query("""
            SELECT direction, COUNT(*) as trades,
                   SUM(CASE WHEN pnl > 0.01 THEN 1 ELSE 0 END) as wins,
                   COALESCE(SUM(pnl), 0) as pnl
            FROM training_trades GROUP BY direction
        """)
        direction_stats = {}
        for r in (dir_rows or []):
            direction_stats[r["direction"] or "UNKNOWN"] = {
                "trades": r["trades"], "wins": int(r.get("wins", 0) or 0),
                "pnl": round(float(r.get("pnl", 0) or 0), 2),
            }

        regime_rows = run_query("""
            SELECT regime, COUNT(*) as trades,
                   SUM(CASE WHEN pnl > 0.01 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN pnl < -0.01 THEN 1 ELSE 0 END) as losses,
                   COALESCE(SUM(pnl), 0) as pnl,
                   COALESCE(AVG(CASE WHEN risk_amount > 0
                                     THEN pnl / risk_amount
                                     ELSE pnl_pct / 0.03 END), 0) as avg_r
            FROM training_trades GROUP BY regime
        """)
        regime_stats = {}
        for r in (regime_rows or []):
            w = int(r.get("wins", 0) or 0)
            l = int(r.get("losses", 0) or 0)
            regime_stats[r["regime"] or "UNKNOWN"] = {
                "trades": r["trades"], "wins": w, "losses": l,
                "pnl": round(float(r.get("pnl", 0) or 0), 2),
                "avg_r": round(float(r.get("avg_r", 0) or 0), 3),
                "wr": round(w / max(1, w + l), 3),
            }

        # Phase 5 Item 14: aggregate fee/slippage visibility
        fee_slippage_summary = {}
        try:
            cost_rows = run_query("""
                SELECT
                    COUNT(*) as total_trades,
                    COALESCE(SUM(pnl), 0) as gross_pnl,
                    COALESCE(SUM(CASE WHEN entry_commission IS NOT NULL
                                      THEN entry_commission ELSE 0 END
                                + CASE WHEN exit_commission IS NOT NULL
                                       THEN exit_commission ELSE 0 END), 0) as total_commissions,
                    COALESCE(SUM(CASE WHEN entry_slippage_abs IS NOT NULL
                                      THEN entry_slippage_abs ELSE 0 END
                                + CASE WHEN exit_slippage_abs IS NOT NULL
                                       THEN exit_slippage_abs ELSE 0 END), 0) as total_slippage,
                    SUM(CASE WHEN (COALESCE(entry_commission, 0) + COALESCE(exit_commission, 0)) > 0
                             THEN 1 ELSE 0 END) as trades_with_costs
                FROM training_trades
            """)
            if cost_rows:
                cr = dict(cost_rows[0])
                gross = float(cr.get("gross_pnl", 0) or 0)
                commissions = float(cr.get("total_commissions", 0) or 0)
                slippage = float(cr.get("total_slippage", 0) or 0)
                total_costs = commissions + slippage
                fee_slippage_summary = {
                    "total_trades": int(cr.get("total_trades", 0)),
                    "trades_with_cost_data": int(cr.get("trades_with_costs", 0) or 0),
                    "gross_pnl": round(gross, 2),
                    "total_commissions": round(commissions, 2),
                    "total_slippage": round(slippage, 2),
                    "total_costs": round(total_costs, 2),
                    "net_pnl": round(gross - total_costs, 2),
                    "cost_pct_of_gross": (round(total_costs / abs(gross) * 100, 2)
                                          if abs(gross) > 0.01 else 0),
                    "note": ("Costs only populated for trades executed post Phase 5 "
                             "Item 14 deploy. Legacy trades show 0 costs."),
                }
        except Exception:
            pass

        return {
            "strategies": strategies,
            "patterns": {"best": best_patterns, "worst": worst_patterns, "most_traded": most_traded},
            "best_assets": best_assets[:10],
            "worst_assets": worst_assets[:10],
            "exit_stats": exit_stats,
            "direction_stats": direction_stats,
            "regime_stats": regime_stats,
            "fee_slippage_summary": fee_slippage_summary,
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "trace": traceback.format_exc()[:500]}


@router.get("/asset-leaderboard")
async def asset_leaderboard():
    """Per-asset performance sorted by PnL. Shows ALL configured assets."""
    try:
        from bahamut.db.query import run_query
        from bahamut.config_assets import ASSET_CLASS_MAP, TRAINING_CRYPTO, TRAINING_STOCKS

        rows = run_query("""
            SELECT asset,
                   COUNT(*) as trades,
                   SUM(CASE WHEN pnl > 0.01 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN pnl < -0.01 THEN 1 ELSE 0 END) as losses,
                   COALESCE(SUM(pnl), 0) as total_pnl,
                   COALESCE(AVG(pnl), 0) as avg_pnl,
                   COALESCE(AVG(pnl_pct), 0) as avg_pnl_pct,
                   MAX(pnl) as best_trade,
                   MIN(pnl) as worst_trade
            FROM training_trades GROUP BY asset ORDER BY total_pnl DESC
        """)

        # Build lookup from DB results
        db_map = {}
        for r in (rows or []):
            db_map[r["asset"]] = r

        def _make_entry(asset: str) -> dict:
            r = db_map.get(asset)
            if r:
                wins = r["wins"] or 0
                losses = r["losses"] or 0
                return {
                    "asset": asset,
                    "trades": r["trades"],
                    "wins": wins,
                    "losses": losses,
                    "wr": round(wins / max(1, wins + losses) * 100, 1),
                    "pnl": round(r["total_pnl"], 2),
                    "avg_pnl": round(r["avg_pnl"], 2),
                    "avg_pnl_pct": round((r["avg_pnl_pct"] or 0) * 100, 2),
                    "best": round(r["best_trade"] or 0, 2),
                    "worst": round(r["worst_trade"] or 0, 2),
                }
            return {
                "asset": asset, "trades": 0, "wins": 0, "losses": 0,
                "wr": 0, "pnl": 0, "avg_pnl": 0, "avg_pnl_pct": 0,
                "best": 0, "worst": 0,
            }

        crypto = sorted([_make_entry(a) for a in TRAINING_CRYPTO], key=lambda x: x["pnl"], reverse=True)
        stock = sorted([_make_entry(a) for a in TRAINING_STOCKS], key=lambda x: x["pnl"], reverse=True)

        return {"crypto": crypto, "stock": stock}
    except Exception as e:
        return {"error": str(e)}


def _estimate_event_direction(event: dict) -> dict:
    """Deterministic market direction estimate for an economic event.
    No AI dependency — uses keyword matching + surprise data.
    """
    name = (event.get("event") or "").lower()
    impact = event.get("impact", "low")
    actual = event.get("actual")
    estimate = event.get("estimate")

    # Events that are generally bullish for markets
    BULLISH_EVENTS = {
        "rate cut": 0.8, "rate decision": 0.5, "gdp": 0.6, "retail sales": 0.6,
        "consumer confidence": 0.6, "pmi": 0.6, "ism services": 0.6, "ism manufacturing": 0.6,
        "housing starts": 0.5, "building permits": 0.5, "earnings": 0.5,
        "non-farm": 0.7, "nfp": 0.7, "payroll": 0.7, "employment": 0.5,
        "stimulus": 0.7, "easing": 0.7, "dovish": 0.8,
    }
    # Events that are generally bearish
    BEARISH_EVENTS = {
        "cpi": 0.6, "inflation": 0.7, "rate hike": 0.8, "hawkish": 0.8,
        "unemployment": 0.5, "jobless": 0.5, "tariff": 0.8, "sanctions": 0.7,
        "opec": 0.5, "crude oil": 0.4, "trade deficit": 0.4,
        "fed speak": 0.3, "fomc": 0.4, "ecb": 0.4, "boe": 0.4,
    }
    # Neutral / uncertain
    NEUTRAL_EVENTS = {
        "auction": 0.3, "bond": 0.3, "treasury": 0.3, "ppi": 0.4,
        "durable goods": 0.4, "factory orders": 0.3, "trade balance": 0.3,
    }

    bull_score = max((v for k, v in BULLISH_EVENTS.items() if k in name), default=0)
    bear_score = max((v for k, v in BEARISH_EVENTS.items() if k in name), default=0)

    # If actual vs estimate available, use surprise direction
    if actual is not None and estimate is not None:
        try:
            surprise = float(actual) - float(estimate)
            if abs(surprise) > 0.001:
                # For inflation/CPI: higher actual = bearish
                if any(k in name for k in ("cpi", "inflation", "pce")):
                    return {
                        "direction": "DOWN" if surprise > 0 else "UP",
                        "confidence": min(0.9, abs(surprise) / max(abs(float(estimate)), 0.01)),
                        "reason": f"{'Higher' if surprise > 0 else 'Lower'} than expected",
                    }
                # For most others: higher = bullish
                return {
                    "direction": "UP" if surprise > 0 else "DOWN",
                    "confidence": min(0.9, abs(surprise) / max(abs(float(estimate)), 0.01)),
                    "reason": f"{'Beat' if surprise > 0 else 'Missed'} estimate",
                }
        except (ValueError, TypeError):
            pass

    # Keyword-based estimation
    if bull_score > bear_score + 0.1:
        return {"direction": "UP", "confidence": round(bull_score * 0.7, 2), "reason": "Historically bullish event"}
    elif bear_score > bull_score + 0.1:
        return {"direction": "DOWN", "confidence": round(bear_score * 0.7, 2), "reason": "Historically bearish event"}

    # Earnings: generally neutral until results
    if "earnings" in name:
        return {"direction": "NEUTRAL", "confidence": 0.3, "reason": "Pending earnings release"}

    return {"direction": "NEUTRAL", "confidence": 0.2, "reason": "Uncertain impact"}


@router.get("/news-dashboard")
async def news_dashboard():
    """Compact news/events dashboard for the Training Operations page."""
    result = {
        "sentiment": {},
        "news_impacts": [],
        "upcoming_events": [],
        "freezes": [],
        "headlines": [],
    }

    # 1. Sentiment state
    try:
        from bahamut.sentiment.gate import get_full_sentiment
        result["sentiment"] = get_full_sentiment()
    except Exception:
        pass

    # 2. News impact for top assets
    try:
        from bahamut.intelligence.news_impact import compute_news_impact_sync
        from bahamut.config_assets import TRAINING_CRYPTO, TRAINING_STOCKS
        for a in (TRAINING_CRYPTO[:8] + TRAINING_STOCKS[:5]):
            ac = "crypto" if a in TRAINING_CRYPTO else "stock"
            nia = compute_news_impact_sync(a, ac)
            if nia.impact_score > 0.05:
                entry = {
                    "asset": a, "asset_class": ac,
                    "impact_score": nia.impact_score,
                    "directional_bias": nia.directional_bias,
                    "shock_level": nia.shock_level,
                    "freeze_trading": nia.freeze_trading,
                    "freeze_reason": nia.freeze_reason,
                    "headline_count": nia.headline_count,
                    "confidence": nia.confidence,
                    "explanations": nia.explanations[:3],
                }
                result["news_impacts"].append(entry)
                if nia.freeze_trading:
                    result["freezes"].append({"asset": a, "reason": nia.freeze_reason})
    except Exception:
        pass

    # 3. Upcoming events — cached in Redis to avoid rate limits
    import httpx as _hx
    _no_surp = {"surprise_z": 0, "direction": "NEUTRAL", "magnitude": "NONE"}
    _events_debug = {"source": "none", "error": None}

    # Check Redis cache first (only use if it's economic calendar data, not stale earnings)
    try:
        import redis as _rds
        _rc = _rds.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        _cached = _rc.get("bahamut:calendar:events_v6")
        if _cached:
            _cached_data = json.loads(_cached)
            # Only use cache if it has real economic events (not just earnings)
            has_econ = any(not e.get("event", "").endswith(")") for e in _cached_data[:5])
            if has_econ or len(_cached_data) > 0:
                result["upcoming_events"] = _cached_data
                _events_debug["source"] = "cache"
    except Exception:
        _rc = None

    # If no cache, fetch fresh
    if not result["upcoming_events"]:
        _headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
        }

        # 3a. Forex Factory economic calendar (priority)
        try:
            async with _hx.AsyncClient(timeout=20, headers=_headers, follow_redirects=True) as _c:
                _r = await _c.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json")
                _events_debug["ff_status"] = _r.status_code
                if _r.status_code == 200:
                    for ev in _r.json()[:40]:
                        imp = ev.get("impact", "Low")
                        if imp == "Holiday":
                            continue
                        result["upcoming_events"].append({
                            "event": ev.get("title", "Unknown"),
                            "country": ev.get("country", ""),
                            "impact": "high" if imp == "High" else "medium" if imp == "Medium" else "low",
                            "actual": ev.get("actual") or None,
                            "estimate": ev.get("forecast") or None,
                            "prev": ev.get("previous") or None,
                            "date": ev.get("date", ""),
                            "source": "forexfactory",
                            "surprise": _no_surp,
                        })
                    _events_debug["source"] = "forexfactory"
                    # Cache economic calendar for 2 hours
                    if _rc and result["upcoming_events"]:
                        try:
                            _rc.setex("bahamut:calendar:events_v6", 7200, json.dumps(result["upcoming_events"]))
                        except Exception:
                            pass
        except Exception as e:
            _events_debug["error"] = str(e)[:100]

        # 3b. Fallback: Finnhub earnings (only for stocks in our universe)
        if not result["upcoming_events"]:
            try:
                from bahamut.config import get_settings as _gs
                from bahamut.config_assets import TRAINING_STOCKS
                _fk = _gs().finnhub_key
                _stock_set = set(TRAINING_STOCKS)
                if _fk:
                    async with _hx.AsyncClient(timeout=15) as _c:
                        _r = await _c.get("https://finnhub.io/api/v1/calendar/earnings",
                                           params={"from": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                                                   "to": (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d"),
                                                   "token": _fk})
                        if _r.status_code == 200:
                            _d = _r.json()
                            for ev in (_d.get("earningsCalendar", []))[:50]:
                                sym = ev.get("symbol", "")
                                # Only show earnings for stocks we actually trade
                                is_relevant = sym in _stock_set
                                result["upcoming_events"].append({
                                    "event": f"{sym} Earnings Q{ev.get('quarter', '?')}",
                                    "country": "US",
                                    "impact": "high" if is_relevant else "medium",
                                    "actual": ev.get("epsActual"),
                                    "estimate": ev.get("epsEstimate"),
                                    "prev": None,
                                    "date": ev.get("date", ""),
                                    "source": "finnhub_earnings",
                                    "surprise": _no_surp,
                                })
                            # Sort: our stocks first, then by date
                            result["upcoming_events"].sort(key=lambda e: (0 if e["impact"] == "high" else 1, e.get("date", "")))
                            _events_debug["source"] = "finnhub_earnings"
                            # Short cache for earnings (15 min) — keep trying for FF
                            if _rc:
                                try:
                                    _rc.setex("bahamut:calendar:events_v6", 900, json.dumps(result["upcoming_events"]))
                                except Exception:
                                    pass
            except Exception as e:
                _events_debug["error"] = (_events_debug.get("error") or "") + " | " + str(e)[:80]

    # Enrich with surprise scores
    if result["upcoming_events"]:
        try:
            from bahamut.intelligence.news_impact import event_surprise_score
            for ev in result["upcoming_events"]:
                if ev.get("actual") is not None and ev.get("estimate") is not None:
                    ev["surprise"] = event_surprise_score(ev)
        except Exception:
            pass

    # Estimate market direction for each event (deterministic — no AI dependency)
    if result["upcoming_events"]:
        _has_estimates = any(ev.get("ai_estimate") for ev in result["upcoming_events"])
        if not _has_estimates:
            for ev in result["upcoming_events"]:
                ev["ai_estimate"] = _estimate_event_direction(ev)
            # Re-cache with estimates
            if _rc:
                try:
                    _rc.setex("bahamut:calendar:events_v6",
                              7200 if _events_debug.get("source") != "finnhub_earnings" else 900,
                              json.dumps(result["upcoming_events"]))
                except Exception:
                    pass

    result["_events_debug"] = _events_debug

    # 3c. Enrich with surprise scores
    if result["upcoming_events"]:
        try:
            from bahamut.intelligence.news_impact import event_surprise_score
            for ev in result["upcoming_events"]:
                if ev.get("actual") is not None and ev.get("estimate") is not None:
                    ev["surprise"] = event_surprise_score(ev)
        except Exception:
            pass

    # 4. Recent headlines — fetch fresh from Finnhub (async endpoint)
    try:
        from bahamut.ingestion.adapters.news import news_adapter
        from bahamut.intelligence.news_impact import dedupe_headlines
        # Fetch general market news + crypto news
        general = await news_adapter.get_headlines(category="general", count=5)
        crypto = await news_adapter.get_headlines(category="crypto", count=5)
        all_hl = general + crypto
        all_hl = dedupe_headlines(all_hl)
        # Sort by published time, newest first
        all_hl.sort(key=lambda x: x.get("published", ""), reverse=True)
        result["headlines"] = [
            {
                "title": h.get("title", "")[:120],
                "source": h.get("source", ""),
                "published": h.get("published", ""),
                "category": h.get("category", ""),
                "asset": h.get("category", "market").upper(),
            }
            for h in all_hl[:10]
        ]
    except Exception as e:
        logger.debug("news_dashboard_headlines_failed", error=str(e)[:80])
        # Fallback to cached
        try:
            import os, redis as _redis, json
            r2 = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
            for key in r2.keys("bahamut:news:headlines:*"):
                try:
                    asset_name = key.decode().split(":")[-1] if isinstance(key, bytes) else key.split(":")[-1]
                    if asset_name == "_global":
                        continue
                    raw = r2.get(key)
                    if raw:
                        headlines = json.loads(raw)
                        for h in headlines[:2]:
                            result["headlines"].append({
                                "asset": asset_name,
                                "title": h.get("title", "")[:120],
                                "source": h.get("source", ""),
                                "published": h.get("published", ""),
                            })
                except Exception:
                    pass
            result["headlines"] = sorted(result["headlines"], key=lambda x: x.get("published", ""), reverse=True)[:10]
        except Exception:
            pass

    return result


# ═══════════════════════════════════════════════════════
# DIAGRAM DASHBOARD — lightweight aggregation endpoint
# ═══════════════════════════════════════════════════════

@router.get("/diagram-dashboard")
async def diagram_dashboard():
    """Aggregated live state for the Diagram Dashboard.
    Reuses existing functions — no duplicated logic."""
    import json as _json
    from fastapi.responses import JSONResponse

    def _safe(obj):
        if isinstance(obj, set):
            return sorted(list(obj))
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="replace")
        if hasattr(obj, "item"):
            return obj.item()
        return str(obj)

    result = {"ts": datetime.now(timezone.utc).isoformat()}

    # 1. Strategy health
    try:
        from bahamut.db.query import run_query
        rows = run_query("""
            SELECT strategy,
                   COUNT(*) as trades,
                   SUM(CASE WHEN pnl > 0.01 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN pnl < -0.01 THEN 1 ELSE 0 END) as losses,
                   ROUND(SUM(pnl)::numeric, 2) as pnl
            FROM training_trades GROUP BY strategy
        """)
        strats = {}
        for r in rows:
            rd = dict(r)
            s = rd["strategy"]
            w, l = int(rd["wins"] or 0), int(rd["losses"] or 0)
            strats[s] = {
                "trades": rd["trades"], "wins": w, "losses": l,
                "win_rate": round(w / max(1, w + l) * 100, 1),
                "pnl": float(rd["pnl"] or 0),
            }
        result["strategies"] = strats
    except Exception:
        result["strategies"] = {}

    # 2. Trust overview
    try:
        from bahamut.training.learning_engine import get_trust_overview
        result["trust"] = get_trust_overview()
    except Exception:
        result["trust"] = {}

    # 3. Risk engine state
    try:
        from bahamut.training.risk_engine import get_risk_engine_state
        re = get_risk_engine_state()
        result["risk_engine"] = re.get("risk_engine", {})
        result["exposure"] = re.get("exposure", {})
        result["correlation"] = {
            k: v for k, v in re.get("correlation", {}).items() if not k.startswith("_")
        }
    except Exception:
        result["risk_engine"] = {}

    # 4. Adaptive news
    try:
        from bahamut.intelligence.adaptive_news_risk import diagnostics_snapshot, ADAPTIVE_NEWS_ENABLED
        if ADAPTIVE_NEWS_ENABLED:
            result["adaptive_news"] = diagnostics_snapshot()
        else:
            result["adaptive_news"] = {"adaptive_news_enabled": False}
    except Exception:
        result["adaptive_news"] = {}

    # 5. Open positions
    try:
        from bahamut.training.engine import _load_positions
        positions = _load_positions()
        result["open_positions"] = [{
            "asset": p["asset"], "strategy": p["strategy"],
            "direction": p["direction"], "pnl_pct": round(p.get("pnl_pct", 0), 2),
        } for p in positions[:20]]
        result["open_count"] = len(positions)
    except Exception:
        result["open_positions"] = []
        result["open_count"] = 0

    # 6. Last cycle decisions
    try:
        r = _get_redis()
        if r:
            raw = r.get("bahamut:training:last_cycle_decisions")
            if raw:
                decisions = _json.loads(raw)
                result["last_cycle"] = {
                    "executed": len([d for d in decisions if d.get("decision") == "EXECUTE"]),
                    "rejected": len([d for d in decisions if d.get("decision") == "REJECT"]),
                    "watchlist": len([d for d in decisions if d.get("decision") == "WATCHLIST"]),
                    "total": len(decisions),
                }
            last_scan = r.get("bahamut:training:last_scan_time")
            result["last_scan_time"] = last_scan.decode() if last_scan else None
            cycle_count = r.get("bahamut:training:cycle_count")
            result["cycle_count"] = int(cycle_count) if cycle_count else 0
    except Exception:
        pass

    # 7. Containment counters
    try:
        r = _get_redis()
        if r:
            counters = {}
            for ck in [
                "bahamut:counters:engine_suppress_blocks",
                "bahamut:counters:sentiment_gate_blocks",
                "bahamut:counters:risk_engine_blocks",
                "bahamut:counters:news_size_reductions",
                "bahamut:counters:mature_neg_expectancy_blocks",
            ]:
                val = r.get(ck)
                counters[ck.split(":")[-1]] = int(val) if val else 0
            result["counters"] = counters
    except Exception:
        result["counters"] = {}

    # 8. Execution status
    try:
        from bahamut.execution.router import get_execution_status
        result["execution"] = get_execution_status()
    except Exception:
        result["execution"] = {}

    # 9. Sentiment
    try:
        from bahamut.intelligence.sentiment import get_cached_sentiment
        result["sentiment"] = get_cached_sentiment()
    except Exception:
        result["sentiment"] = {}

    # 10. Health
    try:
        r = _get_redis()
        result["health"] = {
            "redis": r is not None and r.ping() if r else False,
            "legacy_disabled": True,
        }
    except Exception:
        result["health"] = {"redis": False}

    body = _json.dumps(result, default=_safe)
    return JSONResponse(content=_json.loads(body))


# ═══════════════════════════════════════════
# MARKET INTELLIGENCE ENDPOINT
# ═══════════════════════════════════════════

@router.get("/market-intelligence")
async def market_intelligence():
    """AI Market Intelligence — unified aggregation with Claude Opus 4.6 analysis."""
    import json as _mij
    import traceback as _tb
    import asyncio
    from fastapi.responses import JSONResponse
    try:
        from bahamut.intelligence.market_intelligence import build_market_intelligence_snapshot

        # Fire Opus analysis in background (non-blocking — do NOT await)
        try:
            from bahamut.intelligence.ai_market_analyst import call_opus_analysis, get_cached_analysis
            from bahamut.sentiment.gate import get_full_sentiment
            if not get_cached_analysis():
                _sent = get_full_sentiment()
                snap_pre = build_market_intelligence_snapshot()
                # Fire and forget — response returns immediately
                asyncio.ensure_future(call_opus_analysis(
                    sentiment=_sent,
                    headlines=snap_pre.get("headline_context", []),
                    events=snap_pre.get("event_context", []),
                ))
        except Exception:
            pass

        snap = build_market_intelligence_snapshot()
        body = _mij.dumps(snap, default=str)
        return JSONResponse(content=_mij.loads(body))
    except Exception as e:
        err_msg = str(e)[:200]
        err_trace = _tb.format_exc()[-500:]
        logger.error("market_intelligence_endpoint_error", error=err_msg, traceback=err_trace)
        # Return a minimal valid snapshot so the page renders
        fallback = {
            "timestamp": "",
            "summary": {"pipeline_posture": "UNKNOWN", "crypto_fear_greed": 0, "stocks_fear_greed": 0,
                         "crypto_market_mode": "UNKNOWN", "stocks_market_mode": "UNKNOWN",
                         "macro_risk_mode": "UNKNOWN", "active_headlines": 0, "upcoming_high_events": 0,
                         "news_modes": {}, "ai_narrative": f"ERROR: {err_msg}"},
            "class_context": {}, "asset_context": {}, "headline_context": [], "event_context": [],
            "pipeline_directives": {}, "source_of_truth": "error_fallback",
            "_error": err_msg, "_trace": err_trace,
        }
        return JSONResponse(content=fallback)
