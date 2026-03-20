"""
Strategy Segmentation — Asset-class-specific parameters.

Different asset classes require different:
  - Threshold sensitivity
  - Volatility expectations
  - Hold durations
  - Risk parameters
"""

STRATEGY_PARAMS = {
    "fx": {
        "neutral_zone": 15,
        "sl_atr_mult": 1.5,
        "tp_atr_mult": 2.25,
        "max_hold_candles": 12,  # 48h at 4H
        "max_concurrent": 4,
        "risk_per_trade_pct": 1.5,
        "slippage_bps": 3,
        "spread_bps": 8,
        "ema_weight": 1.0,
        "structure_weight": 0.8,
        "rsi_overbought": 70,
        "rsi_oversold": 30,
        "adx_strong": 25,
        "adx_weak": 15,
        "description": "FX: tighter stops, moderate hold, spread-sensitive",
    },
    "crypto": {
        "neutral_zone": 20,
        "sl_atr_mult": 2.0,
        "tp_atr_mult": 3.0,
        "max_hold_candles": 18,  # 72h at 4H
        "max_concurrent": 3,
        "risk_per_trade_pct": 2.0,
        "slippage_bps": 10,
        "spread_bps": 15,
        "ema_weight": 0.8,
        "structure_weight": 1.0,
        "rsi_overbought": 75,
        "rsi_oversold": 25,
        "adx_strong": 25,
        "adx_weak": 18,
        "description": "Crypto: wider stops, longer hold, higher volatility tolerance",
    },
    "commodities": {
        "neutral_zone": 18,
        "sl_atr_mult": 1.8,
        "tp_atr_mult": 2.7,
        "max_hold_candles": 15,
        "max_concurrent": 3,
        "risk_per_trade_pct": 1.5,
        "slippage_bps": 5,
        "spread_bps": 12,
        "ema_weight": 0.9,
        "structure_weight": 0.9,
        "rsi_overbought": 72,
        "rsi_oversold": 28,
        "adx_strong": 25,
        "adx_weak": 16,
        "description": "Commodities: medium parameters, momentum-driven",
    },
    "stocks": {
        "neutral_zone": 15,
        "sl_atr_mult": 2.0,
        "tp_atr_mult": 3.0,
        "max_hold_candles": 20,  # 5 days at 4H (market hours)
        "max_concurrent": 5,
        "risk_per_trade_pct": 2.0,
        "slippage_bps": 5,
        "spread_bps": 5,
        "ema_weight": 1.0,
        "structure_weight": 1.0,
        "rsi_overbought": 70,
        "rsi_oversold": 30,
        "adx_strong": 25,
        "adx_weak": 15,
        "description": "Stocks: standard parameters, earnings/event aware",
    },
    "indices": {
        "neutral_zone": 15,
        "sl_atr_mult": 1.5,
        "tp_atr_mult": 2.5,
        "max_hold_candles": 12,
        "max_concurrent": 3,
        "risk_per_trade_pct": 1.5,
        "slippage_bps": 3,
        "spread_bps": 5,
        "ema_weight": 1.0,
        "structure_weight": 0.7,
        "rsi_overbought": 70,
        "rsi_oversold": 30,
        "adx_strong": 20,
        "adx_weak": 12,
        "description": "Indices: macro-sensitive, moderate parameters",
    },
    "bonds": {
        "neutral_zone": 20,
        "sl_atr_mult": 1.5,
        "tp_atr_mult": 2.0,
        "max_hold_candles": 24,
        "max_concurrent": 2,
        "risk_per_trade_pct": 1.0,
        "slippage_bps": 2,
        "spread_bps": 5,
        "ema_weight": 0.7,
        "structure_weight": 0.5,
        "rsi_overbought": 65,
        "rsi_oversold": 35,
        "adx_strong": 20,
        "adx_weak": 12,
        "description": "Bonds: conservative, macro-driven, longer holds",
    },
}


def get_strategy_params(asset_class: str) -> dict:
    """Get strategy parameters for an asset class. Falls back to FX defaults."""
    return STRATEGY_PARAMS.get(asset_class, STRATEGY_PARAMS["fx"])
