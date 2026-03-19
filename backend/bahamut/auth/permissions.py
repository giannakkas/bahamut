"""
Bahamut.AI — Role-Based Permission System

Roles:
  - user: standard trading user
  - admin: operator with config/monitoring access
  - super_admin: full system control (Chris only)

Super admin is enforced by BOTH role AND email allowlist.
"""
import structlog
from fastapi import HTTPException, Depends

logger = structlog.get_logger()

# Hard-coded super admin allowlist — cannot be overridden
SUPER_ADMIN_EMAILS = {"chris@bahamut.ai"}

# Role hierarchy
ROLE_LEVELS = {
    "user": 0,
    "viewer": 0,
    "trader": 1,
    "admin": 2,
    "super_admin": 3,
}


def get_role_level(role: str) -> int:
    return ROLE_LEVELS.get(role, 0)


def is_super_admin(user) -> bool:
    """Check if user is a verified super admin (role + email)."""
    return (
        getattr(user, "role", "") == "super_admin"
        and getattr(user, "email", "") in SUPER_ADMIN_EMAILS
    )


def is_admin_or_above(user) -> bool:
    """Check if user is admin or super_admin."""
    return get_role_level(getattr(user, "role", "")) >= ROLE_LEVELS["admin"]


def is_trader_or_above(user) -> bool:
    """Check if user is trader, admin, or super_admin."""
    return get_role_level(getattr(user, "role", "")) >= ROLE_LEVELS["trader"]


def require_admin(user):
    """Dependency: require admin or super_admin role."""
    if not is_admin_or_above(user):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def require_super_admin(user):
    """Dependency: require verified super admin (role + email check)."""
    if not is_super_admin(user):
        logger.warning("super_admin_access_denied",
                        email=getattr(user, "email", "unknown"),
                        role=getattr(user, "role", "unknown"))
        raise HTTPException(status_code=403, detail="Super admin access required")
    return user


def require_trader(user):
    """Dependency: require trader or above."""
    if not is_trader_or_above(user):
        raise HTTPException(status_code=403, detail="Trader access required")
    return user


def get_user_capabilities(user) -> dict:
    """Return capability flags for the current user's role."""
    role = getattr(user, "role", "user")
    sa = is_super_admin(user)

    return {
        "role": role,
        "is_super_admin": sa,
        "can_trade": get_role_level(role) >= ROLE_LEVELS["trader"],
        "can_admin": get_role_level(role) >= ROLE_LEVELS["admin"],
        "can_super_admin": sa,
        # Feature access
        "can_view_config": get_role_level(role) >= ROLE_LEVELS["admin"],
        "can_edit_config": sa,
        "can_view_overrides": get_role_level(role) >= ROLE_LEVELS["admin"],
        "can_manage_overrides": get_role_level(role) >= ROLE_LEVELS["admin"],
        "can_view_audit": get_role_level(role) >= ROLE_LEVELS["admin"],
        "can_manage_users": get_role_level(role) >= ROLE_LEVELS["admin"],
        "can_view_learning": get_role_level(role) >= ROLE_LEVELS["admin"],
        "can_view_raw_internals": sa,
        "can_force_overrides": sa,
        "can_dangerous_actions": sa,
        "can_edit_roles": sa,
        "can_kill_switch": get_role_level(role) >= ROLE_LEVELS["trader"],
    }
