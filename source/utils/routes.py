from state import JobScraperState
from langgraph.graph import END

def _route_after_bootstrap(state: JobScraperState) -> str:
    if state.get("session_established", False):
        return "select_next_url"

    attempt_count = int((state.get("metadata") or {}).get("bootstrap_attempt_count", 0) or 0)
    if attempt_count < 3:
        return "bootstrap_browser"
    return END


def _route_after_select_next_url(state: JobScraperState) -> str:
    if state.get("navigate_to"):
        return "navigation"
    return END


def _route_after_navigation(state: JobScraperState) -> str:
    metadata = state.get("metadata") or {}
    navigation_status = str(metadata.get("navigation_status", "") or "").strip().lower()
    navigation_attempt_count = int(metadata.get("navigation_attempt_count", 0) or 0)

    if navigation_status == "navigated":
        return "extract_page_content"
    if navigation_status == "navigation_download":
        return "select_next_url"
    if state.get("navigate_to") and navigation_attempt_count < 3:
        return "navigation"
    return "select_next_url"


def _route_after_extract_page_content(state: JobScraperState) -> str:
    metadata = state.get("metadata") or {}
    extract_status = str(metadata.get("extract_status", "") or "").strip().lower()
    extract_attempt_count = int(metadata.get("extract_attempt_count", 0) or 0)
    navigation_action_status = str(metadata.get("navigation_action_status", "") or "").strip().lower()

    if extract_status == "extracted":
        return "page_category"
    if navigation_action_status == "download_started":
        return "select_next_url"
    if state.get("navigate_to") and extract_attempt_count < 3:
        return "navigation"
    return "select_next_url"


def _route_after_page_category(state: JobScraperState) -> str:
    page_category = state.get("page_category") or {}
    category = str(page_category.get("category", "") or "").strip().lower()
    loop_count = int((state.get("metadata") or {}).get("page_category_loop_count", 0) or 0)

    if category == "need_navigation" and loop_count < 3:
        return "button_click"
    if category == "need_navigation":
        return "select_next_url"
    if category == "job_page":
        return "job_page_features"
    return END


def _route_after_next_job_url_selection(state: JobScraperState) -> str:
    if state.get("selected_job_url"):
        return "job_detail_page_extraction"
    return "select_next_url"


def _route_after_job_detail_page_extraction(state: JobScraperState) -> str:
    status = str((state.get("metadata") or {}).get("job_detail_page_extraction_status", "") or "").strip().lower()
    if status == "extracted":
        return "convert_job_page_to_json"
    return "next_job_url_selection"


def _route_after_convert_job_page_to_json(state: JobScraperState) -> str:
    job_urls = [url for url in state.get("job_urls", []) if url]
    completed_job_urls = set(state.get("completed_job_urls", []))
    if any(url not in completed_job_urls for url in job_urls):
        return "next_job_url_selection"
    return "select_next_url"

