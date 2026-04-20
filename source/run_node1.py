from __future__ import annotations

import asyncio
import argparse
import json

from utils.load_urls import _load_urls
from services.job_pipeline_runner import run_job_pipeline






async def main() -> None:
    parser = argparse.ArgumentParser(description="Run single-agent browser workers in parallel.")
    parser.add_argument("--grid-url", default=None, help="Deprecated Selenium Grid URL option; ignored in Playwright mode")
    parser.add_argument("--agent-count", type=int, default=1, help="Number of parallel agents/tabs")
    parser.add_argument("--urls", nargs="*", default=[], help="URLs to distribute across agents")
    parser.add_argument("--urls-file", default=None, help="Path to a newline-delimited URL file")
    parser.add_argument("--headless", action="store_true", help="Run Playwright browsers in headless mode")
    parser.add_argument(
        "--processing-mode",
        default="both",
        choices=["ats_check", "convert_jobs_to_dict", "both"],
        help="Whether to run ATS checks, convert job detail pages to structured dicts, or do both",
    )
    args = parser.parse_args()

    urls = _load_urls(args)
    _, main_result = await run_job_pipeline(
        urls=urls,
        processing_mode=args.processing_mode,
        agent_count=args.agent_count,
        grid_url=args.grid_url,
        headless=args.headless,
        persist_final_debug=True,
    )
    print(json.dumps(main_result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
