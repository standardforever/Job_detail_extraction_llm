from __future__ import annotations

from services.domain_state import append_manual_review, current_domain_record, set_domain_record
from state import JobScraperState

from core.config import get_settings
from services.navigation_actions import follow_navigation_target
from services.url_target_classifier import classify_url_target


async def button_click_node(state: JobScraperState) -> JobScraperState:
    domain_key, record = current_domain_record(state)
    record = dict(record or {})
    record_errors = list(record.get("errors", []))
    record_metadata = dict(record.get("metadata", {}) or {})
    page_category = record.get("page_category") or state.get("page_category")
    browser_session = state.get("browser_session")
    agent_tab = state.get("agent_tab")
    agent_index = state.get("agent_index", 0)
    if not page_category or page_category.get("category") not in {"need_navigation", "navigation_required"}:
        updated_state: JobScraperState = {
            **state,
        }
        if domain_key and record is not None:
            record["button_click_result"] = {
                "status": "skipped",
                "target_url": None,
                "target_button": None,
                "current_url": browser_session.page.url if browser_session else None,
                "error": None,
            }
            return set_domain_record(updated_state, domain_key, record)
        return updated_state

    navigation_target = page_category.get("navigation_target") or {}
    if not navigation_target.get("url") and not navigation_target.get("button"):
        navigation_target = {
            "url": record_metadata.get("career_navigation_target_url"),
            "button": record_metadata.get("career_navigation_target_button"),
        }
    settings = get_settings()
    status, current_url, error = await follow_navigation_target(
        browser_session.page if browser_session else None,
        target_url=navigation_target.get("url"),
        target_button=navigation_target.get("button"),
        post_navigation_delay_ms=settings.post_navigation_delay_ms,
    )
    if error:
        record_errors.append(error)

    job_urls = list(record.get("job_urls") or state.get("job_urls", []))
    completed_job_urls = list(record.get("completed_job_urls") or state.get("completed_job_urls", []))
    extracted_jobs = list(record.get("extracted_jobs") or state.get("extracted_jobs", []))
    if status == "download_started" and current_url:
        url_type = classify_url_target(current_url)
        if current_url not in job_urls:
            job_urls.append(current_url)
        if current_url not in completed_job_urls:
            completed_job_urls.append(current_url)
        extracted_jobs.append(
            {
                "job_url": current_url,
                "page_url": current_url,
                "raw_markdown": None,
                "structured_data": {
                    "job_url": current_url,
                    "title": None,
                    "company_name": None,
                    "holiday": None,
                    "location": {"address": None, "city": None, "region": None, "postcode": None, "country": None},
                    "salary": {"min": None, "max": None, "currency": None, "period": None, "actual_salary": None, "raw": None},
                    "job_type": None,
                    "contract_type": None,
                    "remote_option": None,
                    "hours": {"weekly": None, "daily": None, "details": None},
                    "closing_date": {"iso_format": None, "raw_text": None},
                    "interview_date": {"iso_format": None, "raw_text": None},
                    "start_date": {"iso_format": None, "raw_text": None},
                    "post_date": {"iso_format": None, "raw_text": None},
                    "contact": {"name": None, "email": None, "phone": None},
                    "job_reference": None,
                    "description": None,
                    "responsibilities": [],
                    "requirements": [],
                    "benefits": [],
                    "company_info": None,
                    "how_to_apply": None,
                    "additional_sections": {
                        "non_webpage_reason": f"Navigation target triggered a downloadable/non-webpage resource ({url_type['kind']}). {url_type['reason']}",
                    },
                    "is_job_page": False,
                    "confidence_reason": "A job-related navigation target was found, but it resolves to a downloadable or non-HTML resource instead of a normal webpage.",
                    "application_method": {"type": "external_link", "url": current_url, "email": None, "instructions": None},
                },
            }
        )

    updated_state: JobScraperState = {
        **state,
    }
    if domain_key and record is not None:
        record["errors"] = record_errors
        record["button_click_result"] = {
            "status": status,
            "target_url": navigation_target.get("url"),
            "target_button": navigation_target.get("button"),
            "current_url": current_url or (browser_session.page.url if browser_session else None),
            "error": error,
        }
        record["job_urls"] = job_urls
        record["completed_job_urls"] = completed_job_urls
        record["extracted_jobs"] = extracted_jobs
        record["navigation_results"] = [
            {
                "agent_index": agent_index,
                "handle": agent_tab["handle"] if agent_tab else None,
                "url": navigation_target.get("url") or state.get("navigate_to"),
                "status": "navigation_download" if status == "download_started" else ("navigated" if status in {"clicked", "navigated"} else "navigation_failed"),
                "current_url": current_url or (browser_session.page.url if browser_session else None),
                "error": error,
            }
        ]
        record_metadata["navigation_action_status"] = status
        record_metadata["page_category_loop_count"] = int(record_metadata.get("page_category_loop_count", 0) or 0) + 1
        if status in {"clicked", "navigated"} and current_url:
            record_metadata["current_candidate_url"] = current_url
            visited_candidate_urls = [str(url) for url in (record_metadata.get("visited_candidate_urls") or []) if url]
            if current_url not in visited_candidate_urls:
                visited_candidate_urls.append(current_url)
            record_metadata["visited_candidate_urls"] = visited_candidate_urls
        elif status == "action_failed":
            record = append_manual_review(
                record,
                "button_navigation_failed",
                str(navigation_target.get("button") or navigation_target.get("url") or ""),
            )
            record_metadata = dict(record.get("metadata", {}) or {})
        record["metadata"] = record_metadata
        return set_domain_record(updated_state, domain_key, record)
    return updated_state
