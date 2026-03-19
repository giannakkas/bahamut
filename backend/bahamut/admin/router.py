import structlog
logger = structlog.get_logger()
"""Admin configuration and control API routes."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from bahamut.auth.router import get_current_user
from bahamut.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession

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
    summary = {
        "kill_switch": {"active": False},
        "safe_mode": {"active": False},
        "risk_level": "LOW",
        "last_cycle": None,
        "readiness": {"score": 0.5, "grade": "C", "components": {},
                      "pass": 0, "warn": 0, "fail": 0},
        "system_confidence": {},
        "config_overrides_count": 0,
    }
    try:
        from bahamut.portfolio.kill_switch import get_current_state
        ks = get_current_state()
        summary["kill_switch"] = {
            "active": ks.get("kill_switch_active", False),
            "triggers": ks.get("triggers", []),
        }
        summary["safe_mode"] = {
            "active": ks.get("safe_mode_active", False),
        }
    except Exception as e:
        logger.warning("admin_silent_error", error=str(e))

    try:
        from bahamut.readiness.checklist import run_readiness_check
        r = run_readiness_check()
        total = r.pass_count + r.warn_count + r.fail_count
        score = r.pass_count / total if total > 0 else 0
        grade = "A" if score >= 0.9 else "B" if score >= 0.7 else "C" if score >= 0.5 else "D"
        components = {}
        for c in getattr(r, 'checks', []):
            components[c.get("name", "unknown")] = c.get("status", "unknown")
        summary["readiness"] = {
            "overall": r.overall, "score": round(score, 2), "grade": grade,
            "pass": r.pass_count, "warn": r.warn_count, "fail": r.fail_count,
            "components": components,
        }
    except Exception as e:
        logger.warning("admin_silent_error", error=str(e))

    try:
        from bahamut.db.query import run_query_one
        row = run_query_one("SELECT completed_at FROM signal_cycles ORDER BY completed_at DESC LIMIT 1")
        if row:
            summary["last_cycle"] = str(row.get("completed_at", ""))
    except Exception:
        pass

    try:
        from bahamut.shared.degraded import get_degraded_flags
        flags = get_degraded_flags()
        critical = {"portfolio.kill_switch", "portfolio.scenario_risk", "auth.revocation"}
        has_critical = any(k in critical for k in flags)
        summary["risk_level"] = "HIGH" if has_critical else "MEDIUM" if flags else "LOW"
    except Exception:
        pass

    try:
        from bahamut.consensus.system_confidence import get_system_confidence
        bd = get_system_confidence()
        summary["system_confidence"] = bd.to_dict()
    except Exception as e:
        logger.warning("admin_silent_error", error=str(e))
        summary["system_confidence"] = {"error": "unavailable"}
    try:
        from bahamut.admin.config import get_overrides
        summary["config_overrides_count"] = len(get_overrides())
    except Exception as e:
        logger.warning("admin_silent_error", error=str(e))
    return summary


@router.get("/health")
async def health():
    return {"status": "healthy", "service": "admin-svc"}


# ─── User Management (admin only) ───

from pydantic import BaseModel, EmailStr


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: str = "viewer"  # viewer, trader, admin


@router.get("/users")
async def list_users(user=Depends(get_current_user), db=Depends(get_db)):
    """List all users (admin only)."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    from sqlalchemy import select
    from bahamut.models import User
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return [
        {
            "id": str(u.id), "email": u.email, "full_name": u.full_name,
            "role": u.role, "is_active": u.is_active,
            "last_login_at": str(u.last_login_at) if u.last_login_at else None,
            "created_at": str(u.created_at) if u.created_at else None,
        }
        for u in users
    ]


@router.post("/users")
async def create_user(req: CreateUserRequest, user=Depends(get_current_user), db=Depends(get_db)):
    """Create a new user (admin only). No invite code needed."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    from sqlalchemy import select
    from bahamut.models import User
    from passlib.context import CryptContext

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    # Check duplicate
    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    if req.role not in ("viewer", "trader", "admin"):
        raise HTTPException(status_code=400, detail="Role must be viewer, trader, or admin")

    new_user = User(
        email=req.email,
        password_hash=pwd_context.hash(req.password[:72]),
        full_name=req.full_name,
        role=req.role,
        workspace_id=user.workspace_id,
    )
    db.add(new_user)
    await db.commit()

    return {"status": "created", "email": req.email, "role": req.role}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    """Deactivate a user (admin only). Cannot delete yourself."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    if str(user.id) == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    from sqlalchemy import select
    from bahamut.models import User
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_active = False
    await db.commit()
    return {"status": "deactivated", "email": target.email}
