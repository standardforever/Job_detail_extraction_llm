from __future__ import annotations

from urllib.parse import urlparse

from services.domain_state import current_domain_record, set_domain_record
from state import JobScraperState
from services.url_target_classifier import classify_url_target


def _empty_job_payload(url: str) -> dict:
    return {
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
    }


def _non_webpage_ats_result(url: str, url_type: dict[str, str | bool | None]) -> dict:
    kind = str(url_type.get("kind") or "document")
    reason = (
        f"Job URL points to a non-webpage document/download ({kind}). "
        "Document files are not ATS or application systems."
    )
    return {
        "status": "success",
        "job_url": url,
        "is_ats": False,
        "ats_detected": False,
        "is_known_ats": False,
        "is_external_application": False,
        "provider": None,
        "ats_provider": None,
        "application_style": "document_only",
        "application_type": "document_only",
        "confidence": "high",
        "ats_confidence": "high",
        "reasoning": reason,
        "reason": reason,
        "detection_method": "file_type_rule",
        "page_access_status": "document_only",
        "page_access_issue_detail": str(url_type.get("reason") or ""),
        "indicators_found": [],
        "ats_lookup_domain": None,
        "domain_registry_status": "not_checked",
        "registry_agreement": "neutral",
        "token_usage": 0,
    }


def _merge_ats_results(existing: object, new_results: list[dict]) -> dict:
    existing_results: list[dict] = []
    total_tokens = 0
    if isinstance(existing, dict) and isinstance(existing.get("results"), list):
        existing_results.extend(dict(item) for item in existing.get("results", []) if isinstance(item, dict))
        total_tokens += int(existing.get("total_tokens", 0) or 0)
    elif isinstance(existing, dict) and existing:
        existing_results.append(dict(existing))
        total_tokens += int(existing.get("token_usage", 0) or 0)

    seen_job_urls = {
        str(item.get("job_url") or "").strip()
        for item in existing_results
        if str(item.get("job_url") or "").strip()
    }
    for result in new_results:
        job_url = str(result.get("job_url") or "").strip()
        if job_url and job_url in seen_job_urls:
            continue
        if job_url:
            seen_job_urls.add(job_url)
        existing_results.append(result)

    return {
        "results": existing_results,
        "total_tokens": total_tokens + sum(int(item.get("token_usage", 0) or 0) for item in new_results),
        "jobs_processed": len(existing_results),
        "found_definitive": any(item.get("is_ats") is not None or item.get("ats_detected") is not None for item in existing_results),
        "analysis_mode": "document_url_rule",
    }


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
    non_webpage_ats_results: list[dict] = []

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
                        **_empty_job_payload(url),
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
        ats_result = _non_webpage_ats_result(url, url_type)
        non_webpage_ats_results.append(ats_result)
        extracted_jobs.append(
            {
                "job_url": url,
                "page_url": url,
                "raw_markdown": None,
                "structured_data": {
                    **_empty_job_payload(url),
                    "additional_sections": {
                        "non_webpage_reason": f"Skipped opening because target is a non-webpage document ({url_type['kind']}). {url_type['reason']}",
                    },
                    "is_job_page": False,
                    "confidence_reason": f"Found a job-related target but did not open it because it appears to be a {url_type['kind']} document rather than an HTML page.",
                    "application_method": {"type": "external_link", "url": url, "email": None, "instructions": None},
                    "is_ats": False,
                    "is_job_related": True,
                    "ats_confidence": "high",
                    "application_type": "document_only",
                    "ats_provider": None,
                    "apply_url": None,
                    "apply_button_text": None,
                    "detail_button": None,
                    "requires_scraping": False,
                    "indicators_found": [],
                    "page_validity_issues": None,
                    "additional_notes": ats_result["reason"],
                    "page_access_status": "document_only",
                    "page_access_issue_detail": ats_result["page_access_issue_detail"],
                    "detection_method": "file_type_rule",
                    "ats_lookup_domain": None,
                    "domain_registry_status": "not_checked",
                    "registry_agreement": "neutral",
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
        if non_webpage_ats_results:
            record["ats_check_result"] = _merge_ats_results(record.get("ats_check_result"), non_webpage_ats_results)
            record_metadata["ats_check_status"] = "completed_by_file_type_rule"
            record_metadata["ats_check_mode"] = "file_type_rule"
            record_metadata["non_webpage_job_status"] = "document_only"
        record_metadata["next_job_url_selection_status"] = "ready" if selected_job_url else "done"
        record_metadata["remaining_job_url_count"] = sum(1 for url in job_urls if url not in completed_job_url_set)
        record_metadata["use_embedded_job_page"] = use_embedded_job_page
        record["metadata"] = record_metadata
        return set_domain_record(updated_state, domain_key, record)
    return updated_state
