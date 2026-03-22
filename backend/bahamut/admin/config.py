"""
Bahamut.AI Admin Configuration Service

Single source of truth for all tunable system constants.
Replaces scattered hardcoded values across modules.

Features:
  - Sane defaults for every config key
  - Persisted overrides in DB (admin_config table)
  - Versioned change log (admin_audit_log table)
  - In-memory cache with TTL
  - Type validation on set
  - get_config(key) → value  from anywhere in the codebase
"""
import json
import time
import structlog
from dataclasses import dataclass
from copy import deepcopy

logger = structlog.get_logger()

# ══════════════════════════════════════════
# DEFAULTS — every tunable constant in one place
# ══════════════════════════════════════════

DEFAULTS = {
    # ── Execution ──
    "execution.auto_approve": False,  # When True, APPROVAL trades execute automatically

    # ── Scenario weights ──
    "scenario.weight.risk_off": 0.30,
    "scenario.weight.volatility_spike": 0.25,
    "scenario.weight.crypto_shock": 0.20,
    "scenario.weight.usd_shock": 0.15,
    "scenario.weight.risk_on": 0.10,

    # ── Tail risk thresholds ──
    "scenario.tail_risk.warn": 0.05,
    "scenario.tail_risk.approval": 0.08,
    "scenario.tail_risk.block": 0.12,

    # ── Marginal risk thresholds ──
    "marginal_risk.warn": 0.02,
    "marginal_risk.approval": 0.04,
    "marginal_risk.block": 0.06,

    # ── Quality ratio thresholds ──
    "quality_ratio.min_allow": 0.5,
    "quality_ratio.strong": 2.0,
    "quality_ratio.reduce_below": 1.0,

    # ── Exposure limits ──
    "exposure.gross_max": 0.80,
    "exposure.net_max": 0.50,
    "exposure.single_class_max": 0.40,
    "exposure.single_theme_max": 0.30,
    "exposure.single_asset_max": 0.15,

    # ── Kill switch / safe mode ──
    "kill_switch.tail_risk_threshold": 0.25,
    "kill_switch.fragility_threshold": 0.80,
    "kill_switch.combined_stress_threshold": 0.70,
    "safe_mode.enabled": False,
    "safe_mode.max_position_pct": 0.01,
    "safe_mode.max_concurrent_trades": 2,
    "deleverage.fragility_trigger": 0.75,
    "deleverage.max_close_per_cycle": 1,

    # ── Allocator ──
    "allocator.min_quality_to_keep": 0.35,
    "allocator.min_upgrade_margin": 0.20,
    "allocator.max_reallocs_per_hour": 3,

    # ── System confidence weights ──
    "confidence.trust_stability_weight": 0.30,
    "confidence.disagreement_trend_weight": 0.25,
    "confidence.recent_performance_weight": 0.30,
    "confidence.calibration_health_weight": 0.15,

    # ── Profile limits ──
    "profile.conservative.max_daily_dd": 0.02,
    "profile.conservative.max_weekly_dd": 0.04,
    "profile.conservative.max_trades": 3,
    "profile.conservative.min_score": 0.65,
    "profile.balanced.max_daily_dd": 0.03,
    "profile.balanced.max_weekly_dd": 0.06,
    "profile.balanced.max_trades": 10,
    "profile.balanced.min_score": 0.55,
    "profile.aggressive.max_daily_dd": 0.05,
    "profile.aggressive.max_weekly_dd": 0.10,
    "profile.aggressive.max_trades": 8,
    "profile.aggressive.min_score": 0.45,

    # ── Readiness ──
    "readiness.min_closed_trades": 30,
    "readiness.min_win_rate": 0.45,
    "readiness.min_profit_factor": 1.2,
    "readiness.max_consecutive_losses": 5,
    "readiness.calibration_max_age_hours": 48,
    "readiness.stress_score_min": 0.50,

    # ── Notifications: Telegram ──
    "notify.telegram.enabled": False,
    "notify.telegram.bot_token": "",
    "notify.telegram.chat_id": "",

    # ── Notifications: Email (Brevo SMTP) ──
    "notify.email.enabled": False,
    "notify.email.smtp_host": "smtp-relay.brevo.com",
    "notify.email.smtp_port": 587,
    "notify.email.smtp_user": "",
    "notify.email.smtp_pass": "",       # Brevo API key (xkeysib-...)
    "notify.email.smtp_key": "",        # Brevo SMTP key (for SMTP fallback)
    "notify.email.from_email": "",
    "notify.email.to_email": "",

    # ── Notifications: Alert levels ──
    "notify.level.critical": True,      # Send CRITICAL alerts
    "notify.level.warning": True,       # Send WARNING alerts
    "notify.level.info": False,         # Send INFO alerts (trades/regime changes)
}

# Type constraints for validation
_TYPES = {k: type(v) for k, v in DEFAULTS.items()}

# ══════════════════════════════════════════
# CACHE
# ══════════════════════════════════════════

_cache: dict = {"overrides": {}, "loaded_at": 0}
_CACHE_TTL = 120  # 2 min


def get_config(key: str, default=None):
    """Get a config value. Checks overrides first, then defaults."""
    _ensure_cache()
    if key in _cache["overrides"]:
        return _cache["overrides"][key]
    if key in DEFAULTS:
        return DEFAULTS[key]
    return default


def get_all_config() -> dict:
    """Get merged config (defaults + overrides)."""
    _ensure_cache()
    merged = deepcopy(DEFAULTS)
    merged.update(_cache["overrides"])
    return merged


def get_overrides() -> dict:
    """Get only the keys that have been overridden from defaults."""
    _ensure_cache()
    return deepcopy(_cache["overrides"])


def set_config(key: str, value, changed_by: str = "system") -> dict:
    """Set a config value. Validates type, persists, logs audit."""
    if key not in DEFAULTS:
        return {"error": f"Unknown config key: {key}"}

    expected_type = _TYPES[key]
    if not isinstance(value, expected_type):
        # Try coercion for common cases
        try:
            if expected_type is float:
                value = float(value)
            elif expected_type is int:
                value = int(value)
            elif expected_type is bool:
                value = value in (True, "true", "True", 1, "1")
            elif expected_type is str:
                value = str(value)
            else:
                return {"error": f"Type mismatch: expected {expected_type.__name__}, got {type(value).__name__}"}
        except (ValueError, TypeError):
            return {"error": f"Cannot convert {value} to {expected_type.__name__}"}

    old_value = get_config(key)
    _persist_override(key, value)
    _log_audit(key, old_value, value, changed_by)
    _cache["overrides"][key] = value

    logger.info("config_changed", key=key, old=old_value, new=value, by=changed_by)
    return {"key": key, "old_value": old_value, "new_value": value, "changed_by": changed_by}


def reset_config(key: str, changed_by: str = "system") -> dict:
    """Reset a config key to its default value."""
    if key not in DEFAULTS:
        return {"error": f"Unknown config key: {key}"}
    old = get_config(key)
    _delete_override(key)
    _log_audit(key, old, DEFAULTS[key], changed_by, action="reset")
    _cache["overrides"].pop(key, None)
    return {"key": key, "reset_to": DEFAULTS[key]}


def get_audit_log(limit: int = 50) -> list[dict]:
    """Get recent config change history."""
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT config_key, old_value, new_value, changed_by, action, created_at
                FROM admin_audit_log ORDER BY created_at DESC LIMIT :l
            """), {"l": limit}).mappings().all()
            return [dict(r) for r in rows]
    except Exception as e:

        logger.warning("admin_config_silent_error", error=str(e))
        return []


def get_config_metadata() -> list[dict]:
    """Get all config keys with defaults, current values, and types."""
    _ensure_cache()
    result = []
    for key, default in sorted(DEFAULTS.items()):
        current = _cache["overrides"].get(key, default)
        result.append({
            "key": key,
            "default": default,
            "current": current,
            "type": _TYPES[key].__name__,
            "overridden": key in _cache["overrides"],
            "category": key.split(".")[0],
        })
    return result


# ══════════════════════════════════════════
# DB PERSISTENCE
# ══════════════════════════════════════════

def _ensure_tables():
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            pass  # Schema managed by db.schema.tables
            pass  # Schema managed by db.schema.tables
            conn.commit()
    except Exception as e:

        logger.warning("admin_config_silent_error", error=str(e))
        pass


def _ensure_cache():
    now = time.time()
    if now - _cache["loaded_at"] < _CACHE_TTL and _cache["overrides"] is not None:
        return
    _load_overrides()


def _load_overrides():
    try:
        _ensure_tables()
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            rows = conn.execute(text("SELECT key, value FROM admin_config")).mappings().all()
            overrides = {}
            for r in rows:
                key = r["key"]
                if key in DEFAULTS:
                    expected_type = _TYPES[key]
                    try:
                        if expected_type is bool:
                            overrides[key] = r["value"] in ("True", "true", "1")
                        elif expected_type is float:
                            overrides[key] = float(r["value"])
                        elif expected_type is int:
                            overrides[key] = int(r["value"])
                        else:
                            overrides[key] = r["value"]
                    except (ValueError, TypeError):
                        pass
            _cache["overrides"] = overrides
            _cache["loaded_at"] = time.time()
    except Exception as e:

        logger.warning("admin_config_silent_error", error=str(e))
        _cache["overrides"] = {}
        _cache["loaded_at"] = time.time()


def _persist_override(key, value):
    try:
        _ensure_tables()
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO admin_config (key, value, updated_at) VALUES (:k, :v, NOW())
                ON CONFLICT (key) DO UPDATE SET value = :v, updated_at = NOW()
            """), {"k": key, "v": str(value)})
            conn.commit()
    except Exception as e:
        logger.warning("config_persist_failed", key=key, error=str(e))


def _delete_override(key):
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            conn.execute(text("DELETE FROM admin_config WHERE key = :k"), {"k": key})
            conn.commit()
    except Exception as e:

        logger.warning("admin_config_silent_error", error=str(e))
        pass


def _log_audit(key, old_value, new_value, changed_by, action="set"):
    try:
        _ensure_tables()
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO admin_audit_log (config_key, old_value, new_value, changed_by, action)
                VALUES (:k, :o, :n, :b, :a)
            """), {"k": key, "o": str(old_value), "n": str(new_value),
                   "b": changed_by, "a": action})
            conn.commit()
    except Exception as e:

        logger.warning("admin_config_silent_error", error=str(e))
        pass
