"""
Bahamut Multi-Asset Configuration

Two tiers:
  PRODUCTION — BTC/ETH with real execution (v7 orchestrator)
  TRAINING   — ~50 assets, paper trading only, feeds learning engine

CRITICAL: Training assets NEVER touch the production execution engine.
"""

# ═══════════════════════════════════════════
# PRODUCTION (unchanged — real execution)
# ═══════════════════════════════════════════

ACTIVE_TREND_ASSETS = ["BTCUSD", "ETHUSD"]

ASSET_RISK_MULTIPLIERS = {
    "BTCUSD": 1.0,
    "ETHUSD": 0.75,
}

ASSET_PARAMS = {
    "BTCUSD": {"slippage_bps": 8, "spread_bps": 12},
    "ETHUSD": {"slippage_bps": 10, "spread_bps": 15},
}

MAX_COMBINED_CRYPTO_OPEN_RISK_PCT = 0.05
MAX_POSITIONS_PER_ASSET = 1
MAX_TOTAL_OPEN_POSITIONS = 4


# ═══════════════════════════════════════════
# TRAINING UNIVERSE (paper trading only)
# ═══════════════════════════════════════════

TRADING_CRYPTO = [
    # Tier 1: Large caps (high liquidity, tighter spreads)
    "BTCUSD", "ETHUSD", "BNBUSD", "SOLUSD", "XRPUSD",
    # Tier 2: Major alts
    "ADAUSD", "DOGEUSD", "AVAXUSD", "LINKUSD", "MATICUSD",
    # Tier 3: High-volume mid caps (free on Binance, good volatility)
    "DOTUSD", "ATOMUSD", "UNIUSD", "LTCUSD", "NEARUSD",
    "ARBUSD", "OPUSD", "FILUSD", "APTUSD", "INJUSD",
    # Tier 4: High volatility (great for mean reversion)
    "PEPEUSD", "WIFUSD", "RNDRUSD", "FETUSD", "TIAUSD",
    "SUIUSD", "SEIUSD", "JUPUSD", "WUSD", "ENAUSD",
]

# Forex DISABLED — 4H bars move 0.1-0.2%, SL/TP at 3-8% = never hits.
# 13 trades, 0 wins, $0 PnL. Dead weight wasting API calls.
TRADING_FOREX = []

# Indices DISABLED — similar volatility mismatch on 4H.
# 22 trades, 0 wins, -$500. Only losses from wide swings.
TRADING_INDICES = []

# Commodities DISABLED — 7 trades, 0 wins, -$250. Same issue.
TRADING_COMMODITIES = []

TRADING_STOCKS = [
    # Core performers (proven profitable)
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
    "META", "TSLA", "AMD", "NFLX", "COIN",
    "SPY", "QQQ", "JPM", "BAC", "GS",
    # New additions — high-volume stocks that move well on 4H
    "CRM", "ORCL", "UBER", "SQ", "SHOP",
]

# Flatten all training assets
TRADING_ASSETS = (
    TRADING_CRYPTO + TRADING_FOREX + TRADING_INDICES
    + TRADING_COMMODITIES + TRADING_STOCKS
)

# Asset class mapping for learning engine
ASSET_CLASS_MAP = {}
for a in TRADING_CRYPTO:
    ASSET_CLASS_MAP[a] = "crypto"
for a in TRADING_FOREX:
    ASSET_CLASS_MAP[a] = "forex"
for a in TRADING_INDICES:
    ASSET_CLASS_MAP[a] = "index"
for a in TRADING_COMMODITIES:
    ASSET_CLASS_MAP[a] = "commodity"
for a in TRADING_STOCKS:
    ASSET_CLASS_MAP[a] = "stock"


# ═══════════════════════════════════════════
# MODE & RISK PER ASSET
# ═══════════════════════════════════════════

def get_asset_mode(asset: str) -> str:
    """Returns 'production' or 'training'."""
    if asset in ACTIVE_TREND_ASSETS:
        return "production"
    if asset in TRADING_ASSETS:
        return "training"
    return "unknown"


def get_risk_multiplier(asset: str) -> float:
    return ASSET_RISK_MULTIPLIERS.get(asset, 0.5)


def get_execution_params(asset: str) -> dict:
    return ASSET_PARAMS.get(asset, {"slippage_bps": 10, "spread_bps": 15})


def is_asset_active(asset: str) -> bool:
    return asset in ACTIVE_TREND_ASSETS


# Training risk: much smaller virtual positions
TRADING_VIRTUAL_CAPITAL = 100_000  # $100K virtual portfolio
TRADING_RISK_PER_TRADE_PCT = 0.005  # 0.5% per trade (vs 2% production)
TRADING_MAX_POSITIONS = 20  # Allow many simultaneous training positions


# ═══════════════════════════════════════════
# CANONICAL SUPPRESS MAP — single source of truth
# All suppress checks (engine, strategy, orchestrator, selector) read from here.
# To suppress an asset: add it here. That's it.
# ═══════════════════════════════════════════

TRADING_SUPPRESS = {
    # Global: blocked on ALL strategies, ALL signal paths
    "*": {"RNDRUSD", "MATICUSD", "IXIC", "EURUSD", "XAUUSD", "SPX", "COIN"},
    # v5_base: blocked on EMA trend strategy
    "v5_base": {"ARBUSD", "WIFUSD", "BTCUSD", "FILUSD"},
    # v10_mean_reversion: blocked on mean reversion (standard path)
    "v10_mean_reversion": {"SOLUSD", "BNBUSD", "AAPL", "DOTUSD", "ADAUSD", "UNIUSD", "LTCUSD", "FILUSD", "ATOMUSD"},
    # v9_breakout: specific underperformers
    "v9_breakout": {"ETHUSD", "AMD"},
}

# ═══════════════════════════════════════════
# CRASH-SHORT SUPPRESS — separate from standard v10
# Only applied when execution_type == "crash_short"
# Criteria: ≥4 trades AND (WR<45% AND pnl<-100) OR pnl<-250
# ═══════════════════════════════════════════
CRASH_SHORT_SUPPRESS = {
    # Hard block: proven losers on crash-short path
    "DOTUSD",    # 4 trades, 25% WR, -695
    "SOLUSD",    # 8 trades, 42.9% WR, -528
    "UNIUSD",    # 4 trades, 75% WR, -341 (massive avg loss)
    "SUIUSD",    # 1 trade, -310 (single catastrophic loss)
    "ETHUSD",    # 1 trade, -159 (single large loss)
    "COIN",      # 7 trades, 42.9% WR, -136
}

# Crash-short penalty: reduced sizing for borderline assets
# Criteria: WR<50% OR recent negative streak
CRASH_SHORT_PENALIZE = {
    "BNBUSD",    # 5 trades, 40% WR, -79
    "TIAUSD",    # 3 trades, 33.3% WR, -60
    "OPUSD",     # 1 trade, 0% WR, -73
    "MSFT",      # 1 trade, 0% WR, -77 (stock crash-short)
}


# ═══════════════════════════════════════════
# Phase 3 Item 7 — SUB-STRATEGY SUPPRESS MAP
# Per-substrategy hard blocks. A v10 signal tags itself with one of:
#   "v10_range_long"  — LONG in RANGE regime
#   "v10_range_short" — SHORT in RANGE regime (non-crash)
#   "v10_crash_short" — SHORT triggered by CRASH SHORT detector
#
# This lets us block an asset on (e.g.) v10_range_short without
# also blocking it on v10_crash_short — the two have different edge.
# Starts empty; populated by operator as per-substrategy trust data matures.
# ═══════════════════════════════════════════
SUBSTRATEGY_SUPPRESS: dict = {
    # Example entry — kept empty until we have per-substrategy stats:
    # "v10_range_short": {"XRPUSD"},
    # "v10_crash_short": {"SUIUSD"},
}


def is_suppressed(asset: str, strategy: str, execution_type: str = "standard",
                  substrategy: str = "") -> bool:
    """Check if an asset is suppressed for a given strategy/execution type.

    Phase 3 Item 7: also checks SUBSTRATEGY_SUPPRESS when substrategy is
    non-empty. Callers that don't know the substrategy pass empty string
    and only the parent-strategy maps apply — behavior unchanged for
    v5/v9 and legacy v10 callers.
    """
    if asset in TRADING_SUPPRESS.get("*", set()):
        return True
    if asset in TRADING_SUPPRESS.get(strategy, set()):
        return True
    if execution_type == "crash_short" and asset in CRASH_SHORT_SUPPRESS:
        return True
    if substrategy and asset in SUBSTRATEGY_SUPPRESS.get(substrategy, set()):
        return True
    return False


# ═══════════════════════════════════════════
# LEGACY MODE — defensive flag
# When False: all legacy write endpoints return 410 Gone,
# legacy celery tasks are not registered, legacy UI nav is hidden.
# When True: legacy system is re-enabled (for research/debugging only).
# ═══════════════════════════════════════════
LEGACY_MODE_ENABLED = False
