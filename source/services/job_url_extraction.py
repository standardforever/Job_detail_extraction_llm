from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from prompts.job_url_extraction_prompt import build_job_url_extraction_prompt
from services.openai_service import OpenAIAnalysisService
from state import JobListingPageAnalysis


def _extract_visible_markdown_job_links(extracted_markdown: str, page_url: str | None) -> list[str]:
    lines = extracted_markdown.splitlines()
    candidates: list[str] = []
    seen: set[str] = set()

    for index, line in enumerate(lines):
        for label, url in re.findall(r"\[([^\]]+)\]\(([^)]+)\)", line):
            absolute_url = urljoin(page_url or "", url.strip())
            parsed = urlparse(absolute_url)
            if not parsed.scheme or not parsed.netloc:
                continue
            if absolute_url in seen:
                continue

            label_text = label.strip().lower()
            context_window = " ".join(lines[max(0, index - 2): min(len(lines), index + 3)]).lower()
            same_page = page_url and absolute_url.rstrip("/") == str(page_url).rstrip("/")
            looks_like_job_link = any(
                token in label_text or token in context_window
                for token in ("apply", "role", "job", "position", "opening", "vacanc", "deadline")
            )
            noisy_link = any(
                token in absolute_url.lower() or token in label_text
                for token in ("cookiedatabase", "#main", "manage options", "manage services", "vendor")
            )
            if same_page or noisy_link or not looks_like_job_link:
                continue

            seen.add(absolute_url)
            candidates.append(absolute_url)

    return candidates


def _normalize_job_listing_page_analysis(
    response: dict,
    page_url: str | None,
    extracted_markdown: str,
) -> JobListingPageAnalysis:
    raw_urls = response.get("job_urls") or []
    normalized_job_urls: list[str] = []
    seen_urls: set[str] = set()

    for raw_url in raw_urls:
        if not raw_url:
            continue
        candidate = urljoin(page_url or "", str(raw_url).strip())
        parsed = urlparse(candidate)
        if not parsed.scheme or not parsed.netloc:
            continue
        if candidate in seen_urls:
            continue
        seen_urls.add(candidate)
        normalized_job_urls.append(candidate)

    if not normalized_job_urls:
        for candidate in _extract_visible_markdown_job_links(extracted_markdown, page_url):
            if candidate in seen_urls:
                continue
            seen_urls.add(candidate)
            normalized_job_urls.append(candidate)

    pagination_type = response.get("pagination_type")
    if pagination_type not in {"numbered", "next_previous", "load_more"}:
        pagination_type = None

    next_page_url = response.get("next_page_url")
    if next_page_url:
        next_page_url = urljoin(page_url or "", str(next_page_url).strip())

    notes = str(response.get("notes", "") or "")
    if normalized_job_urls and not response.get("job_urls"):
        notes = f"{notes} Visible markdown links were used as a fallback for job_urls.".strip()

    return {
        "job_urls": normalized_job_urls,
        "filter_present": bool(response.get("filter_present", False)),
        "filter_types": [str(item) for item in (response.get("filter_types") or []) if item],
        "sort_present": bool(response.get("sort_present", False)),
        "sort_types": [str(item) for item in (response.get("sort_types") or []) if item],
        "pagination_present": bool(response.get("pagination_present", False)),
        "pagination_type": pagination_type,
        "next_page_url": str(next_page_url) if next_page_url else None,
        "load_more_button": str(response.get("load_more_button")) if response.get("load_more_button") else None,
        "notes": notes,
    }


async def extract_job_listing_page_analysis(
    extracted_markdown: str,
    page_url: str | None,
    known_features: dict | None = None,
) -> tuple[JobListingPageAnalysis | None, int, str]:
    prompt = build_job_url_extraction_prompt(
        extracted_markdown=extracted_markdown,
        page_url=page_url,
        known_features=known_features,
    )

    service = OpenAIAnalysisService()
    analysis = await service.analyze_data(prompt=prompt, json_response=True)
    if not analysis.success:
        return None, 0, analysis.error

    return _normalize_job_listing_page_analysis(analysis.response, page_url, extracted_markdown), analysis.token_usage, ""
