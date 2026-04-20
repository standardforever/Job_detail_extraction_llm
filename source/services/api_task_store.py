from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from services.progress_persistence import sanitize_state_for_storage
from utils.build_result import _build_main_result


_TASKS: dict[str, dict[str, Any]] = {}
_LOCK = Lock()
TASK_STORE_PATH = Path(__file__).resolve().parents[1] / "job_runs" / "tasks.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_artifact_name(value: str | None) -> str:
    normalized = str(value or "").strip()
    if normalized.startswith("job_debug_"):
        normalized = normalized[len("job_debug_") :]
    elif normalized.startswith("job_"):
        normalized = normalized[len("job_") :]
    if normalized and not normalized.endswith(".json"):
        normalized = f"{normalized}.json"
    return normalized


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    temp_path.replace(path)


def _persist_tasks_unlocked() -> None:
    _write_json_atomic(
        TASK_STORE_PATH,
        {
            "updated_at": _utc_now_iso(),
            "task_count": len(_TASKS),
            "tasks": list(_TASKS.values()),
        },
    )


def _ensure_tasks_loaded_unlocked() -> None:
    if _TASKS:
        return
    if not TASK_STORE_PATH.exists():
        return
    try:
        payload = json.loads(TASK_STORE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return
    tasks = payload.get("tasks", []) or []
    if not isinstance(tasks, list):
        return
    for task in tasks:
        if isinstance(task, dict) and task.get("task_id"):
            _TASKS[str(task["task_id"])] = task


def create_task_record(
    *,
    artifact_name: str,
    artifact_path: str,
    request_payload: dict[str, Any],
) -> dict[str, Any]:
    task_id = uuid4().hex
    record = {
        "task_id": task_id,
        "status": "queued",
        "created_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
        "artifact_name": artifact_name,
        "artifact_path": artifact_path,
        "request": request_payload,
        "run_id": None,
        "error": None,
        "main_result": None,
        "run_result": None,
        "progress": {
            "total_urls": len(request_payload.get("urls", []) or []),
            "completed_urls": 0,
            "completed_job_urls": 0,
            "domains_processed": 0,
            "jobs_extracted": 0,
        },
        "stop_requested": False,
        "worker_states": {},
    }
    with _LOCK:
        _ensure_tasks_loaded_unlocked()
        _TASKS[task_id] = record
        _persist_tasks_unlocked()
    return dict(record)


def update_task_record(task_id: str, **updates: Any) -> dict[str, Any] | None:
    with _LOCK:
        _ensure_tasks_loaded_unlocked()
        record = _TASKS.get(task_id)
        if record is None:
            return None
        record.update(updates)
        record["updated_at"] = _utc_now_iso()
        _persist_tasks_unlocked()
        return dict(record)


def get_task_record(task_id: str) -> dict[str, Any] | None:
    with _LOCK:
        _ensure_tasks_loaded_unlocked()
        record = _TASKS.get(task_id)
        return dict(record) if record is not None else None


def list_task_records() -> list[dict[str, Any]]:
    with _LOCK:
        _ensure_tasks_loaded_unlocked()
        records = [dict(record) for record in _TASKS.values()]
    records.sort(key=lambda record: str(record.get("updated_at") or ""), reverse=True)
    return records


def list_task_records_for_artifact(artifact_name: str) -> list[dict[str, Any]]:
    normalized = _normalize_artifact_name(artifact_name)
    records = [record for record in list_task_records() if _normalize_artifact_name(record.get("artifact_name")) == normalized]
    return records


def get_latest_task_record_for_artifact(artifact_name: str) -> dict[str, Any] | None:
    records = list_task_records_for_artifact(artifact_name)
    return records[0] if records else None


def should_stop_task(task_id: str | None) -> bool:
    if not task_id:
        return False
    with _LOCK:
        _ensure_tasks_loaded_unlocked()
        record = _TASKS.get(task_id)
        return bool(record and record.get("stop_requested"))


def request_task_stop(task_id: str) -> dict[str, Any] | None:
    return update_task_record(task_id, stop_requested=True, status="stop_requested")


def clear_task_stop(task_id: str) -> dict[str, Any] | None:
    return update_task_record(task_id, stop_requested=False)


def _build_progress_snapshot(request_payload: dict[str, Any], worker_results: list[dict[str, Any]]) -> dict[str, int]:
    assigned_urls = [str(url).strip() for url in request_payload.get("urls", []) or [] if str(url).strip()]
    completed_urls: set[str] = set()
    completed_job_urls: set[str] = set()
    processed_domains: set[str] = set()
    jobs_extracted = 0

    for worker in worker_results:
        completed_urls.update(str(url) for url in worker.get("completed_urls", []) or [] if url)
        completed_job_urls.update(str(url) for url in worker.get("completed_job_urls", []) or [] if url)
        domain_records = worker.get("domain_records", {}) or {}
        if isinstance(domain_records, dict):
            processed_domains.update(str(key) for key in domain_records.keys() if key)
        jobs_extracted += len(worker.get("extracted_jobs", []) or [])

    return {
        "total_urls": len(assigned_urls),
        "completed_urls": len(completed_urls.intersection(set(assigned_urls))) if assigned_urls else len(completed_urls),
        "completed_job_urls": len(completed_job_urls),
        "domains_processed": len(processed_domains),
        "jobs_extracted": jobs_extracted,
    }


def update_task_worker_state(task_id: str, worker_state: dict[str, Any]) -> dict[str, Any] | None:
    sanitized_worker = sanitize_state_for_storage(worker_state)
    agent_index = sanitized_worker.get("agent_index")
    if agent_index is None:
        return get_task_record(task_id)

    with _LOCK:
        _ensure_tasks_loaded_unlocked()
        record = _TASKS.get(task_id)
        if record is None:
            return None

        worker_states = dict(record.get("worker_states", {}) or {})
        worker_states[str(agent_index)] = sanitized_worker
        worker_results = [
            worker_states[key]
            for key in sorted(worker_states.keys(), key=lambda value: int(value) if str(value).isdigit() else str(value))
        ]
        run_result = {
            "grid_url": sanitized_worker.get("grid_url"),
            "agent_count": record.get("request", {}).get("agent_count", len(worker_results)),
            "urls": list(record.get("request", {}).get("urls", []) or []),
            "assignments": [],
            "worker_results": worker_results,
        }
        progress = _build_progress_snapshot(record.get("request", {}) or {}, worker_results)

        record["worker_states"] = worker_states
        record["run_result"] = run_result
        record["main_result"] = _build_main_result(run_result)
        record["progress"] = progress
        record["updated_at"] = _utc_now_iso()
        _persist_tasks_unlocked()
        return dict(record)


def get_task_resume_state(task_id: str) -> dict[str, Any] | None:
    with _LOCK:
        _ensure_tasks_loaded_unlocked()
        record = _TASKS.get(task_id)
        if record is None:
            return None
        worker_states = dict(record.get("worker_states", {}) or {})
        if not worker_states:
            return None
        worker_results = [
            worker_states[key]
            for key in sorted(worker_states.keys(), key=lambda value: int(value) if str(value).isdigit() else str(value))
        ]
        return {
            "urls": list(record.get("request", {}).get("urls", []) or []),
            "processing_mode": record.get("request", {}).get("processing_mode", "both"),
            "agent_count": record.get("request", {}).get("agent_count", len(worker_results)),
            "worker_results": worker_results,
        }
