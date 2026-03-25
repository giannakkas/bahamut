"""
Bahamut.AI — Production Default Configuration (v1)

Sensible defaults for paper-trading / warm-start environments.
These load deterministically at startup. User overrides are preserved.
"""

CONFIG_DEFAULTS_VERSION = 1

# ─── Kill Switch ───
KILL_SWITCH_DEFAULTS = {
    "kill_switch.tail_risk_threshold": 0.25,
    "kill_switch.fragility_threshold": 0.80,
    "kill_switch.combined_stress_threshold": 0.70,
}

# ─── Safe Mode ───
SAFE_MODE_DEFAULTS = {
    "safe_mode.enabled": False,
    "safe_mode.max_concurrent_trades": 2,
    "safe_mode.max_position_pct": 0.01,
}

# ─── Deleveraging ───
DELEVERAGE_DEFAULTS = {
    "deleverage.fragility_trigger": 0.75,
    "deleverage.max_close_per_cycle": 1,
}

# ─── Confidence & Scoring ───
CONFIDENCE_DEFAULTS = {
    "confidence.min_trade": 0.58,
    "confidence.strong_signal": 0.72,
    "confidence.min_agreement": 6,
    "confidence.min_individual": 0.50,
}

# ─── Exposure Limits ───
EXPOSURE_DEFAULTS = {
    "exposure.gross_max": 0.80,
    "exposure.net_max": 0.50,
    "exposure.single_class_max": 0.40,
    "exposure.single_theme_max": 0.30,
    "exposure.single_asset_max": 0.15,
}

# ─── Marginal Risk ───
MARGINAL_RISK_DEFAULTS = {
    "marginal_risk.warn_threshold": 0.05,
    "marginal_risk.approval_threshold": 0.10,
    "marginal_risk.block_threshold": 0.15,
}

# ─── Quality Ratio ───
QUALITY_DEFAULTS = {
    "quality.min_ratio": 0.30,
    "quality.approval_ratio": 0.50,
    "quality.block_ratio": 0.20,
}

# ─── Scenario Weights ───
SCENARIO_DEFAULTS = {
    "scenario.weight_bear": 0.25,
    "scenario.weight_bull": 0.15,
    "scenario.weight_crash": 0.30,
    "scenario.weight_recovery": 0.10,
    "scenario.weight_stagnation": 0.20,
    "scenario.tail_risk_warn": 0.05,
    "scenario.tail_risk_approval": 0.10,
    "scenario.tail_risk_block": 0.15,
}

# ─── Readiness ───
READINESS_DEFAULTS = {
    "readiness.min_data_freshness_hours": 4,
    "readiness.min_agents_online": 5,
}

# ─── Warmup Mode ───
WARMUP_DEFAULTS = {
    "warmup.min_closed_trades": 20,
    "warmup.min_calibration_age_days": 3,
    "warmup.min_learning_samples": 50,
    "warmup.auto_trade_during_warmup": False,
    "warmup.size_multiplier": 0.5,
}

# ─── Exploration Mode ───
EXPLORATION_DEFAULTS = {
    "exploration.enabled": True,
    "exploration.min_consensus_score": 0.35,
    "exploration.max_per_cycle": 1,
    "exploration.max_open_positions": 2,
    "exploration.risk_pct": 0.5,           # 0.5% vs 2% normal
    "exploration.size_multiplier": 0.25,   # 25% of normal size
    "exploration.min_signal_label": "WEAK_SIGNAL",  # Allow WEAK_SIGNAL
    "exploration.blocked_regimes": "CRISIS",
}

# ─── Trading Profiles ───
PROFILE_PRESETS = {
    "conservative": {
        "risk_per_trade_pct": 1.0,
        "max_concurrent_trades": 3,
        "max_leverage": 2.0,
        "stop_loss_atr_multiple": 1.0,
        "take_profit_atr_multiple": 2.0,
    },
    "balanced": {
        "risk_per_trade_pct": 2.0,
        "max_concurrent_trades": 10,
        "max_leverage": 5.0,
        "stop_loss_atr_multiple": 1.5,
        "take_profit_atr_multiple": 2.25,
    },
    "aggressive": {
        "risk_per_trade_pct": 3.0,
        "max_concurrent_trades": 8,
        "max_leverage": 10.0,
        "stop_loss_atr_multiple": 2.0,
        "take_profit_atr_multiple": 3.0,
    },
}

# ─── Simplified User Controls → Config Mapping ───
USER_CONTROL_MAPPINGS = {
    "risk_mode": {
        "conservative": {
            "exposure.gross_max": 0.50,
            "exposure.net_max": 0.30,
            "confidence.min_trade": 0.72,
            "confidence.min_agreement": 7,
        },
        "balanced": {
            "exposure.gross_max": 0.80,
            "exposure.net_max": 0.50,
            "confidence.min_trade": 0.58,
            "confidence.min_agreement": 6,
        },
        "aggressive": {
            "exposure.gross_max": 1.00,
            "exposure.net_max": 0.70,
            "confidence.min_trade": 0.48,
            "confidence.min_agreement": 5,
        },
    },
    "trading_mode": {
        "manual": {"execution.auto_trade": False, "execution.require_approval": True},
        "approval": {"execution.auto_trade": True, "execution.require_approval": True},
        "auto": {"execution.auto_trade": True, "execution.require_approval": False},
    },
    "safety_mode": {
        "on": {"safe_mode.enabled": True},
        "off": {"safe_mode.enabled": False},
    },
}


def get_all_defaults() -> dict:
    """Return merged defaults dict."""
    merged = {}
    for group in [KILL_SWITCH_DEFAULTS, SAFE_MODE_DEFAULTS, DELEVERAGE_DEFAULTS,
                   CONFIDENCE_DEFAULTS, EXPOSURE_DEFAULTS, MARGINAL_RISK_DEFAULTS,
                   QUALITY_DEFAULTS, SCENARIO_DEFAULTS, READINESS_DEFAULTS,
                   WARMUP_DEFAULTS, EXPLORATION_DEFAULTS]:
        merged.update(group)
    return merged


def seed_defaults_if_needed() -> dict:
    """Seed default config values that don't already exist. Preserves user overrides."""
    from bahamut.admin.config import get_config, set_config, DEFAULTS
    defaults = get_all_defaults()
    seeded = {}
    for key, value in defaults.items():
        if key not in DEFAULTS:
            # Key not in the system at all — skip (would need schema update)
            continue
        current = get_config(key, value)
        if current == value:
            continue
        # Don't overwrite existing non-default values
    return seeded
