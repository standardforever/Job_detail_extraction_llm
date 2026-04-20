from __future__ import annotations

from services.domain_state import current_domain_record, set_domain_record
from state import JobScraperState

from services.job_detail_extraction import extract_job_detail_page_content
from services.navigation import navigate_to_url
from utils.logging import get_logger, log_event

logger = get_logger("job_detail_page_extraction_node")


async def job_detail_page_extraction_node(state: JobScraperState) -> JobScraperState:
    domain_key, record = current_domain_record(state)
    record = dict(record or {})
    record_errors = list(record.get("errors", []))
    record_metadata = dict(record.get("metadata", {}) or {})
    selected_job_url = record.get("selected_job_url") or state.get("selected_job_url")
    use_embedded_job_page = bool(record_metadata.get("use_embedded_job_page"))
    browser_session = state.get("browser_session")
    agent_tab = state.get("agent_tab")
    agent_index = state.get("agent_index", 0)
    if not selected_job_url:
        return {
            **state,
        }

    if use_embedded_job_page:
        extracted_content = record.get("extracted_content") or state.get("extracted_content")
        if extracted_content is None:
            error_message = "Embedded job page content is missing"
            record_errors.append(error_message)
            completed_job_urls = list(record.get("completed_job_urls") or state.get("completed_job_urls", []))
            if selected_job_url not in completed_job_urls:
                completed_job_urls.append(selected_job_url)
            updated_state: JobScraperState = {
                **state,
            }
            if domain_key and record is not None:
                record["errors"] = record_errors
                record["job_detail_extracted_content"] = None
                record["completed_job_urls"] = completed_job_urls
                record_metadata["job_detail_page_extraction_status"] = "extraction_failed"
                record_metadata["selected_job_url"] = selected_job_url
                record["metadata"] = record_metadata
                return set_domain_record(updated_state, domain_key, record)
            return updated_state

        log_event(
            logger,
            "info",
            "job_detail_reused_embedded_page url=%s markdown_length=%s",
            selected_job_url,
            len(extracted_content["markdown"]),
            domain=domain_key or "unknown",
            selected_job_url=selected_job_url,
            markdown_length=len(extracted_content["markdown"]),
            reused_embedded_page=True,
        )
        updated_state: JobScraperState = {
            **state,
        }
        if domain_key and record is not None:
            record["errors"] = record_errors
            record["job_detail_extracted_content"] = extracted_content
            record_metadata["job_detail_page_extraction_status"] = "extracted"
            record_metadata["selected_job_url"] = selected_job_url
            record_metadata["job_detail_extraction_sections"] = extracted_content.get("metadata", {}).get("sections", [])
            record_metadata["use_embedded_job_page"] = False
            record["metadata"] = record_metadata
            return set_domain_record(updated_state, domain_key, record)
        return updated_state

    navigation_result = await navigate_to_url(
        browser_session.page if browser_session else None,
        agent_index=agent_index,
        tab_handle=agent_tab["handle"] if agent_tab else None,
        url=selected_job_url,
        post_navigation_delay_ms=0,
    )
    if navigation_result["error"]:
        log_event(
            logger,
            "warning",
            "job_detail_navigation_failed url=%s error=%s",
            selected_job_url,
            navigation_result["error"],
            domain=domain_key or "unknown",
            selected_job_url=selected_job_url,
            error=navigation_result["error"],
        )
        error_message = f"Job detail navigation failed: {navigation_result['error']}"
        record_errors.append(error_message)
        completed_job_urls = list(record.get("completed_job_urls") or state.get("completed_job_urls", []))
        if selected_job_url not in completed_job_urls:
            completed_job_urls.append(selected_job_url)
        updated_state: JobScraperState = {
            **state,
        }
        if domain_key and record is not None:
            record["errors"] = record_errors
            record["job_detail_extracted_content"] = None
            record["completed_job_urls"] = completed_job_urls
            record_metadata["job_detail_page_extraction_status"] = "navigation_failed"
            record_metadata["selected_job_url"] = selected_job_url
            record_metadata["use_embedded_job_page"] = False
            record["metadata"] = record_metadata
            return set_domain_record(updated_state, domain_key, record)
        return updated_state

    extracted_content = await extract_job_detail_page_content(
        browser_session.page if browser_session else None,
        page_url=selected_job_url,
    )
    if extracted_content is None:
        log_event(
            logger,
            "warning",
            "job_detail_extraction_failed url=%s",
            selected_job_url,
            domain=domain_key or "unknown",
            selected_job_url=selected_job_url,
        )
        error_message = "Unable to extract job detail page content"
        record_errors.append(error_message)
        completed_job_urls = list(record.get("completed_job_urls") or state.get("completed_job_urls", []))
        if selected_job_url not in completed_job_urls:
            completed_job_urls.append(selected_job_url)
        updated_state: JobScraperState = {
            **state,
        }
        if domain_key and record is not None:
            record["errors"] = record_errors
            record["job_detail_extracted_content"] = None
            record["completed_job_urls"] = completed_job_urls
            record_metadata["job_detail_page_extraction_status"] = "extraction_failed"
            record_metadata["selected_job_url"] = selected_job_url
            record_metadata["use_embedded_job_page"] = False
            record["metadata"] = record_metadata
            return set_domain_record(updated_state, domain_key, record)
        return updated_state

    log_event(
        logger,
        "info",
        "job_detail_extracted url=%s markdown_length=%s",
        selected_job_url,
        len(extracted_content["markdown"]),
        domain=domain_key or "unknown",
        selected_job_url=selected_job_url,
        markdown_length=len(extracted_content["markdown"]),
        page_url=extracted_content.get("url"),
    )
    
    updated_state: JobScraperState = {
        **state,
    }
    if domain_key and record is not None:
        record["errors"] = record_errors
        record["job_detail_extracted_content"] = extracted_content
        record_metadata["job_detail_page_extraction_status"] = "extracted"
        record_metadata["selected_job_url"] = selected_job_url
        record_metadata["job_detail_extraction_sections"] = extracted_content.get("metadata", {}).get("sections", [])
        record_metadata["use_embedded_job_page"] = False
        record["metadata"] = record_metadata
        return set_domain_record(updated_state, domain_key, record)
    return updated_state
