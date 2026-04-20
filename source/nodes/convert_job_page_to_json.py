from __future__ import annotations

from services.domain_state import append_manual_review, current_domain_record, set_domain_record
from state import JobScraperState

from services.job_detail_to_json import convert_job_detail_content_to_json
from utils.logging import get_logger, log_event

logger = get_logger("convert_job_page_to_json_node")


async def convert_job_page_to_json_node(state: JobScraperState) -> JobScraperState:
    domain_key, record = current_domain_record(state)
    record = dict(record or {})
    record_errors = list(record.get("errors", []))
    record_metadata = dict(record.get("metadata", {}) or {})
    selected_job_url = record.get("selected_job_url") or state.get("selected_job_url")
    detail_content = record.get("job_detail_extracted_content") or state.get("job_detail_extracted_content")
    processing_mode = str(record_metadata.get("processing_mode") or state.get("processing_mode") or "convert_jobs_to_dict").strip().lower()
    main_domain = str(record.get("domain") or "").strip() or None
    if not selected_job_url or not detail_content:
        return state

    structured_job_details, token_usage, error = await convert_job_detail_content_to_json(
        detail_content,
        processing_mode=processing_mode,
        main_domain=main_domain,
    )
    if structured_job_details is None:
        log_event(
            logger,
            "warning",
            "job_detail_json_failed url=%s error=%s",
            selected_job_url,
            error,
            domain=domain_key or "unknown",
            selected_job_url=selected_job_url,
            error=error,
            processing_mode=processing_mode,
        )
        error_message = f"Job detail JSON conversion failed: {error}"
        record_errors.append(error_message)
        updated_state: JobScraperState = {
            **state,
        }
        if domain_key and record is not None:
            record["errors"] = record_errors
            record["structured_job_detail"] = None
            record_metadata["convert_job_page_to_json_status"] = "failed"
            record["metadata"] = record_metadata
            record = append_manual_review(record, "job_detail_json_conversion_failed", error_message)
            return set_domain_record(updated_state, domain_key, record)
        return updated_state

    completed_job_urls = list(record.get("completed_job_urls") or state.get("completed_job_urls", []))
    if selected_job_url not in completed_job_urls:
        completed_job_urls.append(selected_job_url)

    extracted_jobs = list(record.get("extracted_jobs") or state.get("extracted_jobs", []))
    normalized_jobs: list[dict] = []
    ats_results: list[dict] = []
    for structured_job_detail in structured_job_details:
        job_with_source = {
            "job_url": selected_job_url,
            **structured_job_detail,
        }
        normalized_jobs.append(job_with_source)
        if processing_mode == "both":
            ats_results.append(
                {
                    "job_url": selected_job_url,
                    "title": structured_job_detail.get("title"),
                    "ats_detected": structured_job_detail.get("is_ats"),
                    "provider": structured_job_detail.get("ats_provider"),
                    "application_style": structured_job_detail.get("application_type"),
                    "apply_url": structured_job_detail.get("apply_url"),
                    "reason": structured_job_detail.get("confidence_reason"),
                    "ats_confidence": structured_job_detail.get("ats_confidence"),
                    "page_access_status": structured_job_detail.get("page_access_status"),
                    "page_access_issue_detail": structured_job_detail.get("page_access_issue_detail"),
                    "indicators_found": structured_job_detail.get("indicators_found", []),
                    "ats_lookup_domain": structured_job_detail.get("ats_lookup_domain"),
                    "domain_registry_status": structured_job_detail.get("domain_registry_status"),
                    "registry_agreement": structured_job_detail.get("registry_agreement"),
                }
            )
        extracted_jobs.append(
            {
                "job_url": selected_job_url,
                "page_url": detail_content.get("url"),
                "raw_markdown": detail_content.get("markdown"),
                "structured_data": job_with_source,
            }
        )

    log_event(
        logger,
        "info",
        "job_detail_json_converted url=%s token_usage=%s",
        selected_job_url,
        token_usage,
        domain=domain_key or "unknown",
        selected_job_url=selected_job_url,
        token_usage=token_usage,
        processing_mode=processing_mode,
        jobs_from_page_count=len(normalized_jobs),
    )
    updated_state: JobScraperState = {
        **state,
    }
    if domain_key and record is not None:
        record["errors"] = record_errors
        record["structured_job_detail"] = normalized_jobs[0] if len(normalized_jobs) == 1 else {"jobs": normalized_jobs}
        if processing_mode == "both":
            record["ats_check_result"] = ats_results[0] if len(ats_results) == 1 else {"jobs": ats_results}
        record["completed_job_urls"] = completed_job_urls
        record["extracted_jobs"] = extracted_jobs
        record_metadata["convert_job_page_to_json_status"] = "converted"
        record_metadata["converted_job_count"] = len(extracted_jobs)
        record_metadata["converted_jobs_from_page_count"] = len(normalized_jobs)
        record_metadata["job_detail_json_tokens"] = token_usage
        if processing_mode == "both":
            record_metadata["job_detail_ats_status"] = "completed"
        record["metadata"] = record_metadata
        return set_domain_record(updated_state, domain_key, record)
    return updated_state
