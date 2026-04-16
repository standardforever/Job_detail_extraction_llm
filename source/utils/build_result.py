from typing import Any
from urllib.parse import urlparse


def _normalize_domain(value: str | None) -> str:
    if not value:
        return "unknown"
    parsed = urlparse(value)
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


def _build_main_result(raw_result: dict[str, Any]) -> dict[str, Any]:
    worker_results = raw_result.get("worker_results", [])
    domains: dict[str, dict[str, Any]] = {}

    def ensure_domain(domain: str) -> dict[str, Any]:
        if domain not in domains:
            domains[domain] = {
                "errors": [],
                "job_urls": [],
                "non_webpage_job_urls": [],
                "visited_urls": [],
                "jobs": [],
                "token_used": 0,
            }
        return domains[domain]

    for worker_result in worker_results:
        worker_token_used = _collect_int_metadata(worker_result)
        worker_domains: set[str] = set()

        for url in worker_result.get("completed_urls", []):
            if url:
                worker_domains.add(_normalize_domain(url))
        for url in worker_result.get("job_urls", []):
            if url:
                worker_domains.add(_normalize_domain(url))
        for job in worker_result.get("extracted_jobs", []):
            job_url = job.get("job_url") or job.get("page_url")
            if job_url:
                worker_domains.add(_normalize_domain(str(job_url)))
        if not worker_domains:
            worker_domains.add("unknown")

        for error in worker_result.get("errors", []):
            for domain in worker_domains:
                bucket = ensure_domain(domain)
                if error not in bucket["errors"]:
                    bucket["errors"].append(error)

        for url in worker_result.get("job_urls", []):
            if not url:
                continue
            domain = _normalize_domain(url)
            bucket = ensure_domain(domain)
            if url not in bucket["job_urls"]:
                bucket["job_urls"].append(url)

        for url in worker_result.get("completed_urls", []):
            if not url:
                continue
            domain = _normalize_domain(url)
            bucket = ensure_domain(domain)
            if url not in bucket["visited_urls"]:
                bucket["visited_urls"].append(url)

        for url in worker_result.get("completed_job_urls", []):
            if not url:
                continue
            domain = _normalize_domain(url)
            bucket = ensure_domain(domain)
            if url not in bucket["visited_urls"]:
                bucket["visited_urls"].append(url)

        for job in worker_result.get("extracted_jobs", []):
            structured = job.get("structured_data")
            if isinstance(structured, dict):
                job_url = structured.get("job_url") or job.get("job_url") or job.get("page_url")
                domain = _normalize_domain(str(job_url) if job_url else None)
                bucket = ensure_domain(domain)
                bucket["jobs"].append(structured)
                if not structured.get("is_job_page", True) and job_url:
                    if job_url not in bucket["non_webpage_job_urls"]:
                        bucket["non_webpage_job_urls"].append(job_url)

        for domain in worker_domains:
            ensure_domain(domain)["token_used"] += worker_token_used

    return {
        "domains": domains,
        "token_used": _collect_int_metadata(raw_result),
    }


def _count_domain_errors(main_result: dict[str, Any]) -> int:
    return sum(len(domain_data.get("errors", [])) for domain_data in main_result.get("domains", {}).values())


def _count_domain_jobs(main_result: dict[str, Any]) -> int:
    return sum(len(domain_data.get("jobs", [])) for domain_data in main_result.get("domains", {}).values())

