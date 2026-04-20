from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import tldextract

from utils.logging import get_logger, log_event


logger = get_logger("ats_domain_registry")

DOMAIN_LIST_ROOT = Path(__file__).resolve().parents[1] / "domain_lists"
ATS_DOMAINS_FILE = DOMAIN_LIST_ROOT / "ats.json"
NON_ATS_DOMAINS_FILE = DOMAIN_LIST_ROOT / "non_ats.json"


def _write_json_atomic(path: Path, payload: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    temp_path.replace(path)


def _load_domain_list(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log_event(
            logger,
            "warning",
            "domain_list_load_failed path=%s error=%s",
            str(path),
            str(exc),
            domain="system",
            path=str(path),
            error=str(exc),
        )
        return set()
    if not isinstance(payload, list):
        return set()
    return {
        str(item).strip().lower()
        for item in payload
        if str(item).strip()
    }


def _ensure_registry_files() -> None:
    DOMAIN_LIST_ROOT.mkdir(parents=True, exist_ok=True)
    for path in (ATS_DOMAINS_FILE, NON_ATS_DOMAINS_FILE):
        if not path.exists():
            _write_json_atomic(path, [])


def extract_base_domain(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None

    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    hostname = (parsed.netloc or parsed.path or "").strip().lower().removeprefix("www.")
    if not hostname:
        return None

    extracted = tldextract.extract(hostname)
    if extracted.domain and extracted.suffix:
        return f"{extracted.domain}.{extracted.suffix}".lower()
    return hostname if "." in hostname else None


def validate_domain(value: str) -> str:
    normalized = extract_base_domain(value)
    if not normalized or "." not in normalized:
        raise ValueError("Invalid domain")
    return normalized


def get_domain_registry() -> dict[str, set[str]]:
    _ensure_registry_files()
    return {
        "ats": _load_domain_list(ATS_DOMAINS_FILE),
        "non_ats": _load_domain_list(NON_ATS_DOMAINS_FILE),
    }


def list_domain_registry_snapshot() -> dict[str, Any]:
    registry = get_domain_registry()
    known_ats = sorted(registry["ats"])
    known_non_ats = sorted(registry["non_ats"])
    unknown_ats: list[str] = []
    return {
        "known_ats": known_ats,
        "known_non_ats": known_non_ats,
        "unknown_ats": unknown_ats,
        "counts": {
            "known_ats": len(known_ats),
            "known_non_ats": len(known_non_ats),
            "unknown_ats": len(unknown_ats),
        },
    }


def set_domain_classification(domain: str, is_ats: bool) -> dict[str, Any]:
    normalized = validate_domain(domain)
    registry = get_domain_registry()
    ats_domains = set(registry["ats"])
    non_ats_domains = set(registry["non_ats"])

    if is_ats:
        ats_domains.add(normalized)
        non_ats_domains.discard(normalized)
    else:
        non_ats_domains.add(normalized)
        ats_domains.discard(normalized)

    _write_json_atomic(ATS_DOMAINS_FILE, sorted(ats_domains))
    _write_json_atomic(NON_ATS_DOMAINS_FILE, sorted(non_ats_domains))

    log_event(
        logger,
        "info",
        "domain_classification_saved domain=%s is_ats=%s",
        normalized,
        is_ats,
        domain=normalized,
        is_ats=is_ats,
    )

    return get_domain_classification(normalized)


def get_domain_classification(domain: str) -> dict[str, Any]:
    normalized = validate_domain(domain)
    registry = get_domain_registry()
    is_known_ats = normalized in registry["ats"]
    is_known_non_ats = normalized in registry["non_ats"]
    if is_known_ats:
        status = "known_ats"
    elif is_known_non_ats:
        status = "known_non_ats"
    else:
        status = "unlisted"
    return {
        "domain": normalized,
        "is_ats": True if is_known_ats else False if is_known_non_ats else None,
        "status": status,
        "is_known_ats": is_known_ats,
        "is_known_non_ats": is_known_non_ats,
    }


def _derive_lookup_domain(result: dict[str, Any], page_url: str | None = None, main_domain: str | None = None) -> str | None:
    apply_url = str(result.get("apply_url") or "").strip() or None
    provider = str(result.get("provider") or result.get("ats_provider") or "").strip() or None
    is_ats = result.get("ats_detected", result.get("is_ats"))

    if apply_url:
        return extract_base_domain(apply_url)
    if provider and "." in provider:
        return extract_base_domain(provider)
    if is_ats is False and page_url:
        return extract_base_domain(page_url)
    if is_ats is False and main_domain:
        return extract_base_domain(main_domain)
    return None


def reconcile_ats_result(result: dict[str, Any], *, page_url: str | None = None, main_domain: str | None = None) -> dict[str, Any]:
    reconciled = dict(result or {})
    lookup_domain = _derive_lookup_domain(reconciled, page_url=page_url, main_domain=main_domain)
    registry_status = "not_checked"
    registry_agreement = "neutral"

    if lookup_domain:
        classification = get_domain_classification(lookup_domain)
        is_detected_ats = reconciled.get("ats_detected", reconciled.get("is_ats"))
        if classification["status"] == "known_ats":
            if is_detected_ats is True:
                registry_status = "known_ats"
                registry_agreement = "agree"
            elif is_detected_ats is False:
                registry_status = "conflict_known_ats_listed_as_non_ats"
                registry_agreement = "conflict"
            else:
                registry_status = "known_ats"
        elif classification["status"] == "known_non_ats":
            if is_detected_ats is True:
                registry_status = "conflict_known_non_ats_listed_as_ats"
                registry_agreement = "conflict"
            elif is_detected_ats is False:
                registry_status = "known_non_ats"
                registry_agreement = "agree"
            else:
                registry_status = "known_non_ats"
        else:
            registry_status = "unlisted"

    reconciled["ats_lookup_domain"] = lookup_domain
    reconciled["domain_registry_status"] = registry_status
    reconciled["registry_agreement"] = registry_agreement
    return reconciled
