from __future__ import annotations

from state import JobScraperState

from services.job_detail_to_json import convert_job_detail_content_to_json
from services.pipeline_logging import get_logger

logger = get_logger("convert_job_page_to_json_node")


async def convert_job_page_to_json_node(state: JobScraperState) -> JobScraperState:
    selected_job_url = state.get("selected_job_url")
    detail_content = state.get("job_detail_extracted_content")
    errors = list(state.get("errors", []))

    if not selected_job_url or not detail_content:
        return state

    structured_job_detail, token_usage, error = await convert_job_detail_content_to_json(detail_content)
    if structured_job_detail is None:
        logger.warning("job_detail_json_failed url=%s error=%s", selected_job_url, error)
        errors.append(f"Job detail JSON conversion failed: {error}")
        return {
            **state,
            "structured_job_detail": None,
            "errors": errors,
            "metadata": {
                **state.get("metadata", {}),
                "convert_job_page_to_json_status": "failed",
            },
        }

    completed_job_urls = list(state.get("completed_job_urls", []))
    if selected_job_url not in completed_job_urls:
        completed_job_urls.append(selected_job_url)

    extracted_jobs = list(state.get("extracted_jobs", []))
    job_with_source = {
        "job_url": selected_job_url,
        **structured_job_detail,
    }
    extracted_jobs.append(
        {
            "job_url": selected_job_url,
            "page_url": detail_content.get("url"),
            "raw_markdown": detail_content.get("markdown"),
            "structured_data": job_with_source,
        }
    )

    logger.info("job_detail_json_converted url=%s token_usage=%s", selected_job_url, token_usage)
    return {
        **state,
        "structured_job_detail": job_with_source,
        "completed_job_urls": completed_job_urls,
        "extracted_jobs": extracted_jobs,
        "errors": errors,
        "metadata": {
            **state.get("metadata", {}),
            "convert_job_page_to_json_status": "converted",
            "converted_job_count": len(extracted_jobs),
            "job_detail_json_tokens": token_usage,
        },
    }
