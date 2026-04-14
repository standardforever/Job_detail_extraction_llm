from __future__ import annotations

from state import JobScraperState


async def select_next_url_node(state: JobScraperState) -> JobScraperState:
    assigned_urls = [url for url in state.get("assigned_urls", []) if url]
    completed_urls = set(state.get("completed_urls", []))
    navigate_to = next((url for url in assigned_urls if url not in completed_urls), None)
    metadata = dict(state.get("metadata", {}))
    if navigate_to != metadata.get("current_processing_url"):
        metadata["navigation_attempt_count"] = 0
        metadata["extract_attempt_count"] = 0
        metadata["page_category_loop_count"] = 0

    return {
        **state,
        "navigate_to": navigate_to,
        "metadata": {
            **metadata,
            "current_processing_url": navigate_to,
            "select_next_url_status": "ready" if navigate_to else "done",
            "remaining_url_count": sum(1 for url in assigned_urls if url not in completed_urls),
        },
    }
