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
                   SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN pnl < -0.01 THEN 1 ELSE 0 END) as losses,
                   COALESCE(SUM(pnl), 0) as total_pnl,
                   COALESCE(AVG(pnl), 0) as avg_pnl,
                   COALESCE(AVG(bars_held), 0) as avg_bars,
                   COALESCE(SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END), 0) as gp,
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
                    result["by_strategy"][s] = {"cnt": 0, "wins": 0, "losses": 0, "pnl": 0, "avg_pnl": 0, "avg_bars": 0, "gp": 0, "gl": 0}
                bs = result["by_strategy"][s]
                bs["cnt"] += cnt; bs["wins"] += wins; bs["losses"] += losses; bs["pnl"] += pnl; bs["gp"] += gp; bs["gl"] += gl

                if c not in result["by_class"]:
                    result["by_class"][c] = {"cnt": 0, "wins": 0, "losses": 0, "pnl": 0}
                bc = result["by_class"][c]
                bc["cnt"] += cnt; bc["wins"] += wins; bc["losses"] += losses; bc["pnl"] += pnl

            # Compute averages for strategies
            for s, bs in result["by_strategy"].items():
                bs["avg_pnl"] = bs["pnl"] / max(1, bs["cnt"])
                bs["avg_bars"] = total_bars / max(1, total_cnt) if total_cnt else 0

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
    for strat in ["v5_base", "v5_tuned", "v9_breakout", "v10_mean_reversion"]:
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
    for strat in ["v5_base", "v5_tuned", "v9_breakout", "v10_mean_reversion"]:
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
                       SUM(CASE WHEN pnl < -0.01 THEN 1 ELSE 0 END) as losses,
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
                       SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
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
    """Structured diagnostic logs for AI analysis.

    Returns comprehensive system state formatted for copy-paste into
    Claude for debugging and accuracy improvement.
    """
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
        for strat in ["v5_base", "v5_tuned", "v9_breakout", "v10_mean_reversion"]:
            for regime in ["TREND", "RANGE", "BREAKOUT"]:
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

    # ── 3. STRATEGY PERFORMANCE ──
    perf_section = {"title": "STRATEGY PERFORMANCE", "rows": []}
    try:
        if r:
            for strat in ["v5_base", "v5_tuned", "v9_breakout", "v10_mean_reversion"]:
                raw = r.get(f"bahamut:training:strategy_stats:{strat}")
                if raw:
                    s = json.loads(raw)
                    perf_section["rows"].append({
                        "strategy": strat,
                        "trades": s.get("trades", 0),
                        "wins": s.get("wins", 0),
                        "losses": s.get("losses", 0),
                        "win_rate": s.get("win_rate", 0),
                        "total_pnl": s.get("total_pnl", 0),
                        "last_pnl": s.get("last_pnl", 0),
                        "last_asset": s.get("last_asset", ""),
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
                "unrealized_pnl": d.get("unrealized_pnl", 0),
            })
    except Exception as e:
        pos_section["error"] = str(e)
    diag["sections"].append(pos_section)

    # ── 7. ASSET CLASS PERFORMANCE ──
    class_section = {"title": "ASSET CLASS PERFORMANCE", "rows": []}
    try:
        if r:
            for ac in ["crypto", "stock", "forex", "commodity", "index"]:
                raw = r.get(f"bahamut:training:class_stats:{ac}")
                if raw:
                    s = json.loads(raw)
                    if s.get("trades", 0) > 0:
                        class_section["rows"].append({
                            "class": ac,
                            "trades": s.get("trades", 0),
                            "wins": s.get("wins", 0),
                            "losses": s.get("losses", 0),
                            "win_rate": s.get("win_rate", 0),
                            "total_pnl": s.get("total_pnl", 0),
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
