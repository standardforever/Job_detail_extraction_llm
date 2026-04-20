from __future__ import annotations

from services.domain_state import append_manual_review, ensure_domain_record, set_domain_record
from state import JobScraperState

from services.content_extraction import extract_page_content
from utils.logging import get_logger, log_event

logger = get_logger("extract_page_content_node")


async def extract_page_content_node(state: JobScraperState) -> JobScraperState:
    browser_session = state.get("browser_session")
    domain_key, records, record = ensure_domain_record(state, state.get("navigate_to"))
    record = dict(record or {})
    record_errors = list(record.get("errors", []))
    record_metadata = dict(record.get("metadata", {}) or {})
    navigation_results = list(record.get("navigation_results") or state.get("navigation_results", []))
    extract_attempt_count = int(record_metadata.get("extract_attempt_count", 0) or 0)

    if not state.get("session_established", False):
        error_message = "Cannot extract page content because the browser session was not established"
        record_errors.append(error_message)
        updated_state: JobScraperState = {
            **state,
        }
        if domain_key and record is not None:
            record["errors"] = record_errors
            record["extracted_content"] = None
            record_metadata["extract_status"] = "session_not_established"
            record["metadata"] = record_metadata
            return set_domain_record(updated_state, domain_key, record)
        return updated_state

    latest_navigation = navigation_results[-1] if navigation_results else None
    button_click_result = state.get("button_click_result")
    action_navigated = button_click_result and button_click_result.get("status") in {"clicked", "navigated"}
    if (latest_navigation is None or latest_navigation.get("status") != "navigated") and not action_navigated:
        updated_state: JobScraperState = {
            **state,
        }
        if domain_key and record is not None:
            record["errors"] = record_errors
            record["extracted_content"] = None
            record_metadata["extract_status"] = "navigation_not_ready"
            record["metadata"] = record_metadata
            return set_domain_record(updated_state, domain_key, record)
        return updated_state

    extracted_content = await extract_page_content(
        browser_session.page if browser_session is not None else None,
    )
    if extracted_content is None:
        log_event(
            logger,
            "warning",
            "page_content_extraction_failed navigate_to=%s",
            state.get("navigate_to"),
            domain=domain_key or "unknown",
            navigate_to=state.get("navigate_to"),
        )
        error_message = "Unable to extract page content"
        record_errors.append(error_message)
        updated_state: JobScraperState = {
            **state,
        }
        if domain_key and record is not None:
            record["errors"] = record_errors
            record["extracted_content"] = None
            record_metadata["extract_status"] = "failed"
            record_metadata["extract_attempt_count"] = extract_attempt_count + 1
            if extract_attempt_count + 1 >= 3:
                record = append_manual_review(record, "content_extraction_failed_after_retries", str(state.get("navigate_to") or ""))
                record_metadata = dict(record.get("metadata", {}) or {})
            record["metadata"] = record_metadata
            return set_domain_record(updated_state, domain_key, record)
        return updated_state

    log_event(
        logger,
        "info",
        "page_content_extracted navigate_to=%s markdown_length=%s",
        state.get("navigate_to"),
        len(extracted_content["markdown"]),
        domain=domain_key or "unknown",
        navigate_to=state.get("navigate_to"),
        markdown_length=len(extracted_content["markdown"]),
        page_url=extracted_content.get("url"),
    )
    updated_state: JobScraperState = {
        **state,
    }
    if domain_key and record is not None:
        record["errors"] = record_errors
        record["extracted_content"] = extracted_content
        record_metadata.update(
            {
                "extract_status": "extracted",
                "extract_attempt_count": 0,
                "extracted_markdown_length": len(extracted_content["markdown"]),
                "extraction_preparation": dict(extracted_content.get("metadata", {}).get("preparation", {})),
            }
        )
        record["metadata"] = record_metadata
        return set_domain_record(updated_state, domain_key, record)
    return updated_state
