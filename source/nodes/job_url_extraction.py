from __future__ import annotations

from state import JobScraperState

from services.pipeline_logging import get_logger
from services.job_url_extraction import extract_job_listing_page_analysis

logger = get_logger("job_url_extraction_node")


async def job_url_extraction_node(state: JobScraperState) -> JobScraperState:
    page_category = state.get("page_category")
    extracted_content = state.get("extracted_content")
    existing_features = state.get("job_page_features") or {}
    errors = list(state.get("errors", []))

    if not page_category or page_category.get("category") != "job_page":
        return {
            **state,
            "job_listing_page_analysis": None,
            "job_urls": [],
        }

    if not extracted_content or not extracted_content.get("markdown"):
        errors.append("Cannot extract job URLs because extracted content is missing")
        return {
            **state,
            "job_listing_page_analysis": None,
            "job_urls": [],
            "errors": errors,
        }

    page_analysis, token_usage, error = await extract_job_listing_page_analysis(
        extracted_markdown=extracted_content["markdown"],
        page_url=extracted_content.get("url"),
        known_features=existing_features,
    )
    if page_analysis is None:
        logger.warning("job_url_extraction_failed page_url=%s error=%s", extracted_content.get("url"), error)
        errors.append(f"Job URL extraction failed: {error}")
        return {
            **state,
            "job_listing_page_analysis": None,
            "job_urls": [],
            "errors": errors,
        }

    merged_features = {
        **existing_features,
        "filter_present": page_analysis["filter_present"],
        "filter_types": page_analysis["filter_types"],
        "sort_present": page_analysis["sort_present"],
        "sort_types": page_analysis["sort_types"],
        "pagination_present": page_analysis["pagination_present"],
        "pagination_type": page_analysis["pagination_type"],
    }

    logger.info(
        "job_url_extraction_completed page_url=%s job_url_count=%s",
        extracted_content.get("url"),
        len(page_analysis["job_urls"]),
    )
    return {
        **state,
        "job_listing_page_analysis": page_analysis,
        "job_page_features": merged_features,
        "job_urls": page_analysis["job_urls"],
        "errors": errors,
        "metadata": {
            **state.get("metadata", {}),
            "job_url_count": len(page_analysis["job_urls"]),
            "job_url_extraction_tokens": token_usage,
            "job_listing_page_notes": page_analysis["notes"],
            "next_page_url": page_analysis["next_page_url"],
            "load_more_button": page_analysis["load_more_button"],
        },
    }
