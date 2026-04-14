from __future__ import annotations

import inspect

from services.content_extraction import extract_page_content
from services.domain_job_extraction_registry import get_domain_job_detail_extraction_config
from state import ExtractedPageContent

try:
    from playwright.async_api import Page
except Exception:  # pragma: no cover - handled gracefully at runtime
    Page = None


async def extract_job_detail_page_content(
    page: Page | None,
    page_url: str | None,
) -> ExtractedPageContent | None:
    config = get_domain_job_detail_extraction_config(page_url)
    custom_script = None
    if config.script_builder is not None:
        built_script = config.script_builder()
        custom_script = await built_script if inspect.isawaitable(built_script) else built_script

    return await extract_page_content(
        page,
        sections=config.sections,
        custom_script=custom_script,
    )
