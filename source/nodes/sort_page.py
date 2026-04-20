from __future__ import annotations

from services.domain_state import current_domain_record, set_domain_record
from state import JobScraperState


async def sort_page_node(state: JobScraperState) -> JobScraperState:
    domain_key, record = current_domain_record(state)
    record = dict(record or {})
    record_metadata = dict(record.get("metadata", {}) or {})
    features = record.get("job_page_features") or state.get("job_page_features")
    if not features or not features.get("sort_present"):
        return state

    updated_state: JobScraperState = {
        **state,
        "metadata": {
            **state.get("metadata", {}),
            "sort_status": "detected_not_applied",
            "sort_types": features.get("sort_types", []),
        },
    }
    if domain_key and record is not None:
        record_metadata["sort_status"] = "detected_not_applied"
        record_metadata["sort_types"] = features.get("sort_types", [])
        record["metadata"] = record_metadata
        return set_domain_record(updated_state, domain_key, record)
    return updated_state
