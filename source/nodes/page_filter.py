from __future__ import annotations

from state import JobScraperState


async def page_filter_node(state: JobScraperState) -> JobScraperState:
    features = state.get("job_page_features")
    if not features or not features.get("filter_present"):
        return state

    return {
        **state,
        "metadata": {
            **state.get("metadata", {}),
            "page_filter_status": "detected_not_applied",
            "page_filter_types": features.get("filter_types", []),
        },
    }
