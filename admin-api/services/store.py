"""
Persistence-backed data store for Bahamut TICC.

Uses SQLAlchemy with SQLite (swappable to PostgreSQL).
Public API matches what routers expect — no router changes needed.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Union

from models.audit import AuditLogEntry
from models.config import ConfigMeta, ConfigOverride
from models.portfolio import (
    AISuggestion,
    Alert,
    ConfidenceState,
    KillSwitchState,
    LearningPattern,
    MarginalRiskData,
    ReadinessComponents,
    ReadinessState,
    RiskContributor,
    SafeModeState,
    ScenarioResult,
    SystemSummary,
)
from services.database import (
    AlertRow,
    AuditRow,
    ConfigRow,
    OverrideRow,
    StateRow,
    get_session,
)

logger = logging.getLogger("bahamut.store")


# ─── Helpers ──────────────────────────────────────────────────────

def _parse_value(raw: str, type_: str) -> Union[float, int, str, bool]:
    if type_ == "bool":
        return raw.lower() in ("true", "1", "yes")
    if type_ == "int":
        return int(float(raw))
    if type_ == "float":
        return float(raw)
    return raw


def _row_to_meta(row: ConfigRow) -> ConfigMeta:
    return ConfigMeta(
        value=_parse_value(row.value, row.type),
        type=row.type,
        category=row.category,
        description=row.description,
        default=_parse_value(row.default_value, row.type),
        min=row.min_val,
        max=row.max_val,
        options=row.options.split(",") if row.options else None,
    )


def _get_state(session, key: str, default: str = "") -> str:
    row = session.query(StateRow).filter_by(key=key).first()
    return row.value if row else default


def _set_state(session, key: str, value: str) -> None:
    row = session.query(StateRow).filter_by(key=key).first()
    if row:
        row.value = value
    else:
        session.add(StateRow(key=key, value=value))


# ═══════════════════════════════════════════════════════════════════
# PUBLIC API — same signatures as before
# ═══════════════════════════════════════════════════════════════════


def get_config() -> dict[str, ConfigMeta]:
    with get_session() as session:
        rows = session.query(ConfigRow).all()
        return {r.key: _row_to_meta(r) for r in rows}


def get_config_key(key: str) -> ConfigMeta | None:
    with get_session() as session:
        row = session.query(ConfigRow).filter_by(key=key).first()
        return _row_to_meta(row) if row else None


def update_config(key: str, value: Union[float, int, str, bool], user: str = "user") -> bool:
    with get_session() as session:
        row = session.query(ConfigRow).filter_by(key=key).first()
        if not row:
            return False

        # Type validation
        if row.type == "float" and not isinstance(value, (int, float)):
            return False
        if row.type == "int":
            if isinstance(value, float) and value == int(value):
                value = int(value)
            elif not isinstance(value, int):
                return False
        if row.type == "bool" and not isinstance(value, bool):
            return False
        if row.type == "string" and not isinstance(value, str):
            return False

        # Range validation
        if row.type in ("float", "int"):
            if row.min_val is not None and float(value) < row.min_val:
                return False
            if row.max_val is not None and float(value) > row.max_val:
                return False

        # Options validation
        if row.options and str(value) not in row.options.split(","):
            return False

        old_value = row.value
        row.value = str(value)

        # Audit log
        session.add(AuditRow(
            timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            key=key,
            old_value=old_value,
            new_value=str(value),
            source="user",
            user=user,
        ))
        session.flush()
        logger.info(f"Config updated: {key} = {value} (was {old_value}) by {user}")
        return True


def reset_config(key: str, user: str = "user") -> bool:
    with get_session() as session:
        row = session.query(ConfigRow).filter_by(key=key).first()
        if not row:
            return False
        old_value = row.value
        row.value = row.default_value

        session.add(AuditRow(
            timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            key=key,
            old_value=old_value,
            new_value=row.default_value,
            source="user",
            user=user,
        ))
        logger.info(f"Config reset: {key} to default by {user}")
        return True


def get_overrides() -> list[ConfigOverride]:
    now = datetime.now(timezone.utc)
    with get_session() as session:
        # Prune expired
        session.query(OverrideRow).filter(
            OverrideRow.expires < now.isoformat().replace("+00:00", "Z")
        ).delete()
        session.flush()

        rows = session.query(OverrideRow).all()
        return [ConfigOverride(
            key=r.key, value=_parse_value(r.value, "string"),
            ttl=r.ttl, created=r.created, expires=r.expires, reason=r.reason,
        ) for r in rows]


def create_override(key: str, value: Union[float, int, str, bool], ttl: int, reason: str) -> bool:
    with get_session() as session:
        config_row = session.query(ConfigRow).filter_by(key=key).first()
        if not config_row:
            return False
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=ttl)
        session.add(OverrideRow(
            key=key,
            value=str(value),
            ttl=ttl,
            created=now.isoformat().replace("+00:00", "Z"),
            expires=expires.isoformat().replace("+00:00", "Z"),
            reason=reason,
        ))
        logger.info(f"Override created: {key} = {value} ttl={ttl}s reason={reason}")
        return True


def remove_override(key: str) -> bool:
    with get_session() as session:
        count = session.query(OverrideRow).filter_by(key=key).delete()
        return count > 0


def get_audit_log() -> list[AuditLogEntry]:
    with get_session() as session:
        rows = session.query(AuditRow).order_by(AuditRow.id.desc()).all()
        return [AuditLogEntry(
            id=r.id, timestamp=r.timestamp, key=r.key,
            old_value=r.old_value, new_value=r.new_value,
            source=r.source, user=r.user,
        ) for r in rows]


def get_summary() -> SystemSummary:
    with get_session() as session:
        safe_row = session.query(ConfigRow).filter_by(key="safe_mode.enabled").first()
        safe_active = safe_row and safe_row.value.lower() in ("true", "1")

        ks_active = _get_state(session, "kill_switch_active", "false").lower() == "true"
        ks_reason = _get_state(session, "kill_switch_reason", "") or None
        ks_last = _get_state(session, "kill_switch_last_triggered", "")

        return SystemSummary(
            kill_switch=KillSwitchState(active=ks_active, reason=ks_reason, last_triggered=ks_last),
            safe_mode=SafeModeState(active=bool(safe_active), level=1 if safe_active else 0),
            readiness=ReadinessState(score=0.87, grade="A-", components=ReadinessComponents(data=0.95, model=0.82, market=0.84)),
            confidence=ConfidenceState(score=0.79, trend="stable", history=[0.72, 0.74, 0.76, 0.79, 0.78, 0.79]),
            risk_level="MEDIUM",
            active_constraints=3,
            portfolio_value=127450.0,
            daily_pnl=1247.50,
            daily_pnl_pct=0.98,
            open_positions=7,
            agents_active=6,
            last_cycle=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )


def get_marginal_risk() -> MarginalRiskData:
    return MarginalRiskData(
        total_risk=0.128, expected_return=0.067, quality_ratio=0.72,
        contributors=[
            RiskContributor(asset="BTC", risk=0.042, weight=0.25, contribution_pct=32.8),
            RiskContributor(asset="ETH", risk=0.031, weight=0.18, contribution_pct=24.2),
            RiskContributor(asset="SOL", risk=0.019, weight=0.12, contribution_pct=14.8),
            RiskContributor(asset="AAPL", risk=0.012, weight=0.15, contribution_pct=9.4),
            RiskContributor(asset="TSLA", risk=0.010, weight=0.10, contribution_pct=7.8),
            RiskContributor(asset="NVDA", risk=0.008, weight=0.08, contribution_pct=6.3),
            RiskContributor(asset="GOLD", risk=0.006, weight=0.12, contribution_pct=4.7),
        ],
        scenarios=[
            ScenarioResult(name="Bull", probability=0.25, impact=0.12, color="#10b981"),
            ScenarioResult(name="Base", probability=0.30, impact=0.04, color="#06b6d4"),
            ScenarioResult(name="Bear", probability=0.25, impact=-0.08, color="#f59e0b"),
            ScenarioResult(name="Stress", probability=0.10, impact=-0.15, color="#ef4444"),
            ScenarioResult(name="Black Swan", probability=0.10, impact=-0.35, color="#7c3aed"),
        ],
    )


def toggle_kill_switch(active: bool) -> None:
    with get_session() as session:
        _set_state(session, "kill_switch_active", str(active).lower())
        _set_state(session, "kill_switch_reason", "Manual override" if active else "")
        _set_state(session, "kill_switch_last_triggered",
                   datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    logger.info(f"Kill switch set to {active}")


def get_kill_switch() -> dict[str, Any]:
    with get_session() as session:
        active = _get_state(session, "kill_switch_active", "false").lower() == "true"
        reason = _get_state(session, "kill_switch_reason", "") or None
        return {"active": active, "reason": reason}


def get_learning_patterns() -> list[LearningPattern]:
    return [
        LearningPattern(pattern="Momentum reversal on high volume", frequency=34, confidence=0.82, win_rate=0.71, last_seen="2026-03-18T08:12:00Z"),
        LearningPattern(pattern="Correlation breakdown BTC/ETH", frequency=12, confidence=0.74, win_rate=0.67, last_seen="2026-03-17T22:45:00Z"),
        LearningPattern(pattern="Volatility cluster post-FOMC", frequency=8, confidence=0.88, win_rate=0.75, last_seen="2026-03-15T19:00:00Z"),
        LearningPattern(pattern="Mean reversion after >2σ move", frequency=21, confidence=0.79, win_rate=0.69, last_seen="2026-03-18T06:30:00Z"),
        LearningPattern(pattern="Sentiment divergence signal", frequency=15, confidence=0.68, win_rate=0.60, last_seen="2026-03-16T14:20:00Z"),
        LearningPattern(pattern="Cross-asset momentum spillover", frequency=9, confidence=0.71, win_rate=0.63, last_seen="2026-03-17T11:00:00Z"),
    ]


def get_alerts() -> list[Alert]:
    with get_session() as session:
        rows = session.query(AlertRow).order_by(AlertRow.id.desc()).all()
        return [Alert(
            id=r.id, type=r.type, message=r.message,
            timestamp=r.timestamp, dismissed=r.dismissed,
        ) for r in rows]


def dismiss_alert(alert_id: int) -> bool:
    with get_session() as session:
        row = session.query(AlertRow).filter_by(id=alert_id).first()
        if not row:
            return False
        row.dismissed = True
        logger.info(f"Alert {alert_id} dismissed")
        return True


def get_ai_suggestions() -> list[AISuggestion]:
    config = get_config()
    suggestions = []

    checks = [
        ("confidence.min_trade", lambda v: v < 0.7, 0.70, "Recent win rate suggests higher threshold improves quality"),
        ("exposure.max_single", lambda v: v > 0.12, 0.12, "Correlation increase warrants lower single-asset exposure"),
        ("marginal_risk.threshold", lambda v: v > 0.13, 0.13, "Volatility regime shift detected — tighter risk controls recommended"),
        ("deleverage.speed", lambda v: v < 0.4, 0.4, "Faster deleverage improves drawdown recovery in current regime"),
        ("scenario.weight_bear", lambda v: v < 0.3, 0.30, "Macro indicators suggest elevated downside probability"),
    ]

    for key, condition, suggested, reason in checks:
        meta = config.get(key)
        if meta and isinstance(meta.value, (int, float)) and condition(float(meta.value)):
            suggestions.append(AISuggestion(
                key=key, current=float(meta.value), suggested=suggested, reason=reason,
            ))

    return suggestions
