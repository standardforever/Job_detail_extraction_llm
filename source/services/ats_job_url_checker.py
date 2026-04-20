from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from prompts.ats_check_prompt import build_ats_check_prompt
from services.ats_domain_registry import extract_base_domain, get_domain_classification, reconcile_ats_result
from services.content_extraction import extract_page_content
from services.navigation import navigate_to_url
from services.openai_service import OpenAIAnalysisService
from utils.logging import get_logger, log_event


logger = get_logger("ats_job_url_checker")


def _is_document_url(url: str) -> bool:
    path = urlparse(str(url or "").lower()).path
    return path.endswith((".pdf", ".docx", ".doc"))


def _detect_ats_from_url(job_url: str, company_domain: str) -> dict[str, Any]:
    company_domain_clean = extract_base_domain(company_domain) or str(company_domain or "").strip().lower()
    job_domain = extract_base_domain(job_url) or ""
    is_external = bool(job_domain and company_domain_clean and job_domain != company_domain_clean)
    classification = get_domain_classification(job_domain) if job_domain else {
        "status": "unlisted",
        "is_ats": None,
        "is_known_ats": False,
        "is_known_non_ats": False,
    }

    if classification["status"] == "known_ats":
        return {
            "is_ats": True,
            "is_external_application": is_external,
            "is_known_ats": True,
            "ats_provider": job_domain,
            "job_domain": job_domain,
            "company_domain": company_domain_clean,
            "detection_reason": f"Known ATS provider from stored list: {job_domain}",
        }

    if classification["status"] == "known_non_ats":
        return {
            "is_ats": False,
            "is_external_application": is_external,
            "is_known_ats": False,
            "ats_provider": None,
            "job_domain": job_domain,
            "company_domain": company_domain_clean,
            "detection_reason": f"Known non-ATS domain from stored list: {job_domain}",
        }

    return {
        "is_ats": False,
        "is_external_application": is_external,
        "is_known_ats": False,
        "ats_provider": None,
        "job_domain": job_domain,
        "company_domain": company_domain_clean,
        "detection_reason": (
            f"External domain ({job_domain}) differs from company ({company_domain_clean}) but is not in the stored ATS list"
            if is_external
            else "Internal application on company domain and not in the stored ATS list"
        ),
    }


def _normalize_ats_result(response: dict[str, Any]) -> dict[str, Any]:
    indicators = [str(item).strip() for item in (response.get("indicators_found") or []) if str(item).strip()]
    reasoning = str(response.get("reasoning", "") or response.get("reason", "") or "").strip()
    return {
        "is_ats": response.get("is_ats") if "is_ats" in response else None,
        "ats_detected": response.get("is_ats") if "is_ats" in response else None,
        "confidence": str(response.get("confidence", "") or "").strip() or None,
        "ats_provider": str(response.get("ats_provider", "") or "").strip() or None,
        "application_type": str(response.get("application_type", "") or "").strip() or None,
        "apply_url": str(response.get("apply_url", "") or "").strip() or None,
        "apply_button_text": str(response.get("apply_button_text", "") or "").strip() or None,
        "detail_button": str(response.get("detail_button", "") or "").strip() or None,
        "requires_scraping": bool(response.get("requires_scraping", False)),
        "indicators_found": indicators,
        "page_access_status": str(response.get("page_access_status", "") or "").strip() or None,
        "page_access_issue_detail": str(response.get("page_access_issue_detail", "") or "").strip() or None,
        "reasoning": reasoning,
        "is_job_related": response.get("is_job_related"),
    }


async def _process_single_job(
    *,
    page,
    agent_index: int,
    tab_handle: str | None,
    job_url: str,
    domain: str,
) -> dict[str, Any]:
    token_usage = 0

    if _is_document_url(job_url):
        result = {
            "status": "success",
            "job_url": job_url,
            "is_ats": False,
            "is_known_ats": False,
            "is_external_application": False,
            "ats_provider": None,
            "application_type": "document_only",
            "confidence": "high",
            "reasoning": "Job URL points to a document file (.pdf/.docx). Document files are not ATS or application systems.",
            "detection_method": "file_type_rule",
            "token_usage": 0,
        }
        return reconcile_ats_result(result, page_url=job_url, main_domain=domain)

    ats_info = _detect_ats_from_url(job_url, domain)
    if ats_info["is_ats"]:
        result = {
            "status": "success",
            "job_url": job_url,
            "is_ats": True,
            "is_known_ats": ats_info["is_known_ats"],
            "is_external_application": ats_info["is_external_application"],
            "ats_provider": ats_info["ats_provider"],
            "reasoning": ats_info["detection_reason"],
            "confidence": "high",
            "detection_method": "url_pattern",
            "token_usage": 0,
        }
        return reconcile_ats_result(result, page_url=job_url, main_domain=domain)

    navigation_result = await navigate_to_url(
        page,
        agent_index=agent_index,
        tab_handle=tab_handle,
        url=job_url,
        post_navigation_delay_ms=0,
    )
    current_url = str(navigation_result.get("current_url") or job_url or "").strip() or job_url
    if navigation_result["status"] != "navigated":
        return {
            "status": "error",
            "job_url": job_url,
            "current_url": current_url,
            "is_ats": None,
            "confidence": "uncertain",
            "error": navigation_result.get("error"),
            "reasoning": "Navigation failed during ATS processing",
            "token_usage": token_usage,
        }

    extracted_content = await extract_page_content(page)
    if extracted_content is None or not extracted_content.get("markdown"):
        return {
            "status": "error",
            "job_url": job_url,
            "current_url": current_url,
            "is_ats": None,
            "confidence": "uncertain",
            "error": "Unable to extract job page content",
            "reasoning": "Content extraction failed during ATS processing",
            "token_usage": token_usage,
        }

    prompt = build_ats_check_prompt(
        extracted_content["markdown"],
        site_domain=extract_base_domain(current_url),
        main_domain=domain,
        page_url=current_url,
    )
    analysis = await OpenAIAnalysisService().analyze_data(prompt=prompt, json_response=True)
    token_usage += analysis.token_usage if analysis.success else 0

    if not analysis.success:
        return {
            "status": "error",
            "job_url": job_url,
            "current_url": current_url,
            "is_ats": None,
            "confidence": "uncertain",
            "error": analysis.error,
            "reasoning": "AI analysis failed",
            "token_usage": token_usage,
        }

    response = _normalize_ats_result(analysis.response)
    result = {
        "status": "success" if response.get("confidence") in {"high", "medium"} and response.get("is_ats") is not None else "uncertain",
        "job_url": job_url,
        "current_url": current_url,
        "is_ats": response.get("is_ats"),
        "ats_provider": response.get("ats_provider"),
        "confidence": response.get("confidence"),
        "application_type": response.get("application_type"),
        "reasoning": response.get("reasoning"),
        "indicators_found": response.get("indicators_found", []),
        "page_access_status": response.get("page_access_status"),
        "page_access_issue_detail": response.get("page_access_issue_detail"),
        "detection_method": "ai_analysis",
        "requires_scraping": response.get("requires_scraping", False),
        "token_usage": token_usage,
    }
    return reconcile_ats_result(result, page_url=current_url, main_domain=domain)


async def ats_check_job_urls(
    *,
    page,
    agent_index: int,
    tab_handle: str | None,
    jobs: list[str],
    domain: str,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    total_tokens = 0
    found_definitive = False

    for index, job_url in enumerate(jobs):
        result = await _process_single_job(
            page=page,
            agent_index=agent_index,
            tab_handle=tab_handle,
            job_url=job_url,
            domain=domain,
        )
        results.append(result)
        total_tokens += int(result.get("token_usage", 0) or 0)

        if result.get("status") == "success" and result.get("is_ats") is not None:
            found_definitive = True
            log_event(
                logger,
                "info",
                "ats_definitive_result_found job_url=%s is_ats=%s",
                job_url,
                result.get("is_ats"),
                domain=domain,
                job_url=job_url,
                is_ats=result.get("is_ats"),
                confidence=result.get("confidence"),
            )
            break

        log_event(
            logger,
            "info",
            "ats_result_not_definitive_continuing job_url=%s remaining=%s",
            job_url,
            len(jobs) - index - 1,
            domain=domain,
            job_url=job_url,
            status=result.get("status"),
            remaining_jobs=len(jobs) - index - 1,
        )

    return {
        "results": results,
        "total_tokens": total_tokens,
        "jobs_processed": len(results),
        "found_definitive": found_definitive,
    }
