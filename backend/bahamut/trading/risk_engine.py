"""
Bahamut.AI — Portfolio Risk Engine

Computes live portfolio risk state for the training universe.
Consumed by: Risk Dashboard, selector, orchestrator.

Risk controls:
  1. Daily loss brake — block trades when daily PnL exceeds limit
  2. Portfolio max drawdown guard — reduce/block when DD too deep
  3. Per-class exposure caps — notional + risk-weighted
  4. Per-strategy risk budgets — based on trust/expectancy
  5. Correlation cluster warnings — flag concentrated bets
  6. Kill switch / safe mode — single status output
  7. Position sizing — multiplier output

All thresholds are configurable constants at the top of this file.
"""
import json
import os
import time
import structlog
from datetime import datetime, timezone, timedelta

logger = structlog.get_logger()

# ── State cache (avoids N×3 DB queries per selector cycle) ──
_cached_state: dict | None = None
_cached_at: float = 0
_CACHE_TTL = 30  # seconds — positions don't change faster than this


# ═══════════════════════════════════════════
# CONFIGURABLE THRESHOLDS
# ═══════════════════════════════════════════

DAILY_LOSS_LIMIT_PCT = 2.0        # Block new trades if daily loss > 2% of capital
DAILY_LOSS_LIMIT_CASH = 2000.0    # Or > $2,000 absolute
DAILY_LOSS_REDUCED_PCT = 1.0      # Reduce size if daily loss > 1%

MAX_PORTFOLIO_DD_PCT = 8.0        # Block all new trades if portfolio DD > 8%
REDUCED_DD_PCT = 5.0              # Reduce size if DD > 5%

CLASS_CAPS = {
    "crypto": {"max_notional_pct": 60, "max_positions": 8},
    "stock":  {"max_notional_pct": 60, "max_positions": 10},
    "forex":  {"max_notional_pct": 20, "max_positions": 3},
    "commodity": {"max_notional_pct": 15, "max_positions": 2},
    "index":  {"max_notional_pct": 15, "max_positions": 2},
}

STRATEGY_CAPS = {
    "v9_breakout":        {"max_positions": 8, "risk_budget_pct": 40},
    "v5_base":            {"max_positions": 6, "risk_budget_pct": 30},
    "v10_mean_reversion": {"max_positions": 6, "risk_budget_pct": 30},
}

MAX_PER_CLUSTER = 2  # From portfolio_optimizer


def _get_redis():
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        r.ping()
        return r
    except Exception:
        return None


def _load_open_positions() -> list[dict]:
    """Load current open training positions."""
    try:
        from bahamut.trading.engine import _load_positions
        positions = _load_positions()
        return [
            {
                "asset": p.asset,
                "asset_class": p.asset_class,
                "strategy": p.strategy,
                "direction": p.direction,
                "entry_price": p.entry_price,
                "current_price": p.current_price,
                "size": p.size,
                "risk_amount": p.risk_amount,
                "stop_price": p.stop_price,
                "tp_price": p.tp_price,
                "execution_type": p.execution_type,
            }
            for p in positions
        ]
    except Exception:
        return []


def _get_today_pnl() -> float:
    """Sum of PnL from trades closed today."""
    try:
        from bahamut.db.query import run_query_one
        row = run_query_one("""
            SELECT COALESCE(SUM(pnl), 0) as today_pnl
            FROM training_trades
            WHERE exit_time::timestamp >= CURRENT_DATE
        """)
        return float(row.get("today_pnl", 0) or 0) if row else 0.0
    except Exception:
        return 0.0


def _get_equity_and_dd() -> dict:
    """Current equity, peak, and drawdown from trade history."""
    try:
        from bahamut.db.query import run_query
        from bahamut.config_assets import TRADING_VIRTUAL_CAPITAL
        capital = TRADING_VIRTUAL_CAPITAL

        trades = run_query("""
            SELECT pnl FROM training_trades ORDER BY exit_time ASC
        """)
        if not trades:
            return {"equity": capital, "peak": capital, "dd": 0, "dd_pct": 0}

        running = capital
        peak = capital
        for t in trades:
            running += float(t.get("pnl", 0) or 0)
            if running > peak:
                peak = running

        dd = peak - running
        dd_pct = dd / max(1, peak) * 100
        return {"equity": round(running, 2), "peak": round(peak, 2),
                "dd": round(dd, 2), "dd_pct": round(dd_pct, 2)}
    except Exception:
        return {"equity": 100000, "peak": 100000, "dd": 0, "dd_pct": 0}


def get_risk_engine_state(force_refresh: bool = False) -> dict:
    """
    Main entry point. Returns full risk engine state.
    Called by: /training/risk-metrics, selector, orchestrator.
    Cached for 30s to avoid N×3 DB queries per selector cycle.
    """
    global _cached_state, _cached_at

    if not force_refresh and _cached_state and (time.time() - _cached_at) < _CACHE_TTL:
        return _cached_state

    from bahamut.config_assets import TRADING_VIRTUAL_CAPITAL, ASSET_CLASS_MAP
    from bahamut.trading.portfolio_optimizer import CORRELATION_CLUSTERS, _ASSET_CLUSTERS

    capital = TRADING_VIRTUAL_CAPITAL
    positions = _load_open_positions()
    today_pnl = _get_today_pnl()
    eq = _get_equity_and_dd()

    # ── Compute unrealized PnL from open positions ──
    unrealized = 0
    for p in positions:
        if p["direction"] == "LONG":
            unrealized += (p["current_price"] - p["entry_price"]) * p["size"]
        else:
            unrealized += (p["entry_price"] - p["current_price"]) * p["size"]

    daily_total = today_pnl + unrealized
    daily_dd_pct = abs(min(0, daily_total)) / max(1, capital) * 100

    # ── Exposure by class ──
    class_exposure = {}
    for p in positions:
        cls = p["asset_class"] or ASSET_CLASS_MAP.get(p["asset"], "other")
        if cls not in class_exposure:
            class_exposure[cls] = {"notional": 0, "risk": 0, "positions": 0, "assets": set()}
        notional = p["size"] * p["current_price"] if p["current_price"] > 0 else p["risk_amount"] * 20
        class_exposure[cls]["notional"] += notional
        class_exposure[cls]["risk"] += p["risk_amount"]
        class_exposure[cls]["positions"] += 1
        class_exposure[cls]["assets"].add(p["asset"])

    # Serialize sets
    class_exposure_out = {}
    total_notional = 0
    total_risk = 0
    for cls, exp in class_exposure.items():
        total_notional += exp["notional"]
        total_risk += exp["risk"]
        cap = CLASS_CAPS.get(cls, {"max_notional_pct": 50, "max_positions": 5})
        class_exposure_out[cls] = {
            "notional": round(exp["notional"], 2),
            "risk_weighted": round(exp["risk"], 2),
            "positions": exp["positions"],
            "assets": sorted(exp["assets"]),
            "cap_positions": cap["max_positions"],
            "cap_notional_pct": cap["max_notional_pct"],
            "utilization_pct": round(exp["positions"] / max(1, cap["max_positions"]) * 100, 1),
        }

    # ── Exposure by strategy ──
    strat_exposure = {}
    for p in positions:
        s = p["strategy"]
        if s not in strat_exposure:
            strat_exposure[s] = {"notional": 0, "risk": 0, "positions": 0}
        strat_exposure[s]["notional"] += p["size"] * max(p["current_price"], 1)
        strat_exposure[s]["risk"] += p["risk_amount"]
        strat_exposure[s]["positions"] += 1

    strat_exposure_out = {}
    for s, exp in strat_exposure.items():
        cap = STRATEGY_CAPS.get(s, {"max_positions": 6, "risk_budget_pct": 33})
        strat_exposure_out[s] = {
            "notional": round(exp["notional"], 2),
            "risk_weighted": round(exp["risk"], 2),
            "positions": exp["positions"],
            "cap_positions": cap["max_positions"],
            "risk_budget_pct": cap["risk_budget_pct"],
            "utilization_pct": round(exp["positions"] / max(1, cap["max_positions"]) * 100, 1),
        }

    # ── Cluster warnings ──
    cluster_counts = {}
    for p in positions:
        for cid in _ASSET_CLUSTERS.get(p["asset"], []):
            if cid not in cluster_counts:
                cluster_counts[cid] = {"count": 0, "assets": set(), "label": CORRELATION_CLUSTERS[cid]["label"]}
            cluster_counts[cid]["count"] += 1
            cluster_counts[cid]["assets"].add(p["asset"])

    cluster_warnings = []
    for cid, info in cluster_counts.items():
        if info["count"] >= MAX_PER_CLUSTER:
            cluster_warnings.append({
                "cluster": cid,
                "label": info["label"],
                "count": info["count"],
                "max": MAX_PER_CLUSTER,
                "assets": sorted(info["assets"]),
                "status": "BLOCKED" if info["count"] > MAX_PER_CLUSTER else "AT_LIMIT",
            })

    # ── Triggered rules + mode decision ──
    triggered = []
    warnings = []
    recommendations = []
    mode = "NORMAL"
    block_new_trades = False
    size_multiplier = 1.0

    # Daily loss brake
    if daily_dd_pct >= DAILY_LOSS_LIMIT_PCT or abs(min(0, daily_total)) >= DAILY_LOSS_LIMIT_CASH:
        triggered.append("daily_loss_brake")
        block_new_trades = True
        mode = "BLOCKED"
        recommendations.append(f"Daily loss ${abs(min(0, daily_total)):.0f} exceeds limit — new trades blocked")
        try:
            from bahamut.monitoring.telegram import send_alert
            send_alert(f"🛑 DAILY LOSS BRAKE HIT: ${abs(min(0, daily_total)):.0f} "
                       f"({daily_dd_pct:.1f}%) — all new trades blocked")
        except Exception:
            pass
    elif daily_dd_pct >= DAILY_LOSS_REDUCED_PCT:
        triggered.append("daily_loss_reduced")
        size_multiplier = min(size_multiplier, 0.5)
        if mode == "NORMAL":
            mode = "REDUCED"
        warnings.append(f"Daily loss at {daily_dd_pct:.1f}% — size reduced 50%")

    # Portfolio drawdown guard
    if eq["dd_pct"] >= MAX_PORTFOLIO_DD_PCT:
        triggered.append("portfolio_dd_block")
        block_new_trades = True
        mode = "BLOCKED"
        recommendations.append(f"Portfolio drawdown {eq['dd_pct']:.1f}% exceeds {MAX_PORTFOLIO_DD_PCT}% limit")
        try:
            from bahamut.monitoring.telegram import send_alert
            send_alert(f"🛑 PORTFOLIO DRAWDOWN BLOCK: {eq['dd_pct']:.1f}% "
                       f"exceeds {MAX_PORTFOLIO_DD_PCT}% — all new trades blocked")
        except Exception:
            pass
    elif eq["dd_pct"] >= REDUCED_DD_PCT:
        triggered.append("portfolio_dd_reduced")
        size_multiplier = min(size_multiplier, 0.5)
        if mode == "NORMAL":
            mode = "REDUCED"
        warnings.append(f"Portfolio drawdown {eq['dd_pct']:.1f}% approaching limit ({MAX_PORTFOLIO_DD_PCT}%)")

    # Class cap warnings
    for cls, exp in class_exposure_out.items():
        if exp["utilization_pct"] >= 100:
            warnings.append(f"{cls.upper()} at position cap ({exp['positions']}/{exp['cap_positions']})")
        elif exp["utilization_pct"] >= 80:
            recommendations.append(f"{cls.upper()} exposure at {exp['utilization_pct']:.0f}% of cap")

    # Strategy cap warnings
    for s, exp in strat_exposure_out.items():
        if exp["utilization_pct"] >= 100:
            warnings.append(f"{s} at position cap ({exp['positions']}/{exp['cap_positions']})")

    # Cluster warnings
    for cw in cluster_warnings:
        warnings.append(f"Cluster '{cw['label']}' at {cw['count']}/{cw['max']} — {', '.join(cw['assets'])}")

    # Per-strategy drawdown kill (each strategy must survive on its own)
    per_strategy_blocked = {}
    try:
        import redis as _redis_mod, os as _os_mod
        _rr = _redis_mod.from_url(_os_mod.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                                   socket_connect_timeout=1)
        PER_STRATEGY_DD_LIMIT = 15.0
        for strat in ("v5_base", "v9_breakout", "v10_mean_reversion"):
            raw = _rr.get(f"bahamut:strategy_dd:{strat}")
            if raw:
                dd_pct = float(raw)
                if dd_pct >= PER_STRATEGY_DD_LIMIT:
                    per_strategy_blocked[strat] = dd_pct
                    triggered.append(f"strategy_dd_block_{strat}")
                    warnings.append(f"{strat} drawdown {dd_pct:.1f}% — strategy paused")
    except Exception:
        pass

    # If no issues
    if not triggered and not warnings:
        recommendations.append("All risk controls within limits")

    result = {
        "risk_engine": {
            "status": "active",
            "mode": mode,
            "block_new_trades": block_new_trades,
            "size_multiplier": round(size_multiplier, 2),
            "daily_loss_limit_pct": DAILY_LOSS_LIMIT_PCT,
            "daily_loss_limit_cash": DAILY_LOSS_LIMIT_CASH,
            "current_daily_pnl": round(daily_total, 2),
            "current_daily_drawdown_pct": round(daily_dd_pct, 2),
            "max_portfolio_drawdown_pct": MAX_PORTFOLIO_DD_PCT,
            "current_portfolio_drawdown_pct": eq["dd_pct"],
            "current_equity": eq["equity"],
            "peak_equity": eq["peak"],
            "per_strategy_blocked": per_strategy_blocked,
        },
        "exposure": {
            "total_notional": round(total_notional, 2),
            "total_risk_weighted": round(total_risk, 2),
            "open_positions": len(positions),
            "by_class": class_exposure_out,
            "by_strategy": strat_exposure_out,
        },
        "correlation": {
            "method": "rule_based_clusters",
            "top_clusters": cluster_warnings,
            "blocked_candidates_count": sum(1 for cw in cluster_warnings if cw["status"] == "BLOCKED"),
            # Internal: cluster position counts for can_open_new_trade
            "_cluster_counts": {cid: info["count"] for cid, info in cluster_counts.items()},
        },
        "limits": {
            "class_caps": CLASS_CAPS,
            "strategy_caps": STRATEGY_CAPS,
            "max_per_cluster": MAX_PER_CLUSTER,
        },
        "controls": {
            "triggered_rules": triggered,
            "warnings": warnings,
            "recommendations": recommendations,
        },
    }

    _cached_state = result
    _cached_at = time.time()
    return result


def invalidate_risk_cache():
    """Call after a position opens/closes to force fresh state."""
    global _cached_state, _cached_at
    _cached_state = None
    _cached_at = 0


def can_open_new_trade(asset: str, strategy: str, direction: str,
                       asset_class: str = "") -> dict:
    """Check if a new trade is allowed by the risk engine.
    Returns: {"allowed": bool, "reason": str, "size_multiplier": float}
    """
    state = get_risk_engine_state()
    re = state["risk_engine"]

    if re["block_new_trades"]:
        return {"allowed": False, "reason": f"Risk engine mode={re['mode']}: {state['controls']['triggered_rules']}",
                "size_multiplier": 0}

    # Check class cap
    cls = asset_class or "other"
    cls_exp = state["exposure"]["by_class"].get(cls, {})
    cap = CLASS_CAPS.get(cls, {"max_positions": 5})
    if cls_exp.get("positions", 0) >= cap["max_positions"]:
        return {"allowed": False, "reason": f"{cls} at position cap ({cls_exp['positions']}/{cap['max_positions']})",
                "size_multiplier": 0}

    # Check strategy cap
    strat_exp = state["exposure"]["by_strategy"].get(strategy, {})
    strat_cap = STRATEGY_CAPS.get(strategy, {"max_positions": 6})
    if strat_exp.get("positions", 0) >= strat_cap["max_positions"]:
        return {"allowed": False, "reason": f"{strategy} at position cap",
                "size_multiplier": 0}

    # Check cluster limit — would adding this asset breach any cluster?
    from bahamut.trading.portfolio_optimizer import _ASSET_CLUSTERS
    cluster_counts = state.get("correlation", {}).get("_cluster_counts", {})
    for cid in _ASSET_CLUSTERS.get(asset, []):
        if cluster_counts.get(cid, 0) >= MAX_PER_CLUSTER:
            from bahamut.trading.portfolio_optimizer import CORRELATION_CLUSTERS
            label = CORRELATION_CLUSTERS.get(cid, {}).get("label", cid)
            return {"allowed": False,
                    "reason": f"Cluster '{label}' at {cluster_counts[cid]}/{MAX_PER_CLUSTER}",
                    "size_multiplier": 0}

    return {"allowed": True, "reason": "within_limits",
            "size_multiplier": re["size_multiplier"]}


def get_size_multiplier() -> float:
    """Quick check: what size multiplier should be applied to new trades?"""
    state = get_risk_engine_state()
    if state["risk_engine"]["block_new_trades"]:
        return 0.0
    return state["risk_engine"]["size_multiplier"]
