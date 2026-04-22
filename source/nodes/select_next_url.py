from __future__ import annotations

from services.domain_state import ensure_domain_record, get_domain_key_from_url, set_domain_record
from state import JobScraperState


TERMINAL_URL_EXTRACTION_STATUSES = {
    "domain_access_failed",
    "invalid_input",
    "no_candidates_found",
    "redirected",
    "session_not_established",
}

TERMINAL_CAREER_SCAN_STATUSES = {
    "external_ats_found",
    "external_job_board_found",
    "no_job_page_found",
}


def _terminal_record_inputs(state: JobScraperState) -> set[str]:
    completed: set[str] = set()
    for record in dict(state.get("domain_records", {}) or {}).values():
        if not isinstance(record, dict):
            continue
        metadata = dict(record.get("metadata", {}) or {})
        pipeline_status = str(metadata.get("pipeline_status") or "").strip().lower()
        url_status = str(metadata.get("url_extraction_status") or "").strip().lower()
        scan_status = str(metadata.get("career_page_scan_status") or "").strip().lower()
        if (
            pipeline_status != "failed"
            and url_status not in TERMINAL_URL_EXTRACTION_STATUSES
            and scan_status not in TERMINAL_CAREER_SCAN_STATUSES
            and not scan_status.endswith("_failed")
        ):
            continue
        for candidate in [record.get("current_input_url"), record.get("navigate_to"), *list(record.get("input_urls", []) or [])]:
            normalized = str(candidate or "").strip()
            if normalized:
                completed.add(normalized)
    return completed


async def select_next_url_node(state: JobScraperState) -> JobScraperState:
    assigned_urls = [url for url in state.get("assigned_urls", []) if url]
    completed_urls = set(state.get("completed_urls", [])) | _terminal_record_inputs(state)
    navigate_to = next((url for url in assigned_urls if url not in completed_urls), None)

    if navigate_to is None:
        return {
            **state,
            "navigate_to": None,
            "completed_urls": list(completed_urls),
        }

    navigate_domain_key = get_domain_key_from_url(navigate_to)
    existing_record = dict((state.get("domain_records", {}) or {}).get(navigate_domain_key) or {})
    existing_metadata = dict(existing_record.get("metadata", {}) or {})
    pipeline_status = str(existing_metadata.get("pipeline_status") or "").strip().lower()
    url_status = str(existing_metadata.get("url_extraction_status") or "").strip().lower()
    scan_status = str(existing_metadata.get("career_page_scan_status") or "").strip().lower()
    if (
        pipeline_status == "failed"
        or url_status in TERMINAL_URL_EXTRACTION_STATUSES
        or scan_status in TERMINAL_CAREER_SCAN_STATUSES
        or scan_status.endswith("_failed")
    ):
        completed_urls.add(navigate_to)
        return {
            **state,
            "navigate_to": None,
            "completed_urls": list(completed_urls),
        }

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
                "completed_urls": list(completed_urls),
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
        "completed_urls": list(completed_urls),
    }
