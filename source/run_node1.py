from __future__ import annotations

import asyncio
import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from graph import build_graph
from state import JobScraperState
from services.agent_allocator import allocate_urls_to_agents
from services.grid_session import close_agent_tab, create_session_async
from services.pipeline_logging import configure_logging, get_logger


logger = get_logger("run_node1")


def _load_urls(args: argparse.Namespace) -> list[str]:
    urls: list[str] = []

    if args.urls:
        urls.extend(args.urls)

    if args.urls_file:
        urls.extend(Path(args.urls_file).read_text(encoding="utf-8").splitlines())

    return [url.strip() for url in urls if url and url.strip()]


async def _run_agent(graph_input: JobScraperState) -> JobScraperState:
    logger.info(
        "worker_start agent_index=%s assigned_url_count=%s",
        graph_input["agent_index"],
        len(graph_input.get("assigned_urls", [])),
    )
    graph = build_graph()
    result: JobScraperState | None = None
    try:
        if hasattr(graph, "ainvoke"):
            result = await graph.ainvoke(graph_input)
        else:
            result = await graph(graph_input)
        return result
    finally:
        session = (result or graph_input).get("browser_session")
        await close_agent_tab(session)
        if result is not None:
            result.pop("browser_session", None)
        logger.info("worker_finish agent_index=%s", graph_input["agent_index"])


async def _get_shared_cdp_session(grid_url: str | None) -> tuple[str | None, str | None, bool]:
    session_info = await create_session_async(grid_url=grid_url)
    if session_info is None:
        return None, None, False

    return session_info.session_id, session_info.cdp_url, session_info.reused_existing_session


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


def _normalize_domain(value: str | None) -> str:
    if not value:
        return "unknown"
    parsed = urlparse(value)
    host = parsed.netloc.lower().removeprefix("www.")
    return host or "unknown"


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


async def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Run single-agent browser workers in parallel.")
    parser.add_argument("--grid-url", default=None, help="Deprecated Selenium Grid URL option; ignored in Playwright mode")
    parser.add_argument("--agent-count", type=int, default=1, help="Number of parallel agents/tabs")
    parser.add_argument("--urls", nargs="*", default=[], help="URLs to distribute across agents")
    parser.add_argument("--urls-file", default=None, help="Path to a newline-delimited URL file")
    parser.add_argument("--headless", action="store_true", help="Run Playwright browsers in headless mode")
    args = parser.parse_args()

    urls = _load_urls(args)
    assignments = allocate_urls_to_agents(urls, args.agent_count)
    session_id, cdp_url, reused_existing_session = await _get_shared_cdp_session(args.grid_url)
    if not cdp_url:
        result = {
            "grid_url": args.grid_url,
            "agent_count": args.agent_count,
            "urls": urls,
            "assignments": assignments,
            "worker_results": [],
            "errors": ["Unable to establish shared Selenium/CDP session"],
        }
        main_result = _build_main_result(result)
        Path("debug_job.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        Path("main_job.json").write_text(json.dumps(main_result, indent=2, default=str), encoding="utf-8")
        print(json.dumps(main_result, indent=2, default=str))
        return

    worker_results = await asyncio.gather(
        *[
            _run_agent(
                {
                    "grid_url": args.grid_url,
                    "agent_count": args.agent_count,
                    "agent_index": assignment["agent_index"],
                    "assigned_urls": assignment["urls"],
                    "navigate_to": None,
                    "completed_urls": [],
                    "completed_job_urls": [],
                    "job_urls": [],
                    "extracted_jobs": [],
                    "session_id": session_id,
                    "cdp_url": cdp_url,
                    "metadata": {
                        "allocation_status": assignment["status"],
                        "allocated_url_count": assignment["url_count"],
                        "headless": args.headless,
                        "reused_existing_session": reused_existing_session,
                    },
                }
            )
            for assignment in assignments
        ]
    )

    worker_results.sort(key=lambda result: result.get("agent_index", 0))
    result = {
        "grid_url": args.grid_url,
        "agent_count": args.agent_count,
        "urls": urls,
        "assignments": assignments,
        "worker_results": worker_results,
    }

    main_result = _build_main_result(result)
    Path("main_job.json").write_text(json.dumps(main_result, indent=2, default=str), encoding="utf-8")
    Path("debug_job.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    logger.info(
        "artifacts_written main_job=%s debug_job=%s errors=%s job_count=%s token_used=%s",
        "main_job.json",
        "debug_job.json",
        _count_domain_errors(main_result),
        _count_domain_jobs(main_result),
        main_result["token_used"],
    )

    print(json.dumps(main_result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
