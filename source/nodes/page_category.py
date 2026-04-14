from __future__ import annotations

from state import JobScraperState, PageCategoryResult

from prompts.page_category_prompt import build_page_category_prompt
from services.openai_service import OpenAIAnalysisService


def _normalize_page_category(response: dict) -> PageCategoryResult:
    navigation_target = response.get("navigation_target") or {}
    return {
        "category": str(response.get("category", "") or ""),
        "confidence": float(response.get("confidence", 0.0) or 0.0),
        "reason": str(response.get("reason", "") or ""),
        "navigation_target": {
            "url": str(navigation_target.get("url")) if navigation_target.get("url") else None,
            "button": str(navigation_target.get("button")) if navigation_target.get("button") else None,
        },
    }


async def page_category_node(state: JobScraperState) -> JobScraperState:
    errors = list(state.get("errors", []))
    extracted_content = state.get("extracted_content")

    if not extracted_content or not extracted_content.get("markdown"):
        errors.append("Cannot categorize page because extracted content is missing")
        return {
            **state,
            "page_category": None,
            "errors": errors,
        }

    prompt = build_page_category_prompt(
        extracted_markdown=extracted_content["markdown"],
        page_url=extracted_content.get("url"),
    )

    service = OpenAIAnalysisService()
    analysis = await service.analyze_data(prompt=prompt, json_response=True)
    if not analysis.success:
        errors.append(f"Page categorization failed: {analysis.error}")
        return {
            **state,
            "page_category": None,
            "errors": errors,
        }

    page_category = _normalize_page_category(analysis.response)
    return {
        **state,
        "page_category": page_category,
        "metadata": {
            **state.get("metadata", {}),
            "page_category_tokens": analysis.token_usage,
        },
    }
