"""
Bahamut Strategic Allocation — hybrid "profit core + research sleeve".

Splits every signal into one of two sleeves and sizes it accordingly:

  CORE  (full size)  — the proven edge: stock-LONG breakout/trend (v9, v5).
                        Live data: v9-stock +$5,074/93, v5-stock +$1,341/51.
  RESEARCH (small)   — everything else (crypto, shorts, v10 mean-reversion).
                        Net-negative historically; kept on for LEARNING at a
                        small risk fraction so it can gather data without
                        bleeding the book.

On top of the sleeve fraction, CORE trades get an EXPECTANCY multiplier: the
learning engine already measures each pattern's rolling expectancy (avg
R-multiple), so patterns that have PROVEN positive (mature, 15+ samples) size
up, and proven-marginal ones size down — amplifying real edge, never inventing
it. Bounded and mature-only so a lucky streak can't blow up sizing.

Everything is config-tunable (no redeploy) and fail-safe: any error returns a
neutral 1.0 multiplier, so this layer can never stop or distort trading by
failing.
"""
import structlog

logger = structlog.get_logger()

CORE_STRATEGIES = {"v9_breakout", "v5_base"}

# Config keys (registered in admin/config.py DEFAULTS)
_K_RESEARCH_FRAC = "allocation.research_risk_fraction"   # default 0.30
_K_EXP_ENABLED = "allocation.expectancy_sizing_enabled"  # default True
_K_EXP_MIN = "allocation.expectancy_size_min"            # default 0.80
_K_EXP_MAX = "allocation.expectancy_size_max"            # default 1.30

_DEFAULTS = {
    _K_RESEARCH_FRAC: 0.30,
    _K_EXP_ENABLED: True,
    _K_EXP_MIN: 0.80,
    _K_EXP_MAX: 1.30,
}


def _cfg(key):
    try:
        from bahamut.admin.config import get_config
        return get_config(key, _DEFAULTS[key])
    except Exception:
        return _DEFAULTS[key]


def classify_tier(strategy: str, asset_class: str, direction: str) -> str:
    """Return 'core' for the proven stock-long edge, else 'research'."""
    if (asset_class == "stock" and direction == "LONG"
            and strategy in CORE_STRATEGIES):
        return "core"
    return "research"


def _expectancy_multiplier(strategy: str, regime: str, asset_class: str) -> float:
    """Bounded size factor from learned expectancy. Neutral (1.0) unless the
    pattern is MATURE with a clear positive/negative expectancy."""
    if not _cfg(_K_EXP_ENABLED):
        return 1.0
    try:
        from bahamut.trading.learning_engine import get_pattern_trust
        t = get_pattern_trust(strategy, regime, asset_class)
        if t.get("maturity") != "mature" or t.get("total_trades", 0) < 15:
            return 1.0
        exp = float(t.get("expectancy", 0.0))  # avg R-multiple, last ~10 trades
        lo = float(_cfg(_K_EXP_MIN))
        hi = float(_cfg(_K_EXP_MAX))
        # Map expectancy → factor: 0R → 1.0, +0.4R → hi, -0.4R → lo (linear, clamped)
        factor = 1.0 + (exp / 0.4) * (hi - 1.0 if exp >= 0 else 1.0 - lo)
        return round(max(lo, min(hi, factor)), 3)
    except Exception:
        return 1.0


def strategic_risk_multiplier(strategy: str, asset_class: str,
                              direction: str, regime: str = "") -> dict:
    """Combined sizing multiplier for a signal.

    Returns {tier, base, expectancy, multiplier}. `multiplier` is what callers
    apply to risk_amount. Never raises.
    """
    try:
        tier = classify_tier(strategy, asset_class, direction)
        if tier == "core":
            base = 1.0
            exp_mult = _expectancy_multiplier(strategy, regime, asset_class)
        else:
            # Research sleeve: fixed small fraction, no expectancy amplification
            # (keep it genuinely small and bounded).
            base = float(_cfg(_K_RESEARCH_FRAC))
            exp_mult = 1.0
        mult = round(base * exp_mult, 3)
        return {"tier": tier, "base": base, "expectancy": exp_mult, "multiplier": mult}
    except Exception as e:
        logger.debug("strategic_size_skipped", error=str(e)[:100])
        return {"tier": "unknown", "base": 1.0, "expectancy": 1.0, "multiplier": 1.0}
