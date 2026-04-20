from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from graph import build_graph
from state import JobScraperState
from services.api_task_store import update_task_worker_state
from services.agent_allocator import allocate_urls_to_agents
from services.grid_session import close_agent_tab, create_session_async
from services.progress_persistence import persist_run_progress, sanitize_state_for_storage
from utils.build_result import _build_main_result
from utils.logging import configure_logging, get_logger, log_event


logger = get_logger("job_pipeline_runner")


async def _get_shared_cdp_session(grid_url: str | None) -> tuple[str | None, str | None, bool]:
    session_info = await create_session_async(grid_url=grid_url)
    if session_info is None:
        return None, None, False
    return session_info.session_id, session_info.cdp_url, session_info.reused_existing_session


async def _run_agent(graph_input: JobScraperState) -> JobScraperState:
    assigned_urls = graph_input.get("assigned_urls", [])
    log_event(
        logger,
        "info",
        "worker_start agent_index=%s assigned_url_count=%s",
        graph_input["agent_index"],
        len(assigned_urls),
        domain="run",
        agent_index=graph_input["agent_index"],
        assigned_url_count=len(assigned_urls),
    )
    graph = build_graph()
    result: JobScraperState | None = None
    try:
        if hasattr(graph, "ainvoke"):
            result = await graph.ainvoke(graph_input)
        else:
            result = await graph(graph_input)
        return result
    except Exception as exc:
        if exc.__class__.__name__ == "StopRunRequested" and hasattr(exc, "state"):
            return exc.state
        raise
    finally:
        session = (result or graph_input).get("browser_session")
        await close_agent_tab(session)
        if result is not None:
            result.pop("browser_session", None)
        log_event(
            logger,
            "info",
            "worker_finish agent_index=%s",
            graph_input["agent_index"],
            domain="run",
            agent_index=graph_input["agent_index"],
        )


async def run_job_pipeline(
    *,
    urls: list[str],
    processing_mode: str = "both",
    agent_count: int = 1,
    grid_url: str | None = None,
    headless: bool = False,
    persist_final_debug: bool = True,
    task_id: str | None = None,
    artifact_path: str | None = None,
    resume_result: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    configure_logging()
    if resume_result:
        assignments = [
            {
                "agent_index": worker.get("agent_index", index),
                "status": "resumed",
                "urls": list(worker.get("assigned_urls", []) or []),
                "url_count": len(worker.get("assigned_urls", []) or []),
            }
            for index, worker in enumerate(resume_result.get("worker_results", []) or [])
        ]
    else:
        assignments = allocate_urls_to_agents(urls, agent_count)
    session_id, cdp_url, reused_existing_session = await _get_shared_cdp_session(grid_url)

    if not cdp_url:
        result = {
            "grid_url": grid_url,
            "agent_count": agent_count,
            "urls": urls,
            "assignments": assignments,
            "worker_results": [],
            "errors": ["Unable to establish shared Selenium/CDP session"],
        }
        main_result = _build_main_result(result)
        persist_run_progress(result)
        if persist_final_debug:
            Path("debug_job.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
            Path("main_job.json").write_text(json.dumps(main_result, indent=2, default=str), encoding="utf-8")
        return result, main_result

    persist_run_progress(
        {
            "grid_url": grid_url,
            "agent_count": agent_count,
            "urls": urls,
            "assignments": assignments,
            "worker_results": [],
        }
    )

    if resume_result:
        worker_inputs: list[JobScraperState] = []
        for index, worker in enumerate(resume_result.get("worker_results", []) or []):
            restored_worker: JobScraperState = dict(worker)
            restored_metadata = dict(restored_worker.get("metadata", {}) or {})
            restored_metadata["headless"] = headless
            restored_metadata["processing_mode"] = processing_mode
            restored_metadata["reused_existing_session"] = reused_existing_session
            if task_id:
                restored_metadata["task_id"] = task_id
            if artifact_path:
                restored_metadata["artifact_path"] = artifact_path
            restored_worker["metadata"] = restored_metadata
            restored_worker["grid_url"] = grid_url
            restored_worker["agent_count"] = agent_count
            restored_worker["agent_index"] = restored_worker.get("agent_index", index)
            restored_worker["processing_mode"] = processing_mode
            restored_worker["session_id"] = session_id
            restored_worker["cdp_url"] = cdp_url
            restored_worker["browser_session"] = None
            worker_inputs.append(restored_worker)
    else:
        worker_inputs = [
            {
                "grid_url": grid_url,
                "agent_count": agent_count,
                "agent_index": assignment["agent_index"],
                "assigned_urls": assignment["urls"],
                "navigate_to": None,
                "completed_urls": [],
                "completed_job_urls": [],
                "job_urls": [],
                "domain_records": {},
                "extracted_jobs": [],
                "processing_mode": processing_mode,
                "session_id": session_id,
                "cdp_url": cdp_url,
                "metadata": {
                    "allocation_status": assignment["status"],
                    "allocated_url_count": assignment["url_count"],
                    "headless": headless,
                    "processing_mode": processing_mode,
                    "reused_existing_session": reused_existing_session,
                    "task_id": task_id,
                    "artifact_path": artifact_path,
                },
            }
            for assignment in assignments
        ]

    worker_results = await asyncio.gather(
        *[_run_agent(worker_input) for worker_input in worker_inputs]
    )

    worker_results.sort(key=lambda item: item.get("agent_index", 0))
    result = {
        "grid_url": grid_url,
        "agent_count": agent_count,
        "urls": urls,
        "assignments": assignments,
        "worker_results": worker_results,
    }
    main_result = _build_main_result(result)
    persist_run_progress(result)

    if task_id:
        for worker_result in worker_results:
            update_task_worker_state(task_id, worker_result)

    if persist_final_debug:
        Path("main_job.json").write_text(json.dumps(main_result, indent=2, default=str), encoding="utf-8")
        Path("debug_job.json").write_text(json.dumps(sanitize_state_for_storage(result), indent=2, default=str), encoding="utf-8")

    return result, main_result
