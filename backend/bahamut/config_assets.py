"""
Bahamut Multi-Asset Configuration

Defines active tradable assets, per-asset risk parameters,
and combined crypto correlation risk limits.
"""

# ── Active assets for trend-regime trading ──
ACTIVE_TREND_ASSETS = ["BTCUSD", "ETHUSD"]

# ── Per-asset risk multipliers ──
# BTC is the primary validated asset. ETH gets slightly lower risk initially.
ASSET_RISK_MULTIPLIERS = {
    "BTCUSD": 1.0,
    "ETHUSD": 0.75,  # 75% of BTC risk until independently validated
}

# ── Per-asset execution parameters ──
ASSET_PARAMS = {
    "BTCUSD": {
        "slippage_bps": 8,
        "spread_bps": 12,
    },
    "ETHUSD": {
        "slippage_bps": 10,   # ETH slightly wider spread
        "spread_bps": 15,
    },
}

# ── Combined crypto risk limit ──
# BTC and ETH are ~0.85 correlated. Don't treat them as independent risks.
MAX_COMBINED_CRYPTO_OPEN_RISK_PCT = 0.05  # 5% max total crypto open risk
MAX_POSITIONS_PER_ASSET = 1               # One position per strategy per asset
MAX_TOTAL_OPEN_POSITIONS = 4              # Across all assets and strategies


def get_risk_multiplier(asset: str) -> float:
    return ASSET_RISK_MULTIPLIERS.get(asset, 0.5)

def get_execution_params(asset: str) -> dict:
    return ASSET_PARAMS.get(asset, {"slippage_bps": 10, "spread_bps": 15})

def is_asset_active(asset: str) -> bool:
    return asset in ACTIVE_TREND_ASSETS
