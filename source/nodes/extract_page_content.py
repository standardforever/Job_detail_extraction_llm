from __future__ import annotations

from state import JobScraperState

from services.content_extraction import extract_page_content
from services.pipeline_logging import get_logger

logger = get_logger("extract_page_content_node")


async def extract_page_content_node(state: JobScraperState) -> JobScraperState:
    errors = list(state.get("errors", []))
    browser_session = state.get("browser_session")
    navigation_results = list(state.get("navigation_results", []))
    metadata = dict(state.get("metadata", {}))
    extract_attempt_count = int(metadata.get("extract_attempt_count", 0) or 0)

    if not state.get("session_established", False):
        errors.append("Cannot extract page content because the browser session was not established")
        return {
            **state,
            "extracted_content": None,
            "errors": errors,
            "metadata": {
                **metadata,
                "extract_status": "session_not_established",
            },
        }

    latest_navigation = navigation_results[-1] if navigation_results else None
    button_click_result = state.get("button_click_result")
    action_navigated = button_click_result and button_click_result.get("status") in {"clicked", "navigated"}
    if (latest_navigation is None or latest_navigation.get("status") != "navigated") and not action_navigated:
        return {
            **state,
            "extracted_content": None,
            "errors": errors,
            "metadata": {
                **metadata,
                "extract_status": "navigation_not_ready",
            },
        }

    extracted_content = await extract_page_content(
        browser_session.page if browser_session is not None else None,
    )
    print(extracted_content.get('markdown'))
    if extracted_content is None:
        logger.warning("page_content_extraction_failed navigate_to=%s", state.get("navigate_to"))
        errors.append("Unable to extract page content")
        return {
            **state,
            "extracted_content": None,
            "errors": errors,
            "metadata": {
                **metadata,
                "extract_status": "failed",
                "extract_attempt_count": extract_attempt_count + 1,
            },
        }

    logger.info(
        "page_content_extracted navigate_to=%s markdown_length=%s",
        state.get("navigate_to"),
        len(extracted_content["markdown"]),
    )
    return {
        **state,
        "extracted_content": extracted_content,
        "metadata": {
            **metadata,
            "extract_status": "extracted",
            "extract_attempt_count": 0,
            "extracted_markdown_length": len(extracted_content["markdown"]),
            "extraction_preparation": dict(extracted_content.get("metadata", {}).get("preparation", {})),
        },
    }
