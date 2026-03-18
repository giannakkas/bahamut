from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel


class ConfigMeta(BaseModel):
    """Matches frontend ConfigMeta exactly."""

    value: Union[float, int, str, bool]
    type: Literal["float", "int", "bool", "string"]
    category: str
    description: str
    default: Union[float, int, str, bool]
    min: float | None = None
    max: float | None = None
    options: list[str] | None = None


# GET /admin/config returns Record<string, ConfigMeta>
# Represented as dict[str, ConfigMeta] in Python


class ConfigUpdatePayload(BaseModel):
    """Matches frontend ConfigUpdatePayload."""

    key: str
    value: Union[float, int, str, bool]


class ConfigOverride(BaseModel):
    """Matches frontend ConfigOverride."""

    key: str
    value: Union[float, int, str, bool]
    ttl: int
    created: str
    expires: str
    reason: str


class CreateOverrideRequest(BaseModel):
    """Request body for POST /admin/config/overrides."""

    key: str
    value: Union[float, int, str, bool]
    ttl: int
    reason: str
