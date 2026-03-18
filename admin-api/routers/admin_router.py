from typing import Annotated, Union

from fastapi import APIRouter, Depends, HTTPException, status

from auth import get_current_user
from models.audit import AuditLogEntry
from models.config import ConfigMeta, ConfigOverride, ConfigUpdatePayload, CreateOverrideRequest
from models.portfolio import AISuggestion, Alert, LearningPattern, SystemSummary
from services import store

router = APIRouter(prefix="/admin", tags=["admin"])

User = Annotated[str, Depends(get_current_user)]


# ─── Summary ──────────────────────────────────────────────────────


@router.get("/summary", response_model=SystemSummary)
async def get_summary(user: User) -> SystemSummary:
    """
    GET /admin/summary
    Response: SystemSummary (matches frontend exactly)
    """
    return store.get_summary()


# ─── Config ───────────────────────────────────────────────────────


@router.get("/config", response_model=dict[str, ConfigMeta])
async def get_config(user: User) -> dict[str, ConfigMeta]:
    """
    GET /admin/config
    Response: Record<string, ConfigMeta>
    """
    return store.get_config()


@router.post("/config", status_code=200)
async def update_config(body: ConfigUpdatePayload, user: User) -> dict[str, str]:
    """
    POST /admin/config
    Request:  { key: string, value: number | string | boolean }
    Response: { status: "ok" }
    """
    success = store.update_config(body.key, body.value, user=user)
    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to update '{body.key}': invalid key, type, or range",
        )
    return {"status": "ok"}


# ─── Overrides (MUST be before /config/{key} to avoid route capture) ─


@router.get("/config/overrides", response_model=list[ConfigOverride])
async def get_overrides(user: User) -> list[ConfigOverride]:
    """
    GET /admin/config/overrides
    Response: ConfigOverride[]
    """
    return store.get_overrides()


@router.post("/config/overrides", status_code=201)
async def create_override(body: CreateOverrideRequest, user: User) -> dict[str, str]:
    """
    POST /admin/config/overrides
    Request:  { key, value, ttl, reason }
    Response: { status: "created" }
    """
    success = store.create_override(body.key, body.value, body.ttl, body.reason)
    if not success:
        raise HTTPException(status_code=400, detail=f"Invalid config key '{body.key}'")
    return {"status": "created"}


@router.delete("/config/overrides/{key}", status_code=200)
async def remove_override(key: str, user: User) -> dict[str, str]:
    """
    DELETE /admin/config/overrides/{key}
    Response: { status: "removed" }
    """
    success = store.remove_override(key)
    if not success:
        raise HTTPException(status_code=404, detail=f"No active override for '{key}'")
    return {"status": "removed"}


@router.post("/config/reset/{key}", status_code=200)
async def reset_config(key: str, user: User) -> dict[str, str]:
    """
    POST /admin/config/reset/{key}
    Response: { status: "ok" }
    """
    success = store.reset_config(key, user=user)
    if not success:
        raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")
    return {"status": "ok"}


# Dynamic key route LAST — catches any /config/{key} not matched above
@router.get("/config/{key}", response_model=ConfigMeta)
async def get_config_key(key: str, user: User) -> ConfigMeta:
    """
    GET /admin/config/{key}
    Response: ConfigMeta
    """
    result = store.get_config_key(key)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")
    return result


# ─── Audit Log ────────────────────────────────────────────────────


@router.get("/audit-log", response_model=list[AuditLogEntry])
async def get_audit_log(user: User) -> list[AuditLogEntry]:
    """
    GET /admin/audit-log
    Response: AuditLogEntry[]
    """
    return store.get_audit_log()


# ─── Learning ─────────────────────────────────────────────────────


@router.get("/learning/patterns", response_model=list[LearningPattern])
async def get_learning_patterns(user: User) -> list[LearningPattern]:
    """
    GET /admin/learning/patterns
    Response: LearningPattern[]
    """
    return store.get_learning_patterns()


# ─── Alerts ───────────────────────────────────────────────────────


@router.get("/alerts", response_model=list[Alert])
async def get_alerts(user: User) -> list[Alert]:
    """
    GET /admin/alerts
    Response: Alert[]
    """
    return store.get_alerts()


@router.post("/alerts/{alert_id}/dismiss", status_code=200)
async def dismiss_alert(alert_id: int, user: User) -> dict[str, str]:
    """
    POST /admin/alerts/{id}/dismiss
    Response: { status: "dismissed" }
    """
    success = store.dismiss_alert(alert_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    return {"status": "dismissed"}


# ─── AI Optimization ──────────────────────────────────────────────


@router.get("/ai/optimize", response_model=list[AISuggestion])
async def get_ai_suggestions(user: User) -> list[AISuggestion]:
    """
    GET /admin/ai/optimize
    Response: AISuggestion[]
    """
    return store.get_ai_suggestions()
