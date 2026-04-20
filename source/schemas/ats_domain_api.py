from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ATSDomainUpsertRequest(BaseModel):
    domain: str = Field(..., min_length=1)
    is_ats: bool

    @field_validator("domain")
    @classmethod
    def _normalize_domain(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("domain is required")
        return normalized


class ATSDomainResponse(BaseModel):
    domain: str
    is_ats: bool | None
    status: str
    is_known_ats: bool
    is_known_non_ats: bool


class ATSDomainRegistryResponse(BaseModel):
    known_ats: list[str]
    known_non_ats: list[str]
    unknown_ats: list[str]
    counts: dict[str, int]
