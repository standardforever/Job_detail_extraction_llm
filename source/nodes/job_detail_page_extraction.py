from __future__ import annotations

from state import JobScraperState

from services.job_detail_extraction import extract_job_detail_page_content
from services.navigation import navigate_to_url
from services.pipeline_logging import get_logger

logger = get_logger("job_detail_page_extraction_node")


async def job_detail_page_extraction_node(state: JobScraperState) -> JobScraperState:
    selected_job_url = state.get("selected_job_url")
    browser_session = state.get("browser_session")
    agent_tab = state.get("agent_tab")
    agent_index = state.get("agent_index", 0)
    errors = list(state.get("errors", []))

    if not selected_job_url:
        return {
            **state,
            "job_detail_extracted_content": None,
        }

    navigation_result = await navigate_to_url(
        browser_session.page if browser_session else None,
        agent_index=agent_index,
        tab_handle=agent_tab["handle"] if agent_tab else None,
        url=selected_job_url,
        post_navigation_delay_ms=0,
    )
    if navigation_result["error"]:
        logger.warning("job_detail_navigation_failed url=%s error=%s", selected_job_url, navigation_result["error"])
        errors.append(f"Job detail navigation failed: {navigation_result['error']}")
        completed_job_urls = list(state.get("completed_job_urls", []))
        if selected_job_url not in completed_job_urls:
            completed_job_urls.append(selected_job_url)
        return {
            **state,
            "job_detail_extracted_content": None,
            "completed_job_urls": completed_job_urls,
            "errors": errors,
            "metadata": {
                **state.get("metadata", {}),
                "job_detail_page_extraction_status": "navigation_failed",
                "selected_job_url": selected_job_url,
            },
        }

    extracted_content = await extract_job_detail_page_content(
        browser_session.page if browser_session else None,
        page_url=selected_job_url,
    )
    if extracted_content is None:
        logger.warning("job_detail_extraction_failed url=%s", selected_job_url)
        errors.append("Unable to extract job detail page content")
        completed_job_urls = list(state.get("completed_job_urls", []))
        if selected_job_url not in completed_job_urls:
            completed_job_urls.append(selected_job_url)
        return {
            **state,
            "job_detail_extracted_content": None,
            "completed_job_urls": completed_job_urls,
            "errors": errors,
            "metadata": {
                **state.get("metadata", {}),
                "job_detail_page_extraction_status": "extraction_failed",
                "selected_job_url": selected_job_url,
            },
        }

    logger.info(
        "job_detail_extracted url=%s markdown_length=%s",
        selected_job_url,
        len(extracted_content["markdown"]),
    )
    
    return {
        **state,
        "job_detail_extracted_content": extracted_content,
        "metadata": {
            **state.get("metadata", {}),
            "job_detail_page_extraction_status": "extracted",
            "selected_job_url": selected_job_url,
            "job_detail_extraction_sections": extracted_content.get("metadata", {}).get("sections", []),
        },
    }
