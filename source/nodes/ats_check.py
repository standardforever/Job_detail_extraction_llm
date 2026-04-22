from __future__ import annotations

from typing import Any

from prompts.ats_check_prompt import build_ats_check_prompt
from services.ats_job_url_checker import ats_check_job_urls
from services.ats_domain_registry import reconcile_ats_result
from services.domain_state import append_manual_review, get_domain_key_from_url
from services.domain_state import current_domain_record, set_domain_record
from services.openai_service import OpenAIAnalysisService
from state import JobScraperState


def _normalize_ats_result(response: dict[str, Any]) -> dict[str, Any]:
    indicators = [str(item).strip() for item in (response.get("indicators_found") or []) if str(item).strip()]
    page_validity_issues = [str(item).strip() for item in (response.get("page_validity_issues") or []) if str(item).strip()]
    reasoning = str(response.get("reasoning", "") or response.get("reason", "") or "").strip()
    normalized = {
        "ats_detected": (
            response.get("is_ats")
            if "is_ats" in response
            else response.get("ats_detected") if "ats_detected" in response else None
        ),
        "confidence": str(response.get("confidence", "") or "").strip() or None,
        "is_job_related": bool(response.get("is_job_related", False)),
        "provider": str(response.get("ats_provider", "") or response.get("provider", "") or "").strip() or None,
        "application_style": str(response.get("application_type", "") or response.get("application_style", "") or "").strip() or None,
        "apply_url": str(response.get("apply_url", "") or "").strip() or None,
        "apply_button_text": str(response.get("apply_button_text", "") or "").strip() or None,
        "detail_button": str(response.get("detail_button", "") or "").strip() or None,
        "requires_scraping": bool(response.get("requires_scraping", False)),
        "indicators_found": indicators,
        "page_validity_issues": page_validity_issues or None,
        "additional_notes": str(response.get("additional_notes", "") or "").strip() or None,
        "page_access_status": str(response.get("page_access_status", "") or "").strip() or None,
        "page_access_issue_detail": str(response.get("page_access_issue_detail", "") or "").strip() or None,
        "reason": reasoning,
        "detection_method": str(response.get("detection_method", "") or "").strip() or "ai_analysis",
    }
    page_access_status = str(normalized.get("page_access_status") or "").strip().lower()
    is_accessible = page_access_status in {"", "accessible"}
    has_no_ats_evidence = (
        not normalized.get("provider")
        and not normalized.get("apply_url")
        and not normalized.get("indicators_found")
        and not normalized.get("requires_scraping")
    )
    if normalized.get("ats_detected") is None and is_accessible and normalized.get("is_job_related") and has_no_ats_evidence:
        normalized["ats_detected"] = False
        normalized["confidence"] = normalized.get("confidence") if normalized.get("confidence") in {"high", "medium"} else "high"
        fallback_reason = "Accessible job page with no ATS URL, provider, or indicators; defaulted to non-ATS."
        normalized["reason"] = f"{normalized.get('reason') or ''} {fallback_reason}".strip()
    return normalized


async def ats_check_node(state: JobScraperState) -> JobScraperState:
    domain_key, record = current_domain_record(state)
    record = dict(record or {})
    record_errors = list(record.get("errors", []))
    record_metadata = dict(record.get("metadata", {}) or {})
    browser_session = state.get("browser_session")
    processing_mode = str(record_metadata.get("processing_mode") or state.get("processing_mode") or "both").strip().lower()
    job_urls = [str(url) for url in (record.get("job_urls") or state.get("job_urls", [])) if str(url).strip()]
    extracted_content = record.get("extracted_content") or state.get("extracted_content")
    current_candidate_url = str(record_metadata.get("career_page_found_url") or record_metadata.get("current_candidate_url") or state.get("navigate_to") or "").strip() or None
    main_domain = (
        str(record.get("domain") or "").strip()
        or get_domain_key_from_url(record.get("current_input_url"))
        or get_domain_key_from_url(state.get("navigate_to"))
    )
    site_domain = get_domain_key_from_url(current_candidate_url)

    if processing_mode == "ats_check" and job_urls:
        ats_results = await ats_check_job_urls(
            page=browser_session.page if browser_session else None,
            agent_index=int(state.get("agent_index", 0) or 0),
            tab_handle=((state.get("agent_tab") or {}) or {}).get("handle"),
            jobs=job_urls,
            domain=main_domain or "",
        )
        definitive_result = next(
            (
                item
                for item in ats_results.get("results", [])
                if isinstance(item, dict) and item.get("status") == "success" and item.get("is_ats") is not None
            ),
            None,
        )
        record["errors"] = record_errors
        record["ats_check_result"] = {
            **ats_results,
            "definitive_result": definitive_result,
            "analysis_mode": "job_url_checks",
            "page_url": current_candidate_url,
        }
        record_metadata["ats_check_status"] = "completed"
        record_metadata["ats_check_tokens"] = ats_results.get("total_tokens", 0)
        record_metadata["ats_check_mode"] = "job_url_checks"
        record["metadata"] = record_metadata
        updated_state: JobScraperState = {**state}
        return set_domain_record(updated_state, domain_key, record) if domain_key else updated_state

    if not extracted_content or not extracted_content.get("markdown"):
        return state

    prompt = build_ats_check_prompt(
        extracted_content["markdown"],
        site_domain=site_domain,
        main_domain=main_domain,
        page_url=current_candidate_url,
    )
    service = OpenAIAnalysisService()
    analysis = await service.analyze_data(prompt=prompt, json_response=True)
    if not analysis.success:
        error_message = f"ATS check failed: {analysis.error}"
        record_errors.append(error_message)
        record["errors"] = record_errors
        record_metadata["ats_check_status"] = "failed"
        record["metadata"] = record_metadata
        record = append_manual_review(record, "ats_check_failed", error_message)
        updated_state: JobScraperState = {**state}
        return set_domain_record(updated_state, domain_key, record) if domain_key else updated_state

    ats_result = {
        **_normalize_ats_result(analysis.response),
        "page_url": current_candidate_url,
        "analysis_tokens": analysis.token_usage,
    }
    ats_result = reconcile_ats_result(
        ats_result,
        page_url=current_candidate_url,
        main_domain=main_domain,
    )
    record["errors"] = record_errors
    record["ats_check_result"] = ats_result
    record_metadata["ats_check_status"] = "completed"
    record_metadata["ats_check_tokens"] = analysis.token_usage
    if ats_result.get("requires_scraping"):
        record = append_manual_review(record, "ats_requires_additional_scraping", current_candidate_url or "")
        record_metadata = dict(record.get("metadata", {}) or {})
    record["metadata"] = record_metadata
    updated_state: JobScraperState = {**state}
    return set_domain_record(updated_state, domain_key, record) if domain_key else updated_state
