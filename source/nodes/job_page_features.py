from __future__ import annotations

from services.domain_state import current_domain_record, set_domain_record
from state import JobScraperState

from services.job_page_features import detect_job_page_features


async def job_page_features_node(state: JobScraperState) -> JobScraperState:
    domain_key, record = current_domain_record(state)
    record = dict(record or {})
    record_metadata = dict(record.get("metadata", {}) or {})
    page_category = record.get("page_category") or state.get("page_category")
    if not page_category or page_category.get("category") != "job_page":
        return {
            **state,
            "job_page_features": None,
        }

    browser_session = state.get("browser_session")
    features = await detect_job_page_features(
        record.get("extracted_content") or state.get("extracted_content"),
        browser_session.page if browser_session else None,
    )
    updated_state: JobScraperState = {
        **state,
        "job_page_features": features,
        "metadata": {
            **state.get("metadata", {}),
            "job_page_features_detected": True,
            "job_detail_target_count": features["job_detail_target_count"],
        },
    }
    if domain_key and record is not None:
        record["job_page_features"] = features
        record_metadata["job_page_features_detected"] = True
        record_metadata["job_detail_target_count"] = features["job_detail_target_count"]
        record["metadata"] = record_metadata
        return set_domain_record(updated_state, domain_key, record)
    return updated_state
