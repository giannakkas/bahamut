"""
Bahamut.AI — Configuration Safety Guardrails

Prevents dangerous configurations that could lead to excessive risk.
All guardrail violations are rejected with clear error messages.
"""
import structlog

logger = structlog.get_logger()


def validate_user_control(control: str, value: str) -> tuple[bool, str]:
    """Validate a simplified user control change. Returns (ok, error_message)."""

    # Rule 1: Aggressive + auto trading not allowed during warmup
    if control == "risk_mode" and value == "aggressive":
        from bahamut.warmup import is_warmup_mode
        if is_warmup_mode():
            return False, ("Aggressive mode is not available during warmup. "
                          "The system needs more trading history before enabling aggressive settings.")

    if control == "trading_mode" and value == "auto":
        from bahamut.warmup import is_warmup_mode
        if is_warmup_mode():
            return False, ("Auto trading is not available during warmup. "
                          "Use Manual or Approval mode until the system is fully calibrated.")

    return True, ""


def validate_config_change(key: str, value) -> tuple[bool, str]:
    """Validate a raw config change. Returns (ok, error_message)."""

    # Rule: Cannot disable critical safety systems
    protected_keys = {
        "kill_switch.tail_risk_threshold": (0.05, 0.30, "Tail risk threshold must be between 5% and 30%"),
        "kill_switch.fragility_threshold": (0.50, 0.95, "Fragility threshold must be between 50% and 95%"),
        "exposure.gross_max": (0.20, 1.00, "Gross exposure max must be between 20% and 100%"),
        "confidence.min_trade": (0.30, 0.90, "Min trade confidence must be between 30% and 90%"),
    }

    if key in protected_keys:
        min_val, max_val, msg = protected_keys[key]
        try:
            v = float(value)
            if v < min_val or v > max_val:
                return False, msg
        except (ValueError, TypeError):
            return False, f"Value for {key} must be a number"

    # Rule: Cannot set max concurrent trades above 20
    if key == "safe_mode.max_concurrent_trades":
        try:
            if int(value) > 20:
                return False, "Max concurrent trades cannot exceed 20"
        except (ValueError, TypeError):
            pass

    # Rule: Cannot set risk_per_trade above 10%
    if key == "risk_per_trade_pct":
        try:
            if float(value) > 10.0:
                return False, "Risk per trade cannot exceed 10%"
        except (ValueError, TypeError):
            pass

    return True, ""
