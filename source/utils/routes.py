from state import JobScraperState
from langgraph.graph import END
from services.domain_state import current_domain_metadata, current_domain_record

def _route_after_bootstrap(state: JobScraperState) -> str:
    if state.get("session_established", False):
        return "select_next_url"

    attempt_count = int((state.get("metadata") or {}).get("bootstrap_attempt_count", 0) or 0)
    if attempt_count < 3:
        return "bootstrap_browser"
    return END


def _route_after_select_next_url(state: JobScraperState) -> str:
    if state.get("navigate_to"):
        return "url_extraction"
    return END


def _route_after_url_extraction(state: JobScraperState) -> str:
    metadata = current_domain_metadata(state)
    if str(metadata.get("pipeline_status") or "").strip().lower() == "failed":
        return "select_next_url"
    status = str(metadata.get("url_extraction_status", "") or "").strip().lower()
    if status in {"ready_for_navigation", "seed_url_retained"} and metadata.get("current_candidate_url"):
        return "navigation"
    return "select_next_url"


def _route_after_navigation(state: JobScraperState) -> str:
    metadata = current_domain_metadata(state)
    if str(metadata.get("pipeline_status") or "").strip().lower() == "failed":
        return "select_next_url"
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
    metadata = current_domain_metadata(state)
    if str(metadata.get("pipeline_status") or "").strip().lower() == "failed":
        return "select_next_url"
    extract_status = str(metadata.get("extract_status", "") or "").strip().lower()
    extract_attempt_count = int(metadata.get("extract_attempt_count", 0) or 0)
    navigation_action_status = str(metadata.get("navigation_action_status", "") or "").strip().lower()

    if extract_status == "extracted":
        return "career_page_category"
    if navigation_action_status == "download_started":
        return "select_next_url"
    if state.get("navigate_to") and extract_attempt_count < 3:
        return "navigation"
    return "select_next_url"


def _route_after_career_page_category(state: JobScraperState) -> str:
    metadata = current_domain_metadata(state)
    if str(metadata.get("pipeline_status") or "").strip().lower() == "failed":
        return "select_next_url"
    
    status = str(metadata.get("career_page_scan_status", "") or "").strip().lower()
    if status.endswith("_failed") or str(metadata.get("career_page_category_status") or "").strip().lower() == "failed":
        return "select_next_url"
    if status in {"continue_scanning", "follow_navigation_url"} and metadata.get("current_candidate_url"):
        return "navigation"
    if status == "follow_navigation_button":
        return "button_click"
    if status == "ats_check_required":
        return "ats_check"
    if status in {"external_job_board_found", "external_ats_found"}:
        return "select_next_url"
    if status in {"found_listing_page", "single_job_only_found"}:
        return "next_job_url_selection"
    return "select_next_url"


def _route_after_ats_check(state: JobScraperState) -> str:
    metadata = current_domain_metadata(state)
    if (
        str(metadata.get("pipeline_status") or "").strip().lower() == "failed"
        or str(metadata.get("ats_check_status") or "").strip().lower() == "failed"
    ):
        return "select_next_url"
    processing_mode = str(current_domain_metadata(state).get("processing_mode") or state.get("processing_mode") or "both").strip().lower()
    if processing_mode == "ats_check":
        return "select_next_url"
    _, record = current_domain_record(state)
    job_urls = [url for url in ((record or {}).get("job_urls") or state.get("job_urls", [])) if url]
    if job_urls or metadata.get("embedded_jobs_present"):
        return "next_job_url_selection"
    return "select_next_url"


def _route_after_next_job_url_selection(state: JobScraperState) -> str:
    if str(current_domain_metadata(state).get("pipeline_status") or "").strip().lower() == "failed":
        return "select_next_url"
    processing_mode = str(current_domain_metadata(state).get("processing_mode") or state.get("processing_mode") or "both").strip().lower()
    if processing_mode == "ats_check":
        return "select_next_url"
    _, record = current_domain_record(state)
    if (record or {}).get("selected_job_url") or state.get("selected_job_url"):
        return "job_detail_page_extraction"
    return "select_next_url"


def _route_after_job_detail_page_extraction(state: JobScraperState) -> str:
    metadata = current_domain_metadata(state)
    if str(metadata.get("pipeline_status") or "").strip().lower() == "failed":
        return "next_job_url_selection"
    status = str(metadata.get("job_detail_page_extraction_status", "") or "").strip().lower()
    if status == "extracted":
        return "convert_job_page_to_json"
    return "next_job_url_selection"


def _route_after_convert_job_page_to_json(state: JobScraperState) -> str:
    if str(current_domain_metadata(state).get("pipeline_status") or "").strip().lower() == "failed":
        return "select_next_url"
    _, record = current_domain_record(state)
    job_urls = [url for url in ((record or {}).get("job_urls") or state.get("job_urls", [])) if url]
    completed_job_urls = set((record or {}).get("completed_job_urls") or state.get("completed_job_urls", []))
    if any(url not in completed_job_urls for url in job_urls):
        return "next_job_url_selection"
    return "select_next_url"
