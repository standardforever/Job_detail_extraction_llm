from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import tldextract

from services.carrer_url_extractor import UrlExtractor
from services.domain_state import ensure_domain_record, set_domain_record
from utils.logging import get_logger, log_event
from state import JobScraperState

logger = get_logger("url_extraction_node")


def _dedupe_urls(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _dedupe_career_items(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", "") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(item)
    return result


def _normalize_input_target(raw_value: str) -> dict[str, Any]:
    cleaned = str(raw_value or "").strip()
    with_scheme = cleaned if "://" in cleaned else f"https://{cleaned}"
    parsed = urlparse(with_scheme)
    hostname = (parsed.netloc or "").lower().strip()
    ext = tldextract.extract(hostname)
    registered_domain = f"{ext.domain}.{ext.suffix}".lower().strip(".") if ext.domain and ext.suffix else hostname.replace("www.", "")
    hostname_without_www = hostname.replace("www.", "", 1)
    has_path_or_query = bool((parsed.path and parsed.path != "/") or parsed.query or parsed.fragment)
    has_subdomain = bool(ext.subdomain and ext.subdomain.lower() != "www")
    is_main_domain_input = bool(
        registered_domain
        and hostname_without_www == registered_domain
        and not has_path_or_query
        and not has_subdomain
    )

    normalized_url = parsed._replace(fragment="").geturl()
    return {
        "raw_input": cleaned,
        "normalized_url": normalized_url,
        "hostname": hostname,
        "registered_domain": registered_domain,
        "discovery_domain": hostname_without_www or registered_domain,
        "is_main_domain_input": is_main_domain_input,
        "has_subdomain": has_subdomain,
        "has_path_or_query": has_path_or_query,
    }


async def career_url_extraction_node(state: JobScraperState) -> JobScraperState:
    completed_urls = list(state.get("completed_urls", []))
    navigate_to = str(state.get("navigate_to") or "").strip()
    browser_session = state.get("browser_session")
    domain_key, records, record = ensure_domain_record(state, navigate_to)
    record = dict(record or {})
    record_errors = list(record.get("errors", []))
    record_metadata = dict(record.get("metadata", {}) or {})

    if not navigate_to:
        updated_state: JobScraperState = {
            **state,
        }
        if domain_key and record is not None:
            record["discovered_job_urls"] = []
            record["non_domain_career_urls"] = []
            record_metadata["url_extraction_status"] = "idle"
            record["metadata"] = record_metadata
            records[domain_key] = record
            updated_state["domain_records"] = records
        return updated_state

    if browser_session is None or getattr(browser_session, "page", None) is None:
        error_message = f"Cannot extract URLs before navigation because no Playwright page is attached for {navigate_to}"
        record_errors.append(error_message)
        if navigate_to not in completed_urls:
            completed_urls.append(navigate_to)
        updated_state: JobScraperState = {
            **state,
            "completed_urls": completed_urls,
        }
        if domain_key and record is not None:
            record["errors"] = record_errors
            record["discovered_job_urls"] = []
            record["non_domain_career_urls"] = []
            record["career_page_analyses"] = {}
            record_metadata["url_extraction_status"] = "session_not_established"
            record_metadata["url_extraction_error"] = "missing_browser_page"
            record["metadata"] = record_metadata
            return set_domain_record(updated_state, domain_key, record)
        return updated_state

    target = _normalize_input_target(navigate_to)
    if not target["discovery_domain"]:
        error_message = f"Unable to determine discovery domain from input {navigate_to}"
        record_errors.append(error_message)
        if navigate_to not in completed_urls:
            completed_urls.append(navigate_to)
        updated_state: JobScraperState = {
            **state,
            "completed_urls": completed_urls,
        }
        if domain_key and record is not None:
            record["errors"] = record_errors
            record["discovered_job_urls"] = []
            record["non_domain_career_urls"] = []
            record["career_page_analyses"] = {}
            record_metadata["url_extraction_status"] = "invalid_input"
            record_metadata["url_extraction_error"] = "missing_discovery_domain"
            record["metadata"] = record_metadata
            return set_domain_record(updated_state, domain_key, record)
        return updated_state

    extractor = UrlExtractor(browser_session.page)
    fallback_urls = await extractor.discover_job_urls_from_domain(
        domain=target["discovery_domain"],
        try_common_paths=False,
        extract_from_homepage=True,
    )

    fallback_meta = dict(fallback_urls.get("meta_data", {}) or {})
    redirect_detected = bool(fallback_meta.get("redirected"))

    non_domain_careers_result: dict[str, Any] = {"success": False, "result": [], "meta_data": {}}
    search_result: dict[str, Any] = {"success": False, "result": [], "meta_data": {}}
    combined_job_urls = _dedupe_urls(list(fallback_urls.get("result", []) or []))
    non_domain_career_urls: list[dict[str, Any]] = []

    status = "ready_for_navigation"
    should_skip_current_url = False
    skip_reason = None

    if redirect_detected:
        status = "redirected"
        should_skip_current_url = True
        skip_reason = "domain_redirected"
        combined_job_urls = []
        error_message = f"Domain redirected for {navigate_to}: {fallback_meta.get('original_url', navigate_to)} -> {fallback_meta.get('final_url', '')}"
        record_errors.append(error_message)
    elif not fallback_urls.get("success"):
        fallback_error = str(fallback_urls.get("error", "") or "Unknown error")
        if target["is_main_domain_input"]:
            status = "domain_access_failed"
            should_skip_current_url = True
            skip_reason = "domain_access_failed"
            combined_job_urls = []
            error_message = f"Failed to access domain or load homepage for {navigate_to}: {fallback_error}"
            record_errors.append(error_message)
        else:
            status = "seed_url_retained"
            combined_job_urls = _dedupe_urls([target["normalized_url"], *combined_job_urls])
            error_message = f"Domain discovery failed for {navigate_to}; continuing with the provided start URL"
            record_errors.append(error_message)
    else:
        non_domain_careers_result = await extractor._extract_career_urls_from_page(
            target["registered_domain"] or target["discovery_domain"]
        )
        search_query = f"site:{target['discovery_domain']} jobs careers vacancies openings"
        search_result = await extractor.search_duckduckgo(search_query, target["discovery_domain"])
        combined_job_urls = _dedupe_urls(
            list(fallback_urls.get("result", []) or []) + list(search_result.get("result", []) or [])
        )
        non_domain_career_urls = _dedupe_career_items(list(non_domain_careers_result.get("result", []) or []))
        if not target["is_main_domain_input"]:
            combined_job_urls = _dedupe_urls([target["normalized_url"], *combined_job_urls])

    if should_skip_current_url and navigate_to not in completed_urls:
        completed_urls.append(navigate_to)

    summary = {
        "input_url": navigate_to,
        "normalized_url": target["normalized_url"],
        "registered_domain": target["registered_domain"],
        "discovery_domain": target["discovery_domain"],
        "is_main_domain_input": target["is_main_domain_input"],
        "has_subdomain": target["has_subdomain"],
        "has_path_or_query": target["has_path_or_query"],
        "status": status,
        "skip_current_url": should_skip_current_url,
        "skip_reason": skip_reason,
        "job_filtered": combined_job_urls,
        "non_domain_careers_url": non_domain_career_urls,
        "fallback_success": bool(fallback_urls.get("success")),
        "fallback_error": str(fallback_urls.get("error", "") or ""),
        "fallback_status": str(fallback_urls.get("status", "") or ""),
        "search_success": bool(search_result.get("success")),
        "search_error": str(search_result.get("error", "") or ""),
        "redirect_detected": redirect_detected,
        "redirected_url": fallback_meta.get("final_url"),
        "redirected_domain": fallback_meta.get("final_domain"),
        "fallback_meta_data": fallback_meta,
        "search_meta_data": dict(search_result.get("meta_data", {}) or {}),
        "career_meta_data": dict(non_domain_careers_result.get("meta_data", {}) or {}),
    }
    history = list(record_metadata.get("url_extraction_history", []))
    history.append(summary)

    log_event(
        logger,
        "info",
        "url_extraction_completed input=%s status=%s job_filtered_count=%s non_domain_career_count=%s skip_current_url=%s",
        navigate_to,
        status,
        len(combined_job_urls),
        len(non_domain_career_urls),
        should_skip_current_url,
        domain=domain_key or target["registered_domain"] or target["discovery_domain"] or "unknown",
        input_url=navigate_to,
        status=status,
        job_filtered_count=len(combined_job_urls),
        non_domain_career_count=len(non_domain_career_urls),
        skip_current_url=should_skip_current_url,
    )

    updated_state: JobScraperState = {
        **state,
        "completed_urls": completed_urls,
    }
    if domain_key and record is not None:
        record["errors"] = record_errors
        record["discovered_job_urls"] = combined_job_urls
        record["non_domain_career_urls"] = non_domain_career_urls
        record["career_page_analyses"] = {}
        record_metadata.update(
            {
                "url_extraction_status": status,
                "job_filtered": combined_job_urls,
                "non_domain_careers_url": non_domain_career_urls,
                "redirected_url": fallback_meta.get("final_url"),
                "redirected_domain": fallback_meta.get("final_domain"),
                "url_extraction_result": summary,
                "url_extraction_history": history,
                "current_candidate_url": combined_job_urls[0] if combined_job_urls and status in {"ready_for_navigation", "seed_url_retained"} else None,
                "checked_candidate_urls": [],
                "career_page_scan_status": "ready" if combined_job_urls and status in {"ready_for_navigation", "seed_url_retained"} else "not_started",
                "career_page_found_url": None,
                "career_navigation_steps": 0,
                "career_navigation_target_url": None,
                "career_navigation_target_button": None,
                "visited_candidate_urls": [],
                "llm_reasoning": [],
                "manual_review_required": False,
                "manual_reviews": [],
                "processing_mode": state.get("processing_mode") or "both",
            }
        )
        record["metadata"] = record_metadata
        records[domain_key] = record
        updated_state["domain_records"] = records
        return set_domain_record(updated_state, domain_key, record)
    return updated_state
