"""Pydantic request models (strict: unknown fields rejected)."""
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

_SID = r"^[a-f0-9]{16}$"
_CID = r"^[A-Za-z0-9_-]{20,64}$"


class ConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol: Literal["any", "udp", "tcp"] = "any"
    country: Optional[str] = Field(default=None, pattern=r"^[A-Za-z]{2}$")
    exclude: List[str] = Field(default_factory=list, max_length=10)
    min_quality: float = Field(default=0, ge=0, le=100)


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_id: str = Field(pattern=_CID)
    reason: Literal["timeout", "auth", "tls", "no_handshake", "network", "cancelled", "other"] = "other"


class SuccessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_id: str = Field(pattern=_CID)


class DisconnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_id: str = Field(pattern=_CID)


class VerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verified: bool = True
