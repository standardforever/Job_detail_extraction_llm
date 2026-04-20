from __future__ import annotations

import inspect

from prompts.job_deteail_ats_check import get_job_detail_and_ats_prompt
from prompts.job_detail_to_json_prompt import build_job_detail_to_json_prompt
from services.ats_domain_registry import reconcile_ats_result
from services.domain_job_extraction_registry import get_domain_job_detail_json_converter
from services.domain_state import get_domain_key_from_url
from services.openai_service import OpenAIAnalysisService
from state import ExtractedPageContent


def _normalize_job_detail_json(response: dict) -> dict:
    location = response.get("location") or {}
    salary = response.get("salary") or {}
    hours = response.get("hours") or {}
    closing_date = response.get("closing_date") or {}
    interview_date = response.get("interview_date") or {}
    start_date = response.get("start_date") or {}
    post_date = response.get("post_date") or {}
    contact = response.get("contact") or {}
    application_method = response.get("application_method") or {}
    additional_sections = response.get("additional_sections") or {}

    return {
        "title": str(response.get("title")) if response.get("title") is not None else None,
        "company_name": str(response.get("company_name")) if response.get("company_name") is not None else None,
        "holiday": str(response.get("holiday")) if response.get("holiday") is not None else None,
        "location": {
            "address": str(location.get("address")) if location.get("address") is not None else None,
            "city": str(location.get("city")) if location.get("city") is not None else None,
            "region": str(location.get("region")) if location.get("region") is not None else None,
            "postcode": str(location.get("postcode")) if location.get("postcode") is not None else None,
            "country": str(location.get("country")) if location.get("country") is not None else None,
        },
        "salary": {
            "min": salary.get("min"),
            "max": salary.get("max"),
            "currency": str(salary.get("currency")) if salary.get("currency") is not None else None,
            "period": str(salary.get("period")) if salary.get("period") is not None else None,
            "actual_salary": str(salary.get("actual_salary")) if salary.get("actual_salary") is not None else None,
            "raw_text_salary": str(salary.get("raw_text_salary")) if salary.get("raw_text_salary") is not None else None,
        },
        "job_type": str(response.get("job_type")) if response.get("job_type") is not None else None,
        "contract_type": str(response.get("contract_type")) if response.get("contract_type") is not None else None,
        "remote_option": str(response.get("remote_option")) if response.get("remote_option") is not None else None,
        "hours": {
            "weekly": hours.get("weekly"),
            "daily": hours.get("daily"),
            "details": str(hours.get("details")) if hours.get("details") is not None else None,
        },
        "closing_date": {
            "iso_format": str(closing_date.get("iso_format")) if closing_date.get("iso_format") is not None else None,
            "raw_text": str(closing_date.get("raw_text")) if closing_date.get("raw_text") is not None else None,
        },
        "interview_date": {
            "iso_format": str(interview_date.get("iso_format")) if interview_date.get("iso_format") is not None else None,
            "raw_text": str(interview_date.get("raw_text")) if interview_date.get("raw_text") is not None else None,
        },
        "start_date": {
            "iso_format": str(start_date.get("iso_format")) if start_date.get("iso_format") is not None else None,
            "raw_text": str(start_date.get("raw_text")) if start_date.get("raw_text") is not None else None,
        },
        "post_date": {
            "iso_format": str(post_date.get("iso_format")) if post_date.get("iso_format") is not None else None,
            "raw_text": str(post_date.get("raw_text")) if post_date.get("raw_text") is not None else None,
        },
        "contact": {
            "name": str(contact.get("name")) if contact.get("name") is not None else None,
            "email": str(contact.get("email")) if contact.get("email") is not None else None,
            "phone": str(contact.get("phone")) if contact.get("phone") is not None else None,
        },
        "job_reference": str(response.get("job_reference")) if response.get("job_reference") is not None else None,
        "description": str(response.get("description")) if response.get("description") is not None else None,
        "responsibilities": [str(item) for item in (response.get("responsibilities") or []) if item],
        "requirements": [str(item) for item in (response.get("requirements") or []) if item],
        "benefits": [str(item) for item in (response.get("benefits") or []) if item],
        "company_info": str(response.get("company_info")) if response.get("company_info") is not None else None,
        "how_to_apply": str(response.get("how_to_apply")) if response.get("how_to_apply") is not None else None,
        "additional_sections": (
            {
                str(key): str(value)
                for key, value in additional_sections.items()
                if key and value is not None
            }
            if isinstance(additional_sections, dict)
            else {}
        ),
        "is_job_page": bool(response.get("is_job_page", True)),
        "confidence_reason": str(response.get("confidence_reason", "") or ""),
        "application_method": {
            "type": str(application_method.get("type")) if application_method.get("type") is not None else None,
            "url": str(application_method.get("url")) if application_method.get("url") is not None else None,
            "email": str(application_method.get("email")) if application_method.get("email") is not None else None,
            "instructions": str(application_method.get("instructions")) if application_method.get("instructions") is not None else None,
        },
    }


def _normalize_job_detail_and_ats_json(response: dict, *, page_url: str | None = None, main_domain: str | None = None) -> dict:
    normalized = _normalize_job_detail_json(response)
    indicators = [str(item) for item in (response.get("indicators_found") or []) if item]
    validity_issues = [str(item) for item in (response.get("page_validity_issues") or []) if item]
    normalized.update(
        {
            "is_ats": response.get("is_ats") if "is_ats" in response else None,
            "is_job_related": bool(response.get("is_job_related", normalized.get("is_job_page", False))),
            "ats_confidence": str(response.get("ats_confidence")) if response.get("ats_confidence") is not None else None,
            "application_type": str(response.get("application_type")) if response.get("application_type") is not None else None,
            "ats_provider": str(response.get("ats_provider")) if response.get("ats_provider") is not None else None,
            "apply_url": str(response.get("apply_url")) if response.get("apply_url") is not None else None,
            "apply_button_text": str(response.get("apply_button_text")) if response.get("apply_button_text") is not None else None,
            "detail_button": str(response.get("detail_button")) if response.get("detail_button") is not None else None,
            "requires_scraping": bool(response.get("requires_scraping", False)),
            "indicators_found": indicators,
            "page_validity_issues": validity_issues or None,
            "additional_notes": str(response.get("additional_notes")) if response.get("additional_notes") is not None else None,
            "page_access_status": str(response.get("page_access_status")) if response.get("page_access_status") is not None else None,
            "page_access_issue_detail": str(response.get("page_access_issue_detail")) if response.get("page_access_issue_detail") is not None else None,
        }
    )
    return reconcile_ats_result(normalized, page_url=page_url, main_domain=main_domain)


def _normalize_job_detail_json_list(response: dict | list) -> list[dict]:
    if isinstance(response, list):
        return [_normalize_job_detail_json(item) for item in response if isinstance(item, dict)]
    if isinstance(response, dict):
        jobs = response.get("jobs")
        if isinstance(jobs, list):
            return [_normalize_job_detail_json(item) for item in jobs if isinstance(item, dict)]
        return [_normalize_job_detail_json(response)]
    return []


def _normalize_job_detail_and_ats_json_list(response: dict | list, *, page_url: str | None = None, main_domain: str | None = None) -> list[dict]:
    if isinstance(response, list):
        return [
            _normalize_job_detail_and_ats_json(item, page_url=page_url, main_domain=main_domain)
            for item in response
            if isinstance(item, dict)
        ]
    if isinstance(response, dict):
        jobs = response.get("jobs")
        if isinstance(jobs, list):
            return [
                _normalize_job_detail_and_ats_json(item, page_url=page_url, main_domain=main_domain)
                for item in jobs
                if isinstance(item, dict)
            ]
        return [_normalize_job_detail_and_ats_json(response, page_url=page_url, main_domain=main_domain)]
    return []


async def convert_job_detail_content_to_json(
    extracted_content: ExtractedPageContent,
    processing_mode: str = "convert_jobs_to_dict",
    main_domain: str | None = None,
) -> tuple[list[dict] | None, int, str]:
    page_url = extracted_content.get("url")
    normalized_processing_mode = str(processing_mode or "convert_jobs_to_dict").strip().lower()
    custom_converter = get_domain_job_detail_json_converter(page_url)
    if custom_converter is not None and normalized_processing_mode != "both":
        result = custom_converter(extracted_content)
        structured = await result if inspect.isawaitable(result) else result
        normalized_jobs = _normalize_job_detail_json_list(structured)
        return normalized_jobs or None, 0, "" if normalized_jobs else "Invalid custom converter response"

    if normalized_processing_mode == "both":
        resolved_main_domain = main_domain or get_domain_key_from_url(page_url) or ""
        prompt = get_job_detail_and_ats_prompt(
            page_text=extracted_content.get("markdown", ""),
            site_domain=get_domain_key_from_url(page_url),
            main_domain=resolved_main_domain,
            page_url=page_url,
        )
    else:
        prompt = build_job_detail_to_json_prompt(
            extracted_markdown=extracted_content.get("markdown", ""),
            page_url=page_url,
        )
    service = OpenAIAnalysisService()
    analysis = await service.analyze_data(prompt=prompt, json_response=True)
    if not analysis.success:
        return None, 0, analysis.error

    normalized_jobs = (
        _normalize_job_detail_and_ats_json_list(analysis.response, page_url=page_url, main_domain=resolved_main_domain)
        if normalized_processing_mode == "both"
        else _normalize_job_detail_json_list(analysis.response)
    )
    return normalized_jobs or None, analysis.token_usage, "" if normalized_jobs else "Invalid model response"
