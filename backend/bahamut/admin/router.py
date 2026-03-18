"""Admin configuration and control API routes."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from bahamut.auth.router import get_current_user

router = APIRouter()


class ConfigUpdate(BaseModel):
    key: str
    value: str | float | int | bool


@router.get("/config")
async def get_all_config(user=Depends(get_current_user)):
    """Get all config keys with defaults, current values, types."""
    from bahamut.admin.config import get_config_metadata
    return get_config_metadata()


@router.get("/config/{key}")
async def get_single_config(key: str, user=Depends(get_current_user)):
    """Get a single config value."""
    from bahamut.admin.config import get_config, DEFAULTS
    if key not in DEFAULTS:
        return {"error": f"Unknown key: {key}"}
    return {"key": key, "value": get_config(key), "default": DEFAULTS[key]}


@router.post("/config")
async def set_config_value(body: ConfigUpdate, user=Depends(get_current_user)):
    """Set a config value (persisted, audited)."""
    from bahamut.admin.config import set_config
    return set_config(body.key, body.value, changed_by="admin")


@router.post("/config/reset/{key}")
async def reset_config_value(key: str, user=Depends(get_current_user)):
    """Reset a config key to its default."""
    from bahamut.admin.config import reset_config
    return reset_config(key, changed_by="admin")


@router.get("/config/overrides")
async def get_overrides(user=Depends(get_current_user)):
    """Get only keys that differ from defaults."""
    from bahamut.admin.config import get_overrides
    return get_overrides()


@router.get("/audit-log")
async def get_audit(limit: int = 50, user=Depends(get_current_user)):
    """Get config change audit log."""
    from bahamut.admin.config import get_audit_log
    return get_audit_log(limit)


@router.get("/summary")
async def admin_summary(user=Depends(get_current_user)):
    """Read-only system summary for admin dashboard."""
    summary = {}
    try:
        from bahamut.portfolio.kill_switch import get_current_state
        summary["kill_switch"] = get_current_state()
    except Exception:
        summary["kill_switch"] = {"error": "unavailable"}
    try:
        from bahamut.readiness.checklist import run_readiness_check
        r = run_readiness_check()
        summary["readiness"] = {"overall": r.overall, "pass": r.pass_count,
                                 "warn": r.warn_count, "fail": r.fail_count}
    except Exception:
        summary["readiness"] = {"error": "unavailable"}
    try:
        from bahamut.consensus.system_confidence import get_system_confidence
        bd = get_system_confidence()
        summary["system_confidence"] = bd.to_dict()
    except Exception:
        summary["system_confidence"] = {"error": "unavailable"}
    try:
        from bahamut.admin.config import get_overrides
        summary["config_overrides_count"] = len(get_overrides())
    except Exception:
        summary["config_overrides_count"] = 0
    return summary


@router.get("/health")
async def health():
    return {"status": "healthy", "service": "admin-svc"}
