from __future__ import annotations

from state import JobScraperState

from core.config import get_settings
from services.navigation_actions import follow_navigation_target
from services.url_target_classifier import classify_url_target


async def button_click_node(state: JobScraperState) -> JobScraperState:
    page_category = state.get("page_category")
    browser_session = state.get("browser_session")
    agent_tab = state.get("agent_tab")
    agent_index = state.get("agent_index", 0)
    errors = list(state.get("errors", []))

    if not page_category or page_category.get("category") != "need_navigation":
        return {
            **state,
            "button_click_result": {
                "status": "skipped",
                "target_url": None,
                "target_button": None,
                "current_url": browser_session.page.url if browser_session else None,
                "error": None,
            },
        }

    navigation_target = page_category.get("navigation_target") or {}
    settings = get_settings()
    status, current_url, error = await follow_navigation_target(
        browser_session.page if browser_session else None,
        target_url=navigation_target.get("url"),
        target_button=navigation_target.get("button"),
        post_navigation_delay_ms=settings.post_navigation_delay_ms,
    )
    if error:
        errors.append(error)

    job_urls = list(state.get("job_urls", []))
    completed_job_urls = list(state.get("completed_job_urls", []))
    extracted_jobs = list(state.get("extracted_jobs", []))
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

    return {
        **state,
        "button_click_result": {
            "status": status,
            "target_url": navigation_target.get("url"),
            "target_button": navigation_target.get("button"),
            "current_url": current_url or (browser_session.page.url if browser_session else None),
            "error": error,
        },
        "navigation_results": [
            {
                "agent_index": agent_index,
                "handle": agent_tab["handle"] if agent_tab else None,
                "url": navigation_target.get("url") or state.get("navigate_to"),
                "status": "navigation_download" if status == "download_started" else ("navigated" if status in {"clicked", "navigated"} else "navigation_failed"),
                "current_url": current_url or (browser_session.page.url if browser_session else None),
                "error": error,
            }
        ],
        "job_urls": job_urls,
        "completed_job_urls": completed_job_urls,
        "extracted_jobs": extracted_jobs,
        "errors": errors,
        "metadata": {
            **state.get("metadata", {}),
            "navigation_action_status": status,
            "page_category_loop_count": int((state.get("metadata") or {}).get("page_category_loop_count", 0) or 0) + 1,
        },
    }
