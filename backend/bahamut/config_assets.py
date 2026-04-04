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

# ═══════════════════════════════════════════
# TRAINING UNIVERSE (paper trading only)
# ═══════════════════════════════════════════

TRAINING_CRYPTO = [
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
TRAINING_FOREX = []

# Indices DISABLED — similar volatility mismatch on 4H.
# 22 trades, 0 wins, -$500. Only losses from wide swings.
TRAINING_INDICES = []

# Commodities DISABLED — 7 trades, 0 wins, -$250. Same issue.
TRAINING_COMMODITIES = []

TRAINING_STOCKS = [
    # Core performers (proven profitable)
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
    "META", "TSLA", "AMD", "NFLX", "COIN",
    "SPY", "QQQ", "JPM", "BAC", "GS",
    # New additions — high-volume stocks that move well on 4H
    "CRM", "ORCL", "UBER", "SQ", "SHOP",
]

# Flatten all training assets
TRAINING_ASSETS = (
    TRAINING_CRYPTO + TRAINING_FOREX + TRAINING_INDICES
    + TRAINING_COMMODITIES + TRAINING_STOCKS
)

# Asset class mapping for learning engine
ASSET_CLASS_MAP = {}
for a in TRAINING_CRYPTO:
    ASSET_CLASS_MAP[a] = "crypto"
for a in TRAINING_FOREX:
    ASSET_CLASS_MAP[a] = "forex"
for a in TRAINING_INDICES:
    ASSET_CLASS_MAP[a] = "index"
for a in TRAINING_COMMODITIES:
    ASSET_CLASS_MAP[a] = "commodity"
for a in TRAINING_STOCKS:
    ASSET_CLASS_MAP[a] = "stock"


# ═══════════════════════════════════════════
# MODE & RISK PER ASSET
# ═══════════════════════════════════════════

def get_asset_mode(asset: str) -> str:
    """Returns 'production' or 'training'."""
    if asset in ACTIVE_TREND_ASSETS:
        return "production"
    if asset in TRAINING_ASSETS:
        return "training"
    return "unknown"


def get_risk_multiplier(asset: str) -> float:
    return ASSET_RISK_MULTIPLIERS.get(asset, 0.5)


def get_execution_params(asset: str) -> dict:
    return ASSET_PARAMS.get(asset, {"slippage_bps": 10, "spread_bps": 15})


def is_asset_active(asset: str) -> bool:
    return asset in ACTIVE_TREND_ASSETS


# Training risk: much smaller virtual positions
TRAINING_VIRTUAL_CAPITAL = 100_000  # $100K virtual portfolio
TRAINING_RISK_PER_TRADE_PCT = 0.005  # 0.5% per trade (vs 2% production)
TRAINING_MAX_POSITIONS = 20  # Allow many simultaneous training positions
