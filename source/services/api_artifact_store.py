from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


ARTIFACT_ROOT = Path(__file__).resolve().parents[1] / "job_runs"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_artifact_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name or "").strip())
    cleaned = cleaned.strip("._") or f"job_run_{uuid4().hex[:8]}"
    return cleaned


def _artifact_stem(artifact_name: str | None = None) -> str:
    if artifact_name:
        stem = _sanitize_artifact_name(artifact_name)
    else:
        stem = f"job_run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}"
    if stem.endswith(".json"):
        stem = stem[:-5]
    if stem.startswith("job_debug_"):
        stem = stem[len("job_debug_") :]
    if stem.startswith("job_"):
        stem = stem[len("job_") :]
    return stem


def build_artifact_path(artifact_name: str | None = None) -> Path:
    return ARTIFACT_ROOT / f"job_{_artifact_stem(artifact_name)}.json"


def build_debug_artifact_path(artifact_name: str | None = None) -> Path:
    return ARTIFACT_ROOT / f"job_debug_{_artifact_stem(artifact_name)}.json"


def _debug_artifact_path_for(artifact_path: Path) -> Path:
    name = artifact_path.name
    if name.startswith("job_debug_"):
        return artifact_path
    stem = artifact_path.stem
    if stem.startswith("job_"):
        stem = stem[len("job_") :]
    return artifact_path.with_name(f"job_debug_{stem}.json")


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    temp_path.replace(path)


def _load_artifact_payload(path: Path) -> dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _prepare_run_entry(
    *,
    existing: dict[str, Any],
    request_payload: dict[str, Any],
    run_id: str,
    status: str,
    run_result: dict[str, Any] | None = None,
    main_result: dict[str, Any] | None = None,
    progress: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "created_at": existing.get("created_at") or _utc_now_iso(),
        "updated_at": _utc_now_iso(),
        "status": status,
        "request": request_payload,
        "result": run_result if run_result is not None else existing.get("result"),
        "main_result": main_result if main_result is not None else existing.get("main_result"),
        "progress": progress if progress is not None else existing.get("progress"),
        "error": error if error is not None else existing.get("error"),
    }


def _upsert_run_entry(artifact_data: dict[str, Any], run_entry: dict[str, Any]) -> list[dict[str, Any]]:
    runs = [dict(item) for item in list(artifact_data.get("runs", []) or []) if isinstance(item, dict)]
    existing_index = next((index for index, item in enumerate(runs) if item.get("run_id") == run_entry["run_id"]), None)
    if existing_index is None:
        runs.append(run_entry)
    else:
        runs[existing_index] = run_entry
    return runs


def _build_compact_run_entry(run_entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": run_entry["run_id"],
        "created_at": run_entry["created_at"],
        "updated_at": run_entry["updated_at"],
        "status": run_entry["status"],
        "request": run_entry.get("request"),
        "progress": run_entry.get("progress"),
        "error": run_entry.get("error"),
        "main_result": run_entry.get("main_result"),
    }


def _write_artifact_pair(
    *,
    artifact_path: Path,
    run_entry: dict[str, Any],
) -> dict[str, Any]:
    debug_artifact_path = _debug_artifact_path_for(artifact_path)

    compact_data = _load_artifact_payload(artifact_path)
    debug_data = _load_artifact_payload(debug_artifact_path)

    compact_runs = _upsert_run_entry(compact_data, _build_compact_run_entry(run_entry))
    debug_runs = _upsert_run_entry(debug_data, run_entry)

    compact_payload = {
        "artifact_name": artifact_path.name,
        "artifact_path": str(artifact_path),
        "debug_artifact_name": debug_artifact_path.name,
        "debug_artifact_path": str(debug_artifact_path),
        "created_at": compact_data.get("created_at") or _utc_now_iso(),
        "updated_at": _utc_now_iso(),
        "run_count": len(compact_runs),
        "runs": compact_runs,
    }
    debug_payload = {
        "artifact_name": debug_artifact_path.name,
        "artifact_path": str(debug_artifact_path),
        "job_artifact_name": artifact_path.name,
        "job_artifact_path": str(artifact_path),
        "created_at": debug_data.get("created_at") or _utc_now_iso(),
        "updated_at": _utc_now_iso(),
        "run_count": len(debug_runs),
        "runs": debug_runs,
    }

    _write_json_atomic(artifact_path, compact_payload)
    _write_json_atomic(debug_artifact_path, debug_payload)
    return compact_payload


def append_run_to_artifact(
    *,
    artifact_path: Path,
    request_payload: dict[str, Any],
    run_result: dict[str, Any],
    main_result: dict[str, Any],
    run_id: str | None = None,
) -> dict[str, Any]:
    run_entry = _prepare_run_entry(
        existing={},
        request_payload=request_payload,
        run_id=run_id or uuid4().hex,
        status="completed",
        run_result=run_result,
        main_result=main_result,
    )
    return _write_artifact_pair(artifact_path=artifact_path, run_entry=run_entry)


def upsert_run_to_artifact(
    *,
    artifact_path: Path,
    request_payload: dict[str, Any],
    run_id: str,
    status: str,
    run_result: dict[str, Any] | None = None,
    main_result: dict[str, Any] | None = None,
    progress: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    artifact_data = _load_artifact_payload(_debug_artifact_path_for(artifact_path))
    existing_runs = [dict(item) for item in list(artifact_data.get("runs", []) or []) if isinstance(item, dict)]
    existing_index = next((index for index, item in enumerate(existing_runs) if item.get("run_id") == run_id), None)
    existing = existing_runs[existing_index] if existing_index is not None else {}

    run_entry = _prepare_run_entry(
        existing=existing,
        request_payload=request_payload,
        run_id=run_id,
        status=status,
        run_result=run_result,
        main_result=main_result,
        progress=progress,
        error=error,
    )
    return _write_artifact_pair(artifact_path=artifact_path, run_entry=run_entry)
