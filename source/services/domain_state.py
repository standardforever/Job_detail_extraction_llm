from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import tldextract

from state import JobScraperState


def get_domain_key_from_url(raw_url: str | None) -> str | None:
    value = str(raw_url or "").strip()
    if not value:
        return None

    parsed = urlparse(value if "://" in value else f"https://{value}")
    hostname = (parsed.netloc or parsed.path or "").strip().lower()
    if not hostname:
        return None

    ext = tldextract.extract(hostname)
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}".lower()
    return hostname.replace("www.", "", 1)


def _default_domain_record(domain_key: str) -> dict[str, Any]:
    return {
        "domain": domain_key,
        "input_urls": [],
        "current_input_url": None,
        "navigate_to": None,
        "navigation_results": [],
        "discovered_job_urls": [],
        "non_domain_career_urls": [],
        "career_page_analyses": {},
        "ats_check_result": None,
        "extracted_content": None,
        "page_category": None,
        "button_click_result": None,
        "job_page_features": None,
        "job_listing_page_analysis": None,
        "job_urls": [],
        "selected_job_url": None,
        "completed_job_urls": [],
        "job_detail_extracted_content": None,
        "structured_job_detail": None,
        "extracted_jobs": [],
        "errors": [],
        "metadata": {},
    }


def append_manual_review(
    record: dict[str, Any],
    reason: str,
    details: str | None = None,
) -> dict[str, Any]:
    record_copy = dict(record or {})
    metadata = dict(record_copy.get("metadata", {}) or {})
    manual_reviews = [
        dict(item)
        for item in list(metadata.get("manual_reviews", []) or [])
        if isinstance(item, dict)
    ]
    entry = {"reason": str(reason).strip()}
    normalized_details = str(details or "").strip()
    if normalized_details:
        entry["details"] = normalized_details
    manual_reviews.append(entry)
    metadata["manual_review_required"] = True
    metadata["manual_reviews"] = manual_reviews
    metadata["last_manual_review_reason"] = entry["reason"]
    if normalized_details:
        metadata["last_manual_review_details"] = normalized_details
    record_copy["metadata"] = metadata
    return record_copy


def ensure_domain_record(
    state: JobScraperState,
    raw_url: str | None = None,
) -> tuple[str | None, dict[str, dict[str, Any]], dict[str, Any] | None]:
    domain_key = get_domain_key_from_url(raw_url) or str(state.get("current_domain_key") or "").strip() or None
    records = {
        str(key): dict(value or {})
        for key, value in dict(state.get("domain_records", {}) or {}).items()
    }
    if not domain_key:
        return None, records, None

    record = dict(records.get(domain_key) or _default_domain_record(domain_key))
    input_url = str(raw_url or state.get("navigate_to") or "").strip()
    if input_url:
        existing_inputs = [str(item) for item in record.get("input_urls", []) if item]
        if input_url not in existing_inputs:
            existing_inputs.append(input_url)
        record["input_urls"] = existing_inputs
        record["current_input_url"] = input_url
        record["navigate_to"] = input_url
    record["domain"] = domain_key
    records[domain_key] = record
    return domain_key, records, record


def current_domain_record(state: JobScraperState) -> tuple[str | None, dict[str, Any] | None]:
    domain_key = str(state.get("current_domain_key") or "").strip() or None
    if not domain_key:
        domain_key = get_domain_key_from_url(state.get("navigate_to"))
    records = dict(state.get("domain_records", {}) or {})
    record = dict(records.get(domain_key) or {}) if domain_key and domain_key in records else None
    return domain_key, record


def current_domain_metadata(state: JobScraperState) -> dict[str, Any]:
    _, record = current_domain_record(state)
    return dict((record or {}).get("metadata", {}) or {})


def set_domain_record(
    state: JobScraperState,
    domain_key: str,
    record: dict[str, Any],
    extra_updates: dict[str, Any] | None = None,
) -> JobScraperState:
    records = {
        str(key): dict(value or {})
        for key, value in dict(state.get("domain_records", {}) or {}).items()
    }
    records[domain_key] = record

    updated_state: JobScraperState = {
        **state,
        "domain_records": records,
        "current_domain_key": domain_key,
    }
    if extra_updates:
        updated_state.update(extra_updates)
    return updated_state
