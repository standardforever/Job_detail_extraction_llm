from __future__ import annotations

import csv
import io
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

from schemas.job_api import (
    JobRunProgressResponse,
    JobRunTaskListResponse,
    JobRunTaskResponse,
    JobRunTaskStatusResponse,
    ProcessingMode,
    URLListRunRequest,
)
from core.config import get_settings
from services.api_artifact_store import build_artifact_path, upsert_run_to_artifact
from services.api_task_store import (
    clear_task_stop,
    create_task_record,
    get_latest_task_record_for_artifact,
    get_task_resume_state,
    get_task_record,
    list_task_records_for_artifact,
    list_task_records,
    request_task_stop,
    update_task_record,
)
from services.job_pipeline_runner import run_job_pipeline
from utils.logging import get_logger, log_event


logger = get_logger("api")
router = APIRouter(tags=["job-runs"])


def _parse_csv_urls(file_bytes: bytes) -> list[str]:
    decoded = file_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(decoded))
    if "url" not in (reader.fieldnames or []):
        raise HTTPException(status_code=400, detail="CSV must contain a 'url' column")
    urls = [str(row.get("url") or "").strip() for row in reader if str(row.get("url") or "").strip()]
    if not urls:
        raise HTTPException(status_code=400, detail="CSV did not contain any non-empty url values")
    return urls


def _build_domain_response(task_record: dict) -> dict[str, dict]:
    main_result = dict(task_record.get("main_result") or {})
    return {
        str(domain_key): dict(payload)
        for domain_key, payload in dict(main_result.get("domains") or {}).items()
        if isinstance(payload, dict)
    }


def _build_task_status_response(task_record: dict) -> JobRunTaskStatusResponse:
    return JobRunTaskStatusResponse(
        task_id=task_record["task_id"],
        status=task_record["status"],
        artifact_name=task_record["artifact_name"],
        artifact_path=task_record["artifact_path"],
        run_id=task_record.get("run_id"),
        error=task_record.get("error"),
        progress=task_record.get("progress"),
        stop_requested=task_record.get("stop_requested"),
        domains=_build_domain_response(task_record),
    )


def _build_task_progress_response(task_record: dict) -> JobRunProgressResponse:
    return JobRunProgressResponse(
        task_id=task_record["task_id"],
        status=task_record["status"],
        artifact_name=task_record["artifact_name"],
        artifact_path=task_record["artifact_path"],
        progress=task_record.get("progress"),
        error=task_record.get("error"),
        domains=_build_domain_response(task_record),
    )


async def _execute_run_task(
    *,
    task_id: str,
    artifact_name: str,
    artifact_path: str,
    request_payload: dict,
    urls: list[str],
    processing_mode: str,
    agent_count: int,
    grid_url: str | None,
    headless: bool,
    resume_state: dict | None = None,
) -> None:
    update_task_record(task_id, status="running")
    upsert_run_to_artifact(
        artifact_path=Path(artifact_path),
        request_payload=request_payload,
        run_id=task_id,
        status="running",
    )
    log_event(
        logger,
        "info",
        "api_run_started task_id=%s url_count=%s processing_mode=%s agent_count=%s artifact_name=%s",
        task_id,
        len(urls),
        processing_mode,
        agent_count,
        artifact_name,
        domain="api",
        task_id=task_id,
        url_count=len(urls),
        processing_mode=processing_mode,
        agent_count=agent_count,
        artifact_name=artifact_name,
    )
    try:
        run_result, main_result = await run_job_pipeline(
            urls=urls,
            processing_mode=processing_mode,
            agent_count=agent_count,
            grid_url=grid_url,
            headless=headless,
            persist_final_debug=False,
            task_id=task_id,
            artifact_path=artifact_path,
            resume_result=resume_state,
        )
        worker_results = list(run_result.get("worker_results", []) or [])
        is_stopped = any(
            str((worker.get("metadata", {}) or {}).get("task_status", "")).lower() == "stopped"
            for worker in worker_results
        )
        final_status = "stopped" if is_stopped else "completed"
        artifact_payload = upsert_run_to_artifact(
            artifact_path=Path(artifact_path),
            request_payload=request_payload,
            run_id=task_id,
            status=final_status,
            run_result=run_result,
            main_result=main_result,
            progress={
                "total_urls": len(urls),
                "completed_urls": len({url for worker in worker_results for url in worker.get("completed_urls", []) or []}),
                "completed_job_urls": len({url for worker in worker_results for url in worker.get("completed_job_urls", []) or []}),
                "domains_processed": len({domain for worker in worker_results for domain in ((worker.get("domain_records") or {}).keys())}),
                "jobs_extracted": sum(len(worker.get("extracted_jobs", []) or []) for worker in worker_results),
            },
        )
        update_task_record(
            task_id,
            status=final_status,
            run_id=task_id,
            main_result=main_result,
            run_result=run_result,
        )
        log_event(
            logger,
            "info",
            "api_run_completed artifact_name=%s run_id=%s run_count=%s task_id=%s",
            artifact_name,
            task_id,
            artifact_payload["run_count"],
            task_id,
            domain="api",
            artifact_name=artifact_name,
            run_id=task_id,
            run_count=artifact_payload["run_count"],
            task_id=task_id,
            final_status=final_status,
        )
    except Exception as exc:
        update_task_record(task_id, status="failed", error=str(exc))
        upsert_run_to_artifact(
            artifact_path=Path(artifact_path),
            request_payload=request_payload,
            run_id=task_id,
            status="failed",
            error=str(exc),
        )
        log_event(
            logger,
            "error",
            "api_run_failed task_id=%s artifact_name=%s error=%s",
            task_id,
            artifact_name,
            str(exc),
            domain="api",
            task_id=task_id,
            artifact_name=artifact_name,
            error=str(exc),
        )


def _queue_run(
    *,
    background_tasks: BackgroundTasks,
    urls: list[str],
    processing_mode: str,
    agent_count: int,
    artifact_name: str | None,
) -> JobRunTaskResponse:
    settings = get_settings()
    grid_url = settings.selenium_remote_url
    headless = False
    artifact_path = build_artifact_path(artifact_name)
    request_payload = {
        "urls": urls,
        "processing_mode": processing_mode,
        "agent_count": agent_count,
        "artifact_name": artifact_name,
    }
    task_record = create_task_record(
        artifact_name=artifact_path.name,
        artifact_path=str(artifact_path),
        request_payload=request_payload,
    )
    upsert_run_to_artifact(
        artifact_path=artifact_path,
        request_payload=request_payload,
        run_id=task_record["task_id"],
        status="queued",
        progress=task_record.get("progress"),
    )
    background_tasks.add_task(
        _execute_run_task,
        task_id=task_record["task_id"],
        artifact_name=artifact_path.name,
        artifact_path=str(artifact_path),
        request_payload=request_payload,
        urls=urls,
        processing_mode=processing_mode,
        agent_count=agent_count,
        grid_url=grid_url,
        headless=headless,
    )
    return JobRunTaskResponse(
        task_id=task_record["task_id"],
        status=task_record["status"],
        artifact_name=task_record["artifact_name"],
        artifact_path=task_record["artifact_path"],
    )


@router.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/tasks", response_model=JobRunTaskListResponse)
async def get_all_tasks() -> JobRunTaskListResponse:
    task_records = list_task_records()
    return JobRunTaskListResponse(
        tasks=[_build_task_status_response(task_record) for task_record in task_records],
        total=len(task_records),
    )


@router.get("/runs/{artifact_name}/tasks", response_model=JobRunTaskListResponse)
async def get_artifact_tasks(artifact_name: str) -> JobRunTaskListResponse:
    task_records = list_task_records_for_artifact(artifact_name)
    return JobRunTaskListResponse(
        tasks=[_build_task_status_response(task_record) for task_record in task_records],
        total=len(task_records),
    )


@router.get("/artifacts/{artifact_name}/tasks", response_model=JobRunTaskListResponse, include_in_schema=False)
async def get_artifact_tasks_legacy(artifact_name: str) -> JobRunTaskListResponse:
    return await get_artifact_tasks(artifact_name)


@router.get("/runs/{artifact_name}", response_model=JobRunTaskStatusResponse)
async def get_artifact_status(artifact_name: str) -> JobRunTaskStatusResponse:
    task_record = get_latest_task_record_for_artifact(artifact_name)
    if task_record is None:
        raise HTTPException(status_code=404, detail="Artifact task not found")
    return _build_task_status_response(task_record)


@router.get("/artifacts/{artifact_name}", response_model=JobRunTaskStatusResponse, include_in_schema=False)
async def get_artifact_status_legacy(artifact_name: str) -> JobRunTaskStatusResponse:
    return await get_artifact_status(artifact_name)


@router.get("/runs/{artifact_name}/progress", response_model=JobRunProgressResponse)
async def get_artifact_progress(artifact_name: str) -> JobRunProgressResponse:
    task_record = get_latest_task_record_for_artifact(artifact_name)
    if task_record is None:
        raise HTTPException(status_code=404, detail="Artifact task not found")
    return _build_task_progress_response(task_record)


@router.get("/artifacts/{artifact_name}/progress", response_model=JobRunProgressResponse, include_in_schema=False)
async def get_artifact_progress_legacy(artifact_name: str) -> JobRunProgressResponse:
    return await get_artifact_progress(artifact_name)


@router.get("/tasks/{task_id}", response_model=JobRunTaskStatusResponse, include_in_schema=False)
async def get_task_status(task_id: str) -> JobRunTaskStatusResponse:
    task_record = get_task_record(task_id)
    if task_record is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return _build_task_status_response(task_record)


@router.get("/runs/{task_id}/progress", response_model=JobRunProgressResponse, include_in_schema=False)
async def get_run_progress(task_id: str) -> JobRunProgressResponse:
    task_record = get_task_record(task_id)
    if task_record is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return _build_task_progress_response(task_record)


@router.post("/runs/urls", response_model=JobRunTaskResponse, status_code=202)
async def run_from_url_list(payload: URLListRunRequest, background_tasks: BackgroundTasks) -> JobRunTaskResponse:
    return _queue_run(
        background_tasks=background_tasks,
        urls=payload.urls,
        processing_mode=payload.processing_mode,
        agent_count=payload.agent_count,
        artifact_name=payload.artifact_name,
    )


@router.post("/runs/csv", response_model=JobRunTaskResponse, status_code=202)
async def run_from_csv(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    processing_mode: ProcessingMode = Form("both"),
    agent_count: int = Form(1),
    artifact_name: str | None = Form(None),
) -> JobRunTaskResponse:
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Uploaded file must be a CSV")
    urls = _parse_csv_urls(await file.read())
    return _queue_run(
        background_tasks=background_tasks,
        urls=urls,
        processing_mode=processing_mode,
        agent_count=agent_count,
        artifact_name=artifact_name,
    )


@router.post("/tasks/{task_id}/stop", response_model=JobRunTaskStatusResponse, include_in_schema=False)
async def stop_task(task_id: str) -> JobRunTaskStatusResponse:
    task_record = request_task_stop(task_id)
    if task_record is None:
        raise HTTPException(status_code=404, detail="Task not found")
    upsert_run_to_artifact(
        artifact_path=Path(task_record["artifact_path"]),
        request_payload=task_record.get("request", {}) or {},
        run_id=task_id,
        status="stop_requested",
        run_result=task_record.get("run_result"),
        main_result=task_record.get("main_result"),
        progress=task_record.get("progress"),
        error=task_record.get("error"),
    )
    return _build_task_status_response(task_record)


@router.post("/runs/{artifact_name}/stop", response_model=JobRunTaskStatusResponse)
async def stop_artifact_task(artifact_name: str) -> JobRunTaskStatusResponse:
    task_record = get_latest_task_record_for_artifact(artifact_name)
    if task_record is None:
        raise HTTPException(status_code=404, detail="Artifact task not found")
    return await stop_task(task_record["task_id"])


@router.post("/artifacts/{artifact_name}/stop", response_model=JobRunTaskStatusResponse, include_in_schema=False)
async def stop_artifact_task_legacy(artifact_name: str) -> JobRunTaskStatusResponse:
    return await stop_artifact_task(artifact_name)


@router.post("/tasks/{task_id}/resume", response_model=JobRunTaskResponse, status_code=202, include_in_schema=False)
async def resume_task(task_id: str, background_tasks: BackgroundTasks) -> JobRunTaskResponse:
    task_record = get_task_record(task_id)
    if task_record is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task_record.get("status") not in {"stopped", "stop_requested", "failed"}:
        raise HTTPException(status_code=400, detail="Task is not in a resumable state")

    resume_state = get_task_resume_state(task_id)
    if not resume_state:
        raise HTTPException(status_code=400, detail="No saved progress found for this task")

    request_payload = dict(task_record.get("request", {}) or {})
    clear_task_stop(task_id)
    update_task_record(task_id, status="queued", error=None)
    upsert_run_to_artifact(
        artifact_path=Path(task_record["artifact_path"]),
        request_payload=request_payload,
        run_id=task_id,
        status="queued",
        run_result=task_record.get("run_result"),
        main_result=task_record.get("main_result"),
        progress=task_record.get("progress"),
    )
    settings = get_settings()
    background_tasks.add_task(
        _execute_run_task,
        task_id=task_id,
        artifact_name=task_record["artifact_name"],
        artifact_path=task_record["artifact_path"],
        request_payload=request_payload,
        urls=list(request_payload.get("urls", []) or []),
        processing_mode=request_payload.get("processing_mode", "both"),
        agent_count=int(request_payload.get("agent_count", 1) or 1),
        grid_url=settings.selenium_remote_url,
        headless=False,
        resume_state=resume_state,
    )
    return JobRunTaskResponse(
        task_id=task_id,
        status="queued",
        artifact_name=task_record["artifact_name"],
        artifact_path=task_record["artifact_path"],
    )


@router.post("/runs/{artifact_name}/resume", response_model=JobRunTaskResponse, status_code=202)
async def resume_artifact_task(artifact_name: str, background_tasks: BackgroundTasks) -> JobRunTaskResponse:
    task_record = get_latest_task_record_for_artifact(artifact_name)
    if task_record is None:
        raise HTTPException(status_code=404, detail="Artifact task not found")
    return await resume_task(task_record["task_id"], background_tasks)


@router.post("/artifacts/{artifact_name}/resume", response_model=JobRunTaskResponse, status_code=202, include_in_schema=False)
async def resume_artifact_task_legacy(artifact_name: str, background_tasks: BackgroundTasks) -> JobRunTaskResponse:
    return await resume_artifact_task(artifact_name, background_tasks)
