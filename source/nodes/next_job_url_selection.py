from __future__ import annotations

from urllib.parse import urlparse

from services.domain_state import current_domain_record, set_domain_record
from state import JobScraperState
from services.url_target_classifier import classify_url_target


def _detect_external_job_board(url: str | None) -> str | None:
    normalized = str(url or "").strip()
    if not normalized:
        return None
    domain = urlparse(normalized).netloc.lower()
    if "linkedin." in domain:
        return "linkedin"
    if "indeed." in domain:
        return "indeed"
    return None


async def next_job_url_selection_node(state: JobScraperState) -> JobScraperState:
    domain_key, record = current_domain_record(state)
    record = dict(record or {})
    record_metadata = dict(record.get("metadata", {}) or {})
    job_urls = [url for url in (record.get("job_urls") or state.get("job_urls", [])) if url]
    completed_job_urls = list(record.get("completed_job_urls") or state.get("completed_job_urls", []))
    completed_job_url_set = set(completed_job_urls)
    extracted_jobs = list(record.get("extracted_jobs") or state.get("extracted_jobs", []))
    external_job_board_targets = {
        str(key): str(value)
        for key, value in dict(record_metadata.get("external_job_board_targets", {}) or {}).items()
        if key and value
    }
    selected_job_url = None
    use_embedded_job_page = False

    for url in job_urls:
        if url in completed_job_url_set:
            continue

        external_job_board = external_job_board_targets.get(url) or _detect_external_job_board(url)
        if external_job_board:
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
                            "external_job_board": external_job_board,
                            "external_job_board_reason": f"Skipped opening because navigation target points to an external {external_job_board} job URL.",
                        },
                        "is_job_page": False,
                        "confidence_reason": f"Found a job-related target on {external_job_board}, but did not navigate into the external job board page.",
                        "application_method": {"type": "external_link", "url": url, "email": None, "instructions": None},
                    },
                }
            )
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

    if (
        selected_job_url is None
        and not job_urls
        and bool(record_metadata.get("embedded_jobs_present"))
        and bool(record_metadata.get("should_convert_jobs"))
    ):
        embedded_page_url = str(record_metadata.get("career_page_found_url") or record.get("navigate_to") or "").strip() or None
        if embedded_page_url and embedded_page_url not in completed_job_url_set:
            selected_job_url = embedded_page_url
            use_embedded_job_page = True

    updated_state: JobScraperState = {
        **state,
    }
    if domain_key and record is not None:
        record["selected_job_url"] = selected_job_url
        record["completed_job_urls"] = completed_job_urls
        record["extracted_jobs"] = extracted_jobs
        record_metadata["next_job_url_selection_status"] = "ready" if selected_job_url else "done"
        record_metadata["remaining_job_url_count"] = sum(1 for url in job_urls if url not in completed_job_url_set)
        record_metadata["use_embedded_job_page"] = use_embedded_job_page
        record["metadata"] = record_metadata
        return set_domain_record(updated_state, domain_key, record)
    return updated_state
