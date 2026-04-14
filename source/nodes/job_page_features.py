from __future__ import annotations

from state import JobScraperState

from services.job_page_features import detect_job_page_features


async def job_page_features_node(state: JobScraperState) -> JobScraperState:
    page_category = state.get("page_category")
    if not page_category or page_category.get("category") != "job_page":
        return {
            **state,
            "job_page_features": None,
        }

    browser_session = state.get("browser_session")
    features = await detect_job_page_features(
        state.get("extracted_content"),
        browser_session.page if browser_session else None,
    )
    return {
        **state,
        "job_page_features": features,
        "metadata": {
            **state.get("metadata", {}),
            "job_page_features_detected": True,
            "job_detail_target_count": features["job_detail_target_count"],
        },
    }
