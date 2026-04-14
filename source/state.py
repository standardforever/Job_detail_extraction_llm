from __future__ import annotations

from typing import Any, TypedDict


class AgentTab(TypedDict):
    agent_index: int
    handle: str | None
    status: str


class AgentAssignment(TypedDict):
    agent_index: int
    status: str
    urls: list[str]
    url_count: int


class NavigationResult(TypedDict):
    agent_index: int
    handle: str | None
    url: str | None
    status: str
    current_url: str | None
    error: str | None


class ExtractedPageContent(TypedDict):
    title: str
    url: str
    markdown: str
    metadata: dict[str, Any]


class NavigationTarget(TypedDict):
    url: str | None
    button: str | None


class PageCategoryResult(TypedDict):
    category: str
    confidence: float
    reason: str
    navigation_target: NavigationTarget


class ButtonClickResult(TypedDict):
    status: str
    target_url: str | None
    target_button: str | None
    current_url: str | None
    error: str | None


class JobPageFeatures(TypedDict):
    filter_present: bool
    filter_types: list[str]
    pagination_present: bool
    pagination_type: str | None
    sort_present: bool
    sort_types: list[str]
    job_detail_target_present: bool
    job_detail_target_types: list[str]
    job_detail_target_count: int


class JobListingPageAnalysis(TypedDict):
    job_urls: list[str]
    filter_present: bool
    filter_types: list[str]
    sort_present: bool
    sort_types: list[str]
    pagination_present: bool
    pagination_type: str | None
    next_page_url: str | None
    load_more_button: str | None
    notes: str


class JobScraperState(TypedDict, total=False):
    grid_url: str
    agent_count: int
    agent_index: int
    urls: list[str]
    assigned_urls: list[str]
    navigate_to: str | None
    completed_urls: list[str]
    completed_job_urls: list[str]
    browser_session: Any
    session_id: str | None
    cdp_url: str | None
    session_established: bool
    agent_tab: AgentTab
    navigation_results: list[NavigationResult]
    extracted_content: ExtractedPageContent | None
    page_category: PageCategoryResult | None
    button_click_result: ButtonClickResult | None
    job_page_features: JobPageFeatures | None
    job_listing_page_analysis: JobListingPageAnalysis | None
    job_urls: list[str]
    selected_job_url: str | None
    job_detail_extracted_content: ExtractedPageContent | None
    structured_job_detail: dict[str, Any] | None
    extracted_jobs: list[dict[str, Any]]
    errors: list[str]
    metadata: dict[str, Any]
