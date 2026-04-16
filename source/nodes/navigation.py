from __future__ import annotations

import asyncio

from state import JobScraperState

from core.config import get_settings
from services.navigation import navigate_to_url
from services.pipeline_logging import get_logger

logger = get_logger("navigation_node")


async def navigation_node(state: JobScraperState) -> JobScraperState:
    settings = get_settings()
    errors = list(state.get("errors", []))
    browser_session = state.get("browser_session")
    agent_index = state.get("agent_index", 0)
    navigate_to = state.get("navigate_to")
    agent_tab = state.get("agent_tab")
    completed_urls = list(state.get("completed_urls", []))
    metadata = dict(state.get("metadata", {}))
    navigation_attempt_count = int(metadata.get("navigation_attempt_count", 0) or 0)

    if not state.get("session_established", False):
        errors.append(f"Cannot navigate because the browser session was not established url {navigate_to}")
        return {
            **state,
            "navigation_results": [],
            "errors": errors,
            "metadata": {
                **metadata,
                "navigation_status": "session_not_established",
            },
        }

    if not navigate_to:
        return {
            **state,
            "navigation_results": [
                {
                    "agent_index": agent_index,
                    "handle": agent_tab["handle"] if agent_tab else None,
                    "url": None,
                    "status": "idle",
                    "current_url": None,
                    "error": None,
                }
            ],
            "errors": errors,
            "metadata": {
                **metadata,
                "navigation_status": "idle",
            },
        }

    if not agent_tab:
        errors.append(f"Cannot navigate because the agent tab was not prepared {navigate_to}")
        return {
            **state,
            "navigation_results": [],
            "errors": errors,
            "metadata": {
                **metadata,
                "navigation_status": "missing_agent_tab",
            },
        }

    navigation_result = await navigate_to_url(
        browser_session.page if browser_session is not None else None,
        agent_index=agent_index,
        tab_handle=agent_tab["handle"],
        url=navigate_to,
        post_navigation_delay_ms=0,
    )
    navigation_results = [navigation_result]
    logger.info(
        "navigation_result agent_index=%s url=%s status=%s",
        agent_index,
        navigate_to,
        navigation_result["status"],
    )

    navigation_errors = [result["error"] for result in navigation_results if result["error"]]
    if browser_session is None:
        errors.append("Unable to attach a Playwright page for navigation")
    else:
        errors.extend(navigation_errors)

    next_navigation_attempt_count = 0 if navigation_result["status"] == "navigated" else navigation_attempt_count + 1

    if navigation_result["status"] == "navigated" and navigate_to not in completed_urls:
        completed_urls.append(navigate_to)
    if navigation_result["status"] != "navigated" and next_navigation_attempt_count >= 3 and navigate_to not in completed_urls:
        completed_urls.append(navigate_to)

    if navigation_result["status"] == "navigated" and settings.post_navigation_delay_ms > 0:
        await asyncio.sleep(settings.post_navigation_delay_ms / 1000)

    return {
        **state,
        "navigation_results": navigation_results,
        "completed_urls": completed_urls,
        "errors": errors,
        "metadata": {
            **metadata,
            "last_navigate_to": navigate_to,
            "navigated_url_count": sum(1 for result in navigation_results if result["status"] == "navigated"),
            "navigation_status": navigation_result["status"],
            "navigation_attempt_count": next_navigation_attempt_count,
            "post_navigation_delay_ms": settings.post_navigation_delay_ms,
        },
    }
