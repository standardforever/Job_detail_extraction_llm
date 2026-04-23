from __future__ import annotations

import asyncio

from state import JobScraperState

from core.config import get_settings
from services.domain_state import append_manual_review, ensure_domain_record, set_domain_record
from services.navigation import navigate_to_url
from utils.logging import get_logger, log_event

logger = get_logger("navigation_node")


async def navigation_node(state: JobScraperState) -> JobScraperState:
    
    settings = get_settings()
    browser_session = state.get("browser_session")
    agent_index = state.get("agent_index", 0)
    outer_navigate_to = state.get("navigate_to")
    agent_tab = state.get("agent_tab")
    completed_urls = list(state.get("completed_urls", []))
    domain_key, records, record = ensure_domain_record(state, outer_navigate_to)
    record = dict(record or {})
    record_errors = list(record.get("errors", []))
    record_metadata = dict(record.get("metadata", {}) or {})
    navigation_attempt_count = int(record_metadata.get("navigation_attempt_count", 0) or 0)
    navigate_to = str(record_metadata.get("current_candidate_url") or outer_navigate_to or "").strip() or None
    visited_candidate_urls = [str(url) for url in (record_metadata.get("visited_candidate_urls") or []) if url]

    if not state.get("session_established", False):
        error_message = f"Cannot navigate because the browser session was not established url {navigate_to}"
        record_errors.append(error_message)
        updated_state: JobScraperState = {
            **state,
        }
        if domain_key and record is not None:
            record["errors"] = record_errors
            record["navigation_results"] = []
            record_metadata["navigation_status"] = "session_not_established"
            record["metadata"] = record_metadata
            return set_domain_record(updated_state, domain_key, record)
        return updated_state

    if not navigate_to:
        return {
            **state,
        }

    if navigate_to in visited_candidate_urls:
        updated_state: JobScraperState = {
            **state,
            "completed_urls": completed_urls,
        }
        if domain_key and record is not None:
            record["errors"] = record_errors
            record["navigation_results"] = []
            record_metadata["navigation_status"] = "already_visited"
            record = append_manual_review(record, "navigation_target_already_visited", navigate_to)
            return set_domain_record(updated_state, domain_key, record)
        return updated_state

    if not agent_tab:
        error_message = f"Cannot navigate because the agent tab was not prepared {navigate_to}"
        record_errors.append(error_message)
        updated_state: JobScraperState = {
            **state,
        }
        if domain_key and record is not None:
            record["errors"] = record_errors
            record["navigation_results"] = []
            record_metadata["navigation_status"] = "missing_agent_tab"
            record["metadata"] = record_metadata
            return set_domain_record(updated_state, domain_key, record)
        return updated_state

    navigation_result = await navigate_to_url(
        browser_session.page if browser_session is not None else None,
        agent_index=agent_index,
        tab_handle=agent_tab["handle"],
        url=navigate_to,
        post_navigation_delay_ms=0,
    )
    navigation_results = [navigation_result]
    log_event(
        logger,
        "info",
        "navigation_result agent_index=%s url=%s status=%s",
        agent_index,
        navigate_to,
        navigation_result["status"],
        domain=domain_key or "unknown",
        agent_index=agent_index,
        navigate_to=navigate_to,
        navigation_status=navigation_result["status"],
        current_url=navigation_result.get("current_url"),
    )

    navigation_errors = [result["error"] for result in navigation_results if result["error"]]
    if browser_session is None:
        error_message = "Unable to attach a Playwright page for navigation"
        record_errors.append(error_message)
    else:
        record_errors.extend(navigation_errors)

    next_navigation_attempt_count = 0 if navigation_result["status"] == "navigated" else navigation_attempt_count + 1

    if navigate_to == outer_navigate_to and navigation_result["status"] == "navigated" and navigate_to not in completed_urls:
        completed_urls.append(navigate_to)
    if navigate_to == outer_navigate_to and navigation_result["status"] != "navigated" and next_navigation_attempt_count >= 3 and navigate_to not in completed_urls:
        completed_urls.append(navigate_to)
    if navigation_result["status"] == "navigation_non_web_url":
        if outer_navigate_to and outer_navigate_to not in completed_urls:
            completed_urls.append(outer_navigate_to)
        if navigate_to not in completed_urls:
            completed_urls.append(navigate_to)

    if navigation_result["status"] == "navigated" and settings.post_navigation_delay_ms > 0:
        await asyncio.sleep(settings.post_navigation_delay_ms / 1000)

    updated_state: JobScraperState = {
        **state,
        "completed_urls": completed_urls,
    }
    if domain_key and record is not None:
        record["errors"] = record_errors
        record["navigation_results"] = navigation_results
        visited_candidate_urls = [*visited_candidate_urls]
        current_url = str(navigation_result.get("current_url") or navigate_to or "").strip()
        if current_url and current_url not in visited_candidate_urls:
            visited_candidate_urls.append(current_url)
        record_metadata.update(
            {
                "last_navigate_to": navigate_to,
                "navigated_url_count": sum(1 for result in navigation_results if result["status"] == "navigated"),
                "navigation_status": navigation_result["status"],
                "navigation_attempt_count": 3 if navigation_result["status"] == "navigation_non_web_url" else next_navigation_attempt_count,
                "post_navigation_delay_ms": settings.post_navigation_delay_ms,
                "visited_candidate_urls": visited_candidate_urls,
            }
        )
        if navigation_result["status"] == "navigation_non_web_url":
            record_metadata["career_page_scan_status"] = "no_job_page_found"
            record_metadata["non_web_navigation_target_url"] = navigate_to
        if navigation_result["status"] in {"navigation_failed", "navigation_timeout"} and next_navigation_attempt_count >= 3:
            record = append_manual_review(record, "navigation_failed_after_retries", navigate_to)
            record_metadata = dict(record.get("metadata", {}) or {})
        record["metadata"] = record_metadata
        return set_domain_record(updated_state, domain_key, record)
    return updated_state
