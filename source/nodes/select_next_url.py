from __future__ import annotations

from services.domain_state import ensure_domain_record, set_domain_record
from state import JobScraperState


async def select_next_url_node(state: JobScraperState) -> JobScraperState:
    assigned_urls = [url for url in state.get("assigned_urls", []) if url]
    completed_urls = set(state.get("completed_urls", []))
    navigate_to = next((url for url in assigned_urls if url not in completed_urls), None)

    if navigate_to:
        domain_key, records, record = ensure_domain_record(state, navigate_to)
        if domain_key and record is not None:
            previous_input_url = record.get("current_input_url")
            record["current_input_url"] = navigate_to
            record["navigate_to"] = navigate_to
            record_metadata = dict(record.get("metadata", {}) or {})
            if navigate_to != previous_input_url:
                record_metadata["navigation_attempt_count"] = 0
                record_metadata["extract_attempt_count"] = 0
                record_metadata["page_category_loop_count"] = 0
                record_metadata["url_extraction_status"] = ""
            record_metadata["select_next_url_status"] = "ready"
            record["metadata"] = record_metadata
            records[domain_key] = record
            return set_domain_record(
                {
                    **state,
                    "navigate_to": navigate_to,
                    "domain_records": records,
                    "current_domain_key": domain_key,
                },
                domain_key,
                record,
                extra_updates={
                    "navigate_to": navigate_to,
                },
            )

    return {
        **state,
        "navigate_to": navigate_to,
    }
