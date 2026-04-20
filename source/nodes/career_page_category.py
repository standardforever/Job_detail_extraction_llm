from __future__ import annotations

from typing import Any

from prompts.career_category_prompt import create_job_page_analysis_prompt
from services.domain_state import append_manual_review, current_domain_record, set_domain_record
from services.flow_safety import detect_external_job_board, normalize_navigation_url
from services.openai_service import OpenAIAnalysisService
from state import JobScraperState


def _normalize_career_analysis(response: dict[str, Any]) -> dict[str, Any]:
    next_action_target = response.get("next_action_target") or {}
    listing_ui = response.get("listing_ui") or {}
    jobs_listed = []
    for item in response.get("jobs_listed_on_page") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "") or "").strip()
        job_url = str(item.get("job_url", "") or "").strip() or None
        jobs_listed.append(
            {
                "title": title,
                "job_url": job_url,
            }
        )

    return {
        "page_category": str(response.get("page_category", "") or "").strip(),
        "confidence": float(response.get("confidence", 0.0) or 0.0),
        "reasoning": str(response.get("reasoning", "") or "").strip(),
        "job_alert": response.get("job_alert"),
        "page_access_status": str(response.get("page_access_status", "") or "").strip(),
        "page_access_issue_detail": str(response.get("page_access_issue_detail", "") or "").strip() or None,
        "next_action_target": {
            "url": str(next_action_target.get("url", "") or "").strip() or None,
            "button": str(next_action_target.get("button", "") or "").strip() or None,
            "element_type": str(next_action_target.get("element_type", "") or "").strip() or None,
        },
        "jobs_listed_on_page": jobs_listed,
        "listing_ui": {
            "ui_category": str(listing_ui.get("ui_category", "") or "").strip() or None,
            "filter_present": bool(listing_ui.get("filter_present", False)),
            "filter_types": [str(item) for item in (listing_ui.get("filter_types") or []) if item],
            "sort_present": bool(listing_ui.get("sort_present", False)),
            "sort_types": [str(item) for item in (listing_ui.get("sort_types") or []) if item],
            "pagination_present": bool(listing_ui.get("pagination_present", False)),
            "pagination_type": str(listing_ui.get("pagination_type", "") or "").strip() or None,
            "next_page_url": str(listing_ui.get("next_page_url", "") or "").strip() or None,
        },
    }


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


def _next_candidate(candidates: list[str], checked: set[str]) -> str | None:
    for candidate in candidates:
        normalized = str(candidate or "").strip()
        if normalized and normalized not in checked:
            return normalized
    return None


async def career_page_category_node(state: JobScraperState) -> JobScraperState:
    domain_key, record = current_domain_record(state)
    record = dict(record or {})
    record_errors = list(record.get("errors", []))
    record_metadata = dict(record.get("metadata", {}) or {})
    extracted_content = record.get("extracted_content") or state.get("extracted_content")
    current_candidate_url = str(record_metadata.get("current_candidate_url", "") or "").strip() or record.get("navigate_to")
    
    if not current_candidate_url or not extracted_content or not extracted_content.get("markdown"):
        return state

    prompt = create_job_page_analysis_prompt(current_candidate_url, extracted_content["markdown"])
    service = OpenAIAnalysisService()
    analysis = await service.analyze_data(prompt=prompt, json_response=True)
    
    if not analysis.success:
        error_message = f"Career page categorization failed: {analysis.error}"
        record_errors.append(error_message)
        record["errors"] = record_errors
        record["career_page_analyses"] = dict(record.get("career_page_analyses", {}) or {})
        record_metadata["career_page_scan_status"] = "continue_scanning"
        checked = set(record_metadata.get("checked_candidate_urls", []) or [])
        checked.add(current_candidate_url)
        record_metadata["checked_candidate_urls"] = list(checked)
        record["metadata"] = record_metadata
        updated_state: JobScraperState = {
            **state,
        }
        return set_domain_record(updated_state, domain_key, record) if domain_key else updated_state

    normalized = _normalize_career_analysis(analysis.response)
    analyses = {
        str(key): dict(value or {})
        for key, value in dict(record.get("career_page_analyses", {}) or {}).items()
    }
    analyses[current_candidate_url] = {
        **normalized,
        "analysis_tokens": analysis.token_usage,
    }
    llm_reasoning = [
        dict(item)
        for item in list(record_metadata.get("llm_reasoning", []) or [])
        if isinstance(item, dict)
    ]
    llm_reasoning.append(
        {
            "url": current_candidate_url,
            "page_category": normalized["page_category"],
            "confidence": normalized["confidence"],
            "reasoning": normalized["reasoning"],
            "token_usage": analysis.token_usage,
        }
    )

    checked = set(record_metadata.get("checked_candidate_urls", []) or [])
    checked.add(current_candidate_url)
    candidates = [str(url) for url in (record.get("discovered_job_urls") or []) if url]
    category = normalized["page_category"]
    existing_job_urls = [str(url) for url in (record.get("job_urls") or []) if url]
    external_job_board_targets = {
        str(key): str(value)
        for key, value in dict(record_metadata.get("external_job_board_targets", {}) or {}).items()
        if key and value
    }
    visited_candidate_urls = [str(url) for url in (record_metadata.get("visited_candidate_urls") or []) if url]
    next_candidate = _next_candidate(candidates, checked)
    scan_status = "continue_scanning"
    processing_mode = str(state.get("processing_mode") or record_metadata.get("processing_mode") or "both").strip().lower()
    
    page_category_result = {
        "category": category,
        "confidence": normalized["confidence"],
        "reason": normalized["reasoning"],
        "navigation_target": {
            "url": normalized["next_action_target"]["url"],
            "button": normalized["next_action_target"]["button"],
        },
    }
    
    job_urls_on_page = [
        str(item.get("job_url") or "").strip()
        for item in normalized["jobs_listed_on_page"]
        if isinstance(item, dict) and str(item.get("job_url") or "").strip()
    ]
    embedded_jobs_present = bool(normalized["jobs_listed_on_page"]) and not bool(job_urls_on_page)
    ui_category = normalized["listing_ui"]["ui_category"]
    should_run_ats_check = processing_mode in {"ats_check", "both"}
    should_convert_jobs = processing_mode in {"convert_jobs_to_dict", "both"}
    navigation_steps = int(record_metadata.get("career_navigation_steps", 0) or 0)

    if category == "not_job_related":
        if next_candidate is None:
            scan_status = "no_job_page_found"

    elif category == "navigation_required":
        target_url = normalize_navigation_url(normalized["next_action_target"]["url"], current_candidate_url)
        target_button = normalized["next_action_target"]["button"]
        external_job_board = detect_external_job_board(target_url)
        if target_url and external_job_board:
            existing_job_urls = _dedupe_urls([target_url, *existing_job_urls])
            external_job_board_targets[target_url] = external_job_board
            scan_status = "single_job_only_found" if next_candidate is None else "continue_scanning"
        elif target_url and target_url in visited_candidate_urls:
            if next_candidate is None:
                scan_status = "no_job_page_found"
        elif navigation_steps < 3 and target_url:
            scan_status = "follow_navigation_url"
            next_candidate = target_url
        elif navigation_steps < 3 and target_button:
            scan_status = "follow_navigation_button"
        elif next_candidate is None:
            scan_status = "single_job_only_found" if existing_job_urls else "no_job_page_found"

    elif category == "single_job_posting":
        existing_job_urls = _dedupe_urls([current_candidate_url, *existing_job_urls])
        if next_candidate is None:
            scan_status = "single_job_only_found"
    elif category in {"jobs_listed", "job_listings_preview_page"}:
        existing_job_urls = _dedupe_urls(existing_job_urls + job_urls_on_page)
        if should_run_ats_check and (
            not job_urls_on_page
            or ui_category != "linked_cards"
            or (processing_mode == "ats_check" and bool(job_urls_on_page))
        ):
            scan_status = "ats_check_required"
        elif normalized["jobs_listed_on_page"]:
            scan_status = "found_listing_page"
        elif next_candidate is None:
            scan_status = "no_job_page_found"
    elif next_candidate is None:
        scan_status = "single_job_only_found" if existing_job_urls else "no_job_page_found"

    if scan_status in {"found_listing_page", "single_job_only_found", "no_job_page_found", "ats_check_required"}:
        completed_urls = list(state.get("completed_urls", []))
        outer_url = str(state.get("navigate_to") or "").strip()
        if outer_url and outer_url not in completed_urls:
            completed_urls.append(outer_url)
    else:
        completed_urls = list(state.get("completed_urls", []))

    next_candidate_url = None if scan_status in {"found_listing_page", "single_job_only_found", "no_job_page_found", "ats_check_required"} else next_candidate

    record["errors"] = record_errors
    record["career_page_analyses"] = analyses
    record["job_urls"] = existing_job_urls
    record["page_category"] = page_category_result
    if (
        category == "navigation_required"
        and not normalized["next_action_target"]["url"]
        and not normalized["next_action_target"]["button"]
        and next_candidate is None
    ):
        record = append_manual_review(record, "missing_navigation_target", current_candidate_url)
        record_metadata = dict(record.get("metadata", {}) or {})
    elif category == "navigation_required" and target_url and target_url in visited_candidate_urls:
        record = append_manual_review(record, "navigation_target_already_visited", target_url)
        record_metadata = dict(record.get("metadata", {}) or {})
    record_metadata.update(
        {
            "career_page_scan_status": scan_status,
            "career_page_category_tokens": analysis.token_usage,
            "llm_reasoning": llm_reasoning,
            "checked_candidate_urls": list(checked),
            "current_candidate_url": next_candidate_url,
            "last_career_category": category,
            "career_page_found_url": current_candidate_url if scan_status in {"found_listing_page", "single_job_only_found", "ats_check_required"} else record_metadata.get("career_page_found_url"),
            "career_navigation_steps": (
                navigation_steps + 1 if scan_status in {"follow_navigation_url", "follow_navigation_button"} else (0 if next_candidate_url else navigation_steps)
            ),
            "career_navigation_target_url": target_url if category == "navigation_required" else normalized["next_action_target"]["url"],
            "career_navigation_target_button": normalized["next_action_target"]["button"],
            "navigation_attempt_count": 0 if scan_status in {"follow_navigation_url", "follow_navigation_button"} or next_candidate_url else int(record_metadata.get("navigation_attempt_count", 0) or 0),
            "extract_attempt_count": 0 if scan_status in {"follow_navigation_url", "follow_navigation_button"} or next_candidate_url else int(record_metadata.get("extract_attempt_count", 0) or 0),
            "processing_mode": processing_mode,
            "ats_check_required": bool(scan_status == "ats_check_required"),
            "should_convert_jobs": bool(should_convert_jobs),
            "embedded_jobs_present": embedded_jobs_present,
            "embedded_jobs_listed_on_page": normalized["jobs_listed_on_page"],
            "external_job_board_targets": external_job_board_targets,
        }
    )
    record["metadata"] = record_metadata

    updated_state: JobScraperState = {
        **state,
        "completed_urls": completed_urls,
    }
    return set_domain_record(updated_state, domain_key, record) if domain_key else updated_state
