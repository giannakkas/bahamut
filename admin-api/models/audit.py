from typing import Literal

from pydantic import BaseModel


class AuditLogEntry(BaseModel):
    """Matches frontend AuditLogEntry exactly."""

    id: int
    timestamp: str
    key: str
    old_value: str
    new_value: str
    source: Literal["user", "system"]
    user: str
