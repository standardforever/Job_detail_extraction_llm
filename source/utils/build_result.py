from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


def _normalize_domain(value: str | None) -> str:
    if not value:
        return "unknown"
    normalized_value = str(value).strip()
    parsed = urlparse(normalized_value if "://" in normalized_value else f"https://{normalized_value}")
    host = parsed.netloc.lower().removeprefix("www.")
    return host or "unknown"


def _collect_int_metadata(value: Any) -> int:
    total = 0
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, int) and "token" in key.lower():
                total += item
            else:
                total += _collect_int_metadata(item)
    elif isinstance(value, list):
        for item in value:
            total += _collect_int_metadata(item)
    return total


def _dedupe_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _dedupe_dicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        marker = repr(sorted(item.items()))
        if marker in seen:
            continue
        seen.add(marker)
        result.append(item)
    return result


def _extract_ats_items(record: dict[str, Any]) -> list[dict[str, Any]]:
    ats_check = record.get("ats_check_result")
    if isinstance(ats_check, dict) and isinstance(ats_check.get("results"), list):
        return [dict(item) for item in ats_check.get("results", []) if isinstance(item, dict)]
    if isinstance(ats_check, dict) and isinstance(ats_check.get("jobs"), list):
        return [dict(item) for item in ats_check.get("jobs", []) if isinstance(item, dict)]
    if isinstance(ats_check, dict):
        return [dict(ats_check)]
    return []


def _classify_ats_item(item: dict[str, Any]) -> str:
    detected = item.get("ats_detected", item.get("is_ats"))
    provider = str(item.get("provider") or item.get("ats_provider") or "").strip() or None
    if detected is True:
        return "ats_true" if provider else "ats_unknown"
    if detected is False:
        return "ats_false"
    return "ats_uncertain"


def _build_ats_breakdown(records: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    breakdown = {
        "ats_true_count": 0,
        "ats_false_count": 0,
        "ats_uncertain_count": 0,
        "ats_unknown_count": 0,
        "ats_true_jobs": [],
        "ats_false_jobs": [],
        "ats_uncertain_jobs": [],
        "ats_unknown_jobs": [],
    }

    for record in records:
        filter_url = (
            str((record.get("metadata", {}) or {}).get("career_page_found_url") or "").strip()
            or str(record.get("navigate_to") or record.get("current_input_url") or "").strip()
            or None
        )
        for ats_item in _extract_ats_items(record):
            job_info = {
                "job_url": ats_item.get("job_url"),
                "filter_url": filter_url,
                "ats_provider": ats_item.get("provider") or ats_item.get("ats_provider"),
                "confidence": ats_item.get("ats_confidence") or ats_item.get("confidence"),
                "reasoning": ats_item.get("reason") or ats_item.get("reasoning"),
                "detection_method": ats_item.get("detection_method") or ats_item.get("application_style") or ats_item.get("application_type"),
                "status": ats_item.get("status"),
                "error": ats_item.get("error"),
            }
            bucket = _classify_ats_item(ats_item)
            if bucket == "ats_true":
                breakdown["ats_true_count"] += 1
                breakdown["ats_true_jobs"].append(job_info)
            elif bucket == "ats_false":
                breakdown["ats_false_count"] += 1
                breakdown["ats_false_jobs"].append(job_info)
            elif bucket == "ats_unknown":
                breakdown["ats_unknown_count"] += 1
                breakdown["ats_unknown_jobs"].append(job_info)
            else:
                breakdown["ats_uncertain_count"] += 1
                breakdown["ats_uncertain_jobs"].append(job_info)

    priority = None
    if breakdown["ats_true_jobs"]:
        first = breakdown["ats_true_jobs"][0]
        priority = {"ats_status": "true", **first}
    elif breakdown["ats_unknown_jobs"]:
        first = breakdown["ats_unknown_jobs"][0]
        priority = {"ats_status": "unknown_ats", **first}
    elif breakdown["ats_false_jobs"]:
        first = breakdown["ats_false_jobs"][0]
        priority = {"ats_status": "false", **first}
    elif breakdown["ats_uncertain_jobs"]:
        first = breakdown["ats_uncertain_jobs"][0]
        priority = {"ats_status": "uncertain", **first}

    return breakdown, priority


def _job_urls_from_analysis(url: str, analysis: dict[str, Any]) -> list[str]:
    listed = []
    for item in analysis.get("jobs_listed_on_page", []) or []:
        if not isinstance(item, dict):
            continue
        job_url = str(item.get("job_url") or "").strip()
        if job_url:
            listed.append(job_url)
    if listed:
        return _dedupe_strings(listed)
    if str(analysis.get("page_category") or "").strip() == "single_job_posting":
        return [url]
    return []


def _build_scrape_results(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scrape_results: list[dict[str, Any]] = []
    for record in records:
        metadata = dict(record.get("metadata", {}) or {})
        llm_reasoning = [dict(item) for item in list(metadata.get("llm_reasoning", []) or []) if isinstance(item, dict)]
        manual_review_required = bool(metadata.get("manual_review_required"))
        message = str(metadata.get("last_manual_review_reason") or "").strip() or None
        visited_urls = []
        for nav in record.get("navigation_results", []) or []:
            if isinstance(nav, dict):
                current_url = str(nav.get("current_url") or nav.get("url") or "").strip()
                if current_url:
                    visited_urls.append(current_url)

        for url, analysis in dict(record.get("career_page_analyses", {}) or {}).items():
            if not isinstance(analysis, dict):
                continue
            page_access_status = str(analysis.get("page_access_status") or "").strip() or None
            page_category = str(analysis.get("page_category") or "").strip()
            job_urls = _job_urls_from_analysis(str(url), analysis)

            if page_access_status and page_access_status != "accessible":
                result_type = "access_blocked"
                status = "failed"
            elif page_category == "navigation_required":
                result_type = "navigation_required"
                status = "success"
            elif page_category in {"jobs_listed", "job_listings_preview_page", "single_job_posting"}:
                result_type = "jobs_found" if job_urls or analysis.get("jobs_listed_on_page") else "success_no_jobs"
                status = "success"
            elif page_category == "not_job_related":
                result_type = "no_jobs_found"
                status = "success"
            else:
                result_type = "unknown"
                status = "failed"

            scrape_results.append(
                {
                    "url": str(url),
                    "status": status,
                    "result_type": result_type,
                    "page_access_status": page_access_status,
                    "page_access_issue_detail": analysis.get("page_access_issue_detail"),
                    "job_alert": analysis.get("job_alert"),
                    "manual_review": manual_review_required,
                    "jobs": {
                        "count": len(job_urls),
                        "job_urls": job_urls,
                    },
                    "ats_check": record.get("ats_check_result"),
                    "scraping_details": {
                        "visited_urls": _dedupe_strings(visited_urls + [str(url)]),
                        "total_tokens": int(analysis.get("analysis_tokens", 0) or 0) + int(metadata.get("job_detail_json_tokens", 0) or 0),
                        "llm_iterations": len(llm_reasoning),
                        "llm_reasoning": llm_reasoning,
                        "message": message or analysis.get("reasoning"),
                    },
                    "error": None,
                }
            )

    return _dedupe_dicts(scrape_results)


def _derive_run_status(
    scrape_results: list[dict[str, Any]],
    ats_detection: dict[str, Any] | None,
    manual_reviews: list[dict[str, Any]],
) -> str:
    if any(result.get("result_type") == "linkedin_indeed_redirect" for result in scrape_results):
        return "LinkedIn/Indeed Redirect"

    blocked = [
        result.get("page_access_status")
        for result in scrape_results
        if result.get("result_type") == "access_blocked"
    ]
    if blocked and len(blocked) == len(scrape_results):
        if "bot_detected" in blocked and "login_required" in blocked:
            return "Access Blocked - Bot Detected / Login Required"
        if "bot_detected" in blocked:
            return "Access Blocked - Bot Detected"
        return "Access Blocked - Login Required"

    if ats_detection is None:
        if any(result.get("job_alert") for result in scrape_results) and manual_reviews:
            return "No Jobs Found - Job Alert Set | Manual Review Required"
        if any(result.get("job_alert") for result in scrape_results):
            return "No Jobs Found - Job Alert Set"
        if manual_reviews:
            return "No Jobs Found - Manual Review Required"
        if any(result.get("jobs", {}).get("count", 0) for result in scrape_results):
            return "Jobs Found"
        return "No Jobs Found"

    if ats_detection["ats_status"] == "true":
        provider = ats_detection.get("ats_provider") or "Unknown"
        return f"ATS Detected - {provider}"
    if ats_detection["ats_status"] == "unknown_ats":
        provider = ats_detection.get("ats_provider") or "Unknown"
        return f"ATS Detected - Unknown ({provider})"
    if ats_detection["ats_status"] == "false":
        return "No ATS - Direct Application"
    if ats_detection["ats_status"] == "uncertain":
        return f"ATS Uncertain - Manual Review Needed ({ats_detection.get('job_url')})"
    return "Completed"


def _build_domain_payload(domain: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    job_urls: list[str] = []
    non_webpage_job_urls: list[str] = []
    visited_urls: list[str] = []
    jobs: list[dict[str, Any]] = []
    manual_reviews: list[dict[str, Any]] = []
    token_used = 0
    discovered_job_urls: list[str] = []
    non_domain_career_urls: list[Any] = []
    latest_ats_check: dict[str, Any] | None = None
    career_url_value: str | None = None
    career_url_reasoning: str | None = None

    for record in records:
        for error in record.get("errors", []) or []:
            if error and error not in errors:
                errors.append(error)
        manual_reviews.extend(
            [
                dict(item)
                for item in list((record.get("metadata", {}) or {}).get("manual_reviews", []) or [])
                if isinstance(item, dict)
            ]
        )
        job_urls.extend(str(url) for url in (record.get("job_urls", []) or []) if url)
        discovered_job_urls.extend(str(url) for url in (record.get("discovered_job_urls", []) or []) if url)
        non_domain_career_urls.extend(list(record.get("non_domain_career_urls", []) or []))
        visited_urls.extend(str(url) for url in (record.get("input_urls", []) or []) if url)
        for result in record.get("navigation_results", []) or []:
            if isinstance(result, dict):
                current_url = result.get("current_url") or result.get("url")
                if current_url:
                    visited_urls.append(str(current_url))
        for url in record.get("completed_job_urls", []) or []:
            if url:
                visited_urls.append(str(url))
        for job in record.get("extracted_jobs", []) or []:
            structured = job.get("structured_data")
            if isinstance(structured, dict):
                job_url = structured.get("job_url") or job.get("job_url") or job.get("page_url")
                jobs.append(structured)
                if not structured.get("is_job_page", True) and job_url:
                    non_webpage_job_urls.append(str(job_url))
        if isinstance(record.get("ats_check_result"), dict):
            latest_ats_check = dict(record["ats_check_result"])
        token_used += _collect_int_metadata(record)

        metadata = dict(record.get("metadata", {}) or {})
        candidate_career_url = (
            str(metadata.get("career_page_found_url") or "").strip()
            or str(record.get("navigate_to") or record.get("current_input_url") or "").strip()
            or None
        )
        if candidate_career_url:
            career_url_value = candidate_career_url
            if not metadata.get("career_page_found_url"):
                career_url_reasoning = "Derived from domain record navigation target."
            else:
                career_url_reasoning = "Derived from discovered career page in scan."

    scrape_results = _build_scrape_results(records)
    ats_breakdown, priority_ats_detection = _build_ats_breakdown(records)
    run_status = _derive_run_status(scrape_results, priority_ats_detection, manual_reviews)

    successful_scrapes = sum(1 for item in scrape_results if item.get("status") == "success")
    failed_scrapes = sum(1 for item in scrape_results if item.get("status") != "success")
    linkedin_indeed_redirects = sum(1 for item in scrape_results if item.get("result_type") == "linkedin_indeed_redirect")
    access_blocked_scrapes = sum(1 for item in scrape_results if item.get("result_type") == "access_blocked")

    return {
        "success": bool(jobs or job_urls or priority_ats_detection or successful_scrapes),
        "run_status": run_status,
        "career_url": {
            "url": career_url_value,
            "confidence": 1.0 if career_url_value else None,
            "reasoning": career_url_reasoning,
        },
        "ats_detection": priority_ats_detection,
        "ats_check": latest_ats_check,
        "errors": _dedupe_strings(errors),
        "job_urls": _dedupe_strings(job_urls),
        "non_webpage_job_urls": _dedupe_strings(non_webpage_job_urls),
        "visited_urls": _dedupe_strings(visited_urls),
        "jobs": _dedupe_dicts(jobs),
        "manual_reviews": _dedupe_dicts(manual_reviews),
        "token_used": token_used,
        "summary": {
            "non_domain_careers_url": _dedupe_dicts([item for item in non_domain_career_urls if isinstance(item, dict)]),
            "job_filtered": _dedupe_strings(discovered_job_urls),
            "urls_checked": len(scrape_results),
            "jobs_found": len(jobs),
            "successful_scrapes": successful_scrapes,
            "failed_scrapes": failed_scrapes,
            "linkedin_indeed_redirects": linkedin_indeed_redirects,
            "access_blocked_scrapes": access_blocked_scrapes,
            "ats_jobs_found": ats_breakdown["ats_true_count"] + ats_breakdown["ats_unknown_count"],
            "ats_breakdown": ats_breakdown,
        },
        "scrape_results": scrape_results,
    }


def _build_main_result(raw_result: dict[str, Any]) -> dict[str, Any]:
    worker_results = raw_result.get("worker_results", [])
    grouped_records: dict[str, list[dict[str, Any]]] = {}

    for worker_result in worker_results:
        domain_records = worker_result.get("domain_records") or {}
        if isinstance(domain_records, dict) and domain_records:
            for key, record in domain_records.items():
                if not isinstance(record, dict):
                    continue
                domain = _normalize_domain(str(record.get("domain") or key or record.get("navigate_to") or record.get("current_input_url") or None))
                grouped_records.setdefault(domain, []).append(record)
            continue

        fallback_domain = "unknown"
        grouped_records.setdefault(fallback_domain, []).append(worker_result)

    domains = {
        domain: _build_domain_payload(domain, records)
        for domain, records in grouped_records.items()
    }

    return {
        "domains": domains,
        "token_used": _collect_int_metadata(raw_result),
    }


def _count_domain_errors(main_result: dict[str, Any]) -> int:
    return sum(len(domain_data.get("errors", [])) for domain_data in main_result.get("domains", {}).values())


def _count_domain_jobs(main_result: dict[str, Any]) -> int:
    return sum(len(domain_data.get("jobs", [])) for domain_data in main_result.get("domains", {}).values())
