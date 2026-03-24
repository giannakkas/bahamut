"""
Bahamut.AI — Training Portfolio Optimizer

Prevents correlated-cluster overexposure in the training universe.
Rule-based first version — no fake quant correlations.

Checks before allowing a new trade:
  1. Correlation cluster limits (BTC+ETH, SPY+QQQ, EURUSD+GBPUSD, etc.)
  2. Direction concentration (max longs / max shorts)
  3. Per-class open position limits (including existing positions)
  4. Strategy concentration limits
  5. Same-direction same-class concentration

Returns: ALLOW / PENALIZE / BLOCK with explanation for each candidate.

TRAINING ONLY — does not touch production.
"""
import structlog

logger = structlog.get_logger()

# ═══════════════════════════════════════════
# CORRELATION CLUSTER MAP
# Rule-based: assets that move together get grouped.
# If you already hold one member, adding another
# from the same cluster is penalized or blocked.
# ═══════════════════════════════════════════

CORRELATION_CLUSTERS = {
    "btc_eth": {"assets": {"BTCUSD", "ETHUSD"}, "label": "BTC/ETH crypto majors"},
    "alt_crypto": {"assets": {"SOLUSD", "AVAXUSD", "MATICUSD", "LINKUSD"}, "label": "Alt-L1 crypto"},
    "meme_crypto": {"assets": {"DOGEUSD", "ADAUSD"}, "label": "Meme/community crypto"},
    "usd_majors": {"assets": {"EURUSD", "GBPUSD", "USDCHF", "USDCAD"}, "label": "USD major pairs"},
    "jpy_crosses": {"assets": {"USDJPY", "EURJPY", "GBPJPY"}, "label": "JPY crosses"},
    "us_indices": {"assets": {"SPX", "IXIC", "DJI", "SPY", "QQQ"}, "label": "US equity indices"},
    "us_mega_tech": {"assets": {"AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META"}, "label": "US mega-cap tech"},
    "us_financials": {"assets": {"JPM", "BAC", "GS"}, "label": "US financials"},
    "precious_metals": {"assets": {"XAUUSD", "XAGUSD"}, "label": "Precious metals"},
    "energy_crypto": {"assets": {"COIN", "BTCUSD"}, "label": "Crypto-equity proxy"},
}

# Build reverse lookup: asset → list of cluster IDs
_ASSET_CLUSTERS: dict[str, list[str]] = {}
for cid, cdata in CORRELATION_CLUSTERS.items():
    for asset in cdata["assets"]:
        _ASSET_CLUSTERS.setdefault(asset, []).append(cid)


# ═══════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════

DEFAULT_LIMITS = {
    "max_per_cluster": 2,          # Max positions from same correlation cluster
    "max_same_direction": 8,       # Max total longs OR shorts across portfolio
    "max_per_class_total": 5,      # Max open positions per asset class (total, not per cycle)
    "max_per_strategy_total": 6,   # Max open positions per strategy
    "max_same_dir_same_class": 3,  # Max same-direction in same class (e.g. 3 crypto longs)
    "cluster_penalty_points": 10,  # Priority penalty per existing cluster member
    "direction_penalty_points": 5, # Priority penalty when direction is concentrated
}


# ═══════════════════════════════════════════
# PORTFOLIO STATE SNAPSHOT
# ═══════════════════════════════════════════

def _build_portfolio_snapshot(positions: list[dict]) -> dict:
    """Build a snapshot of current portfolio state for constraint checking."""
    snap = {
        "total": len(positions),
        "longs": 0,
        "shorts": 0,
        "by_class": {},      # class → count
        "by_strategy": {},   # strategy → count
        "by_cluster": {},    # cluster_id → count
        "by_direction_class": {},  # "LONG:crypto" → count
        "assets": set(),
    }

    for p in positions:
        d = p.get("direction", "LONG")
        cls = p.get("asset_class", "unknown")
        strat = p.get("strategy", "unknown")
        asset = p.get("asset", "")

        if d == "LONG":
            snap["longs"] += 1
        else:
            snap["shorts"] += 1

        snap["by_class"][cls] = snap["by_class"].get(cls, 0) + 1
        snap["by_strategy"][strat] = snap["by_strategy"].get(strat, 0) + 1
        snap["assets"].add(asset)

        dir_cls = f"{d}:{cls}"
        snap["by_direction_class"][dir_cls] = snap["by_direction_class"].get(dir_cls, 0) + 1

        for cid in _ASSET_CLUSTERS.get(asset, []):
            snap["by_cluster"][cid] = snap["by_cluster"].get(cid, 0) + 1

    return snap


# ═══════════════════════════════════════════
# EVALUATE ONE CANDIDATE
# ═══════════════════════════════════════════

def evaluate_candidate(
    asset: str,
    asset_class: str,
    strategy: str,
    direction: str,
    portfolio_snap: dict,
    limits: dict | None = None,
) -> dict:
    """
    Evaluate a single candidate against portfolio constraints.

    Returns:
      decision: "ALLOW" | "PENALIZE" | "BLOCK"
      penalty: int (priority points to deduct)
      reasons: list of explanation strings
      cluster_warnings: list of triggered cluster names
    """
    lim = limits or DEFAULT_LIMITS
    penalty = 0
    reasons = []
    cluster_warnings = []
    blocked = False

    # 1. Correlation cluster check
    for cid in _ASSET_CLUSTERS.get(asset, []):
        existing_count = portfolio_snap.get("by_cluster", {}).get(cid, 0)
        cluster_label = CORRELATION_CLUSTERS[cid]["label"]

        if existing_count >= lim["max_per_cluster"]:
            blocked = True
            reasons.append(f"Cluster full: {cluster_label} ({existing_count}/{lim['max_per_cluster']})")
            cluster_warnings.append(cluster_label)
        elif existing_count > 0:
            pen = existing_count * lim["cluster_penalty_points"]
            penalty += pen
            reasons.append(f"Cluster overlap: {cluster_label} ({existing_count} existing, -{pen}pts)")
            cluster_warnings.append(cluster_label)

    # 2. Direction concentration
    dir_count = portfolio_snap.get("longs" if direction == "LONG" else "shorts", 0)
    if dir_count >= lim["max_same_direction"]:
        blocked = True
        reasons.append(f"Direction full: {dir_count} {direction}s already open (max {lim['max_same_direction']})")
    elif dir_count >= lim["max_same_direction"] - 2:
        pen = lim["direction_penalty_points"]
        penalty += pen
        reasons.append(f"Direction heavy: {dir_count} {direction}s open (-{pen}pts)")

    # 3. Per-class total
    class_count = portfolio_snap.get("by_class", {}).get(asset_class, 0)
    if class_count >= lim["max_per_class_total"]:
        blocked = True
        reasons.append(f"Class full: {asset_class} has {class_count}/{lim['max_per_class_total']} positions")
    elif class_count >= lim["max_per_class_total"] - 1:
        penalty += 5
        reasons.append(f"Class near limit: {asset_class} has {class_count}/{lim['max_per_class_total']}")

    # 4. Strategy concentration
    strat_count = portfolio_snap.get("by_strategy", {}).get(strategy, 0)
    if strat_count >= lim["max_per_strategy_total"]:
        blocked = True
        reasons.append(f"Strategy full: {strategy} has {strat_count}/{lim['max_per_strategy_total']} positions")

    # 5. Same-direction same-class
    dir_cls_key = f"{direction}:{asset_class}"
    dir_cls_count = portfolio_snap.get("by_direction_class", {}).get(dir_cls_key, 0)
    if dir_cls_count >= lim["max_same_dir_same_class"]:
        blocked = True
        reasons.append(f"Concentrated: {dir_cls_count} {direction} {asset_class} already (max {lim['max_same_dir_same_class']})")

    # 6. Duplicate asset
    if asset in portfolio_snap.get("assets", set()):
        blocked = True
        reasons.append(f"Already holding {asset}")

    # Decision
    if blocked:
        decision = "BLOCK"
    elif penalty > 0:
        decision = "PENALIZE"
    else:
        decision = "ALLOW"
        reasons.append("Low overlap, good diversification")

    return {
        "decision": decision,
        "penalty": penalty,
        "reasons": reasons,
        "cluster_warnings": cluster_warnings,
    }


# ═══════════════════════════════════════════
# BATCH EVALUATE (for selector integration)
# ═══════════════════════════════════════════

def optimize_selections(signals: list, open_positions: list[dict]) -> list[dict]:
    """
    Evaluate all pending signals against portfolio constraints.
    Returns list of dicts with signal + optimizer result.

    Used by selector.select_candidates() to adjust priority scores
    and block overexposed candidates.
    """
    snap = _build_portfolio_snapshot(open_positions)
    results = []

    for sig in signals:
        opt = evaluate_candidate(
            asset=sig.asset,
            asset_class=sig.asset_class,
            strategy=sig.strategy,
            direction=sig.direction,
            portfolio_snap=snap,
        )
        results.append({
            "asset": sig.asset,
            "optimizer": opt,
        })

    return results


def get_portfolio_constraints_summary(open_positions: list[dict]) -> dict:
    """Build a summary of current portfolio constraints for the dashboard."""
    snap = _build_portfolio_snapshot(open_positions)
    lim = DEFAULT_LIMITS

    cluster_status = {}
    for cid, cdata in CORRELATION_CLUSTERS.items():
        count = snap["by_cluster"].get(cid, 0)
        if count > 0:
            cluster_status[cid] = {
                "label": cdata["label"],
                "count": count,
                "max": lim["max_per_cluster"],
                "full": count >= lim["max_per_cluster"],
            }

    return {
        "total_positions": snap["total"],
        "longs": snap["longs"],
        "shorts": snap["shorts"],
        "direction_limit": lim["max_same_direction"],
        "by_class": snap["by_class"],
        "class_limit": lim["max_per_class_total"],
        "by_strategy": snap["by_strategy"],
        "strategy_limit": lim["max_per_strategy_total"],
        "active_clusters": cluster_status,
        "limits": lim,
    }
