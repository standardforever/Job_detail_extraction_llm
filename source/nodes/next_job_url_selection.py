from __future__ import annotations

from state import JobScraperState
from services.url_target_classifier import classify_url_target


async def next_job_url_selection_node(state: JobScraperState) -> JobScraperState:
    job_urls = [url for url in state.get("job_urls", []) if url]
    completed_job_urls = list(state.get("completed_job_urls", []))
    completed_job_url_set = set(completed_job_urls)
    extracted_jobs = list(state.get("extracted_jobs", []))
    selected_job_url = None

    for url in job_urls:
        if url in completed_job_url_set:
            continue

        url_type = classify_url_target(url)
        if bool(url_type["is_webpage"]):
            selected_job_url = url
            break

        completed_job_urls.append(url)
        completed_job_url_set.add(url)
        extracted_jobs.append(
            {
                "job_url": url,
                "page_url": url,
                "raw_markdown": None,
                "structured_data": {
                    "job_url": url,
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
                        "non_webpage_reason": f"Skipped opening because target is a non-webpage document ({url_type['kind']}). {url_type['reason']}",
                    },
                    "is_job_page": False,
                    "confidence_reason": f"Found a job-related target but did not open it because it appears to be a {url_type['kind']} document rather than an HTML page.",
                    "application_method": {"type": "external_link", "url": url, "email": None, "instructions": None},
                },
            }
        )

    return {
        **state,
        "selected_job_url": selected_job_url,
        "completed_job_urls": completed_job_urls,
        "extracted_jobs": extracted_jobs,
        "metadata": {
            **state.get("metadata", {}),
            "next_job_url_selection_status": "ready" if selected_job_url else "done",
            "remaining_job_url_count": sum(1 for url in job_urls if url not in completed_job_url_set),
        },
    }
