from __future__ import annotations

from state import JobScraperState


async def sort_page_node(state: JobScraperState) -> JobScraperState:
    features = state.get("job_page_features")
    if not features or not features.get("sort_present"):
        return state

    return {
        **state,
        "metadata": {
            **state.get("metadata", {}),
            "sort_status": "detected_not_applied",
            "sort_types": features.get("sort_types", []),
        },
    }
