from __future__ import annotations

from fastapi import APIRouter, HTTPException

from schemas.ats_domain_api import ATSDomainRegistryResponse, ATSDomainResponse, ATSDomainUpsertRequest
from services.ats_domain_registry import (
    get_domain_classification,
    list_domain_registry_snapshot,
    set_domain_classification,
)


router = APIRouter(tags=["ats-domains"])


@router.get("/ats-domains", response_model=ATSDomainRegistryResponse)
async def list_ats_domains() -> ATSDomainRegistryResponse:
    return ATSDomainRegistryResponse(**list_domain_registry_snapshot())


@router.post("/ats-domains", response_model=ATSDomainResponse)
async def upsert_ats_domain(payload: ATSDomainUpsertRequest) -> ATSDomainResponse:
    try:
        result = set_domain_classification(payload.domain, payload.is_ats)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ATSDomainResponse(**result)


@router.get("/ats-domains/{domain}", response_model=ATSDomainResponse)
async def get_ats_domain(domain: str) -> ATSDomainResponse:
    try:
        result = get_domain_classification(domain)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ATSDomainResponse(**result)
