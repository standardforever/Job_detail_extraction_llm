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


def _debug_options(request_payload: dict[str, Any]) -> dict[str, bool]:
    options = dict((request_payload or {}).get("debug_options") or {})
    return {
        "save_markdown": bool(options.get("save_markdown", False)),
        "save_selector_map": bool(options.get("save_selector_map", False)),
        "save_all_urls": bool(options.get("save_all_urls", False)),
        "save_raw_extracted_jobs": bool(options.get("save_raw_extracted_jobs", False)),
        "save_main_result_in_debug": bool(options.get("save_main_result_in_debug", False)),
    }


def _drop_url_heavy_fields(payload: Any) -> Any:
    if isinstance(payload, list):
        return [_drop_url_heavy_fields(item) for item in payload]
    if not isinstance(payload, dict):
        return payload

    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if key in {
            "urls",
            "assigned_urls",
            "discovered_job_urls",
            "non_domain_career_urls",
            "completed_urls",
            "completed_job_urls",
            "job_filtered",
            "non_domain_careers_url",
            "visited_urls",
        }:
            continue
        cleaned[key] = _drop_url_heavy_fields(value)
    return cleaned


def _strip_extracted_content(payload: Any, *, save_markdown: bool, save_selector_map: bool) -> Any:
    if isinstance(payload, list):
        return [
            _strip_extracted_content(item, save_markdown=save_markdown, save_selector_map=save_selector_map)
            for item in payload
        ]
    if not isinstance(payload, dict):
        return payload

    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if key in {"markdown", "raw_markdown"} and not save_markdown:
            continue
        if key == "selector_map" and not save_selector_map:
            continue
        if key == "metadata" and isinstance(value, dict):
            metadata = dict(value)
            if not save_selector_map:
                metadata.pop("selector_map", None)
            cleaned[key] = _strip_extracted_content(
                metadata,
                save_markdown=save_markdown,
                save_selector_map=save_selector_map,
            )
            continue
        cleaned[key] = _strip_extracted_content(
            value,
            save_markdown=save_markdown,
            save_selector_map=save_selector_map,
        )
    return cleaned


def _compact_domain_record(record: dict[str, Any], options: dict[str, bool]) -> dict[str, Any]:
    metadata = dict(record.get("metadata") or {})
    keep_metadata_keys = {
        "allocation_status",
        "allocated_url_count",
        "processing_mode",
        "url_extraction_status",
        "career_page_scan_status",
        "career_navigation_target_source",
        "career_navigation_target_url",
        "career_navigation_target_button",
        "career_page_found_url",
        "ats_check_status",
        "ats_check_mode",
        "job_detail_page_extraction_status",
        "convert_job_page_to_json_status",
        "converted_job_count",
        "converted_jobs_from_page_count",
        "manual_review_required",
        "manual_reviews",
        "last_manual_review_reason",
        "last_manual_review_details",
        "external_ats_status",
        "external_ats_url",
        "external_ats_reason",
        "external_job_board_status",
        "external_job_board_url",
        "external_job_board_provider",
    }
    compact = {
        "domain": record.get("domain"),
        "current_input_url": record.get("current_input_url"),
        "navigate_to": record.get("navigate_to"),
        "errors": record.get("errors", []),
        "metadata": {
            key: value
            for key, value in metadata.items()
            if key in keep_metadata_keys and value not in (None, "", [], {})
        },
        "career_page_analyses": record.get("career_page_analyses", {}),
        "ats_check_result": record.get("ats_check_result"),
        "page_category": record.get("page_category"),
        "structured_job_detail": record.get("structured_job_detail"),
    }
    if options["save_all_urls"]:
        compact.update(
            {
                "input_urls": record.get("input_urls", []),
                "discovered_job_urls": record.get("discovered_job_urls", []),
                "non_domain_career_urls": record.get("non_domain_career_urls", []),
                "job_urls": record.get("job_urls", []),
                "completed_job_urls": record.get("completed_job_urls", []),
                "navigation_results": record.get("navigation_results", []),
            }
        )
    if options["save_raw_extracted_jobs"]:
        compact["extracted_jobs"] = record.get("extracted_jobs", [])
    if options["save_markdown"] or options["save_selector_map"]:
        compact["extracted_content"] = record.get("extracted_content")
        compact["job_detail_extracted_content"] = record.get("job_detail_extracted_content")
    return _strip_extracted_content(
        compact,
        save_markdown=options["save_markdown"],
        save_selector_map=options["save_selector_map"],
    )


def _compact_worker_result(worker: dict[str, Any], options: dict[str, bool]) -> dict[str, Any]:
    domain_records = {
        str(domain): _compact_domain_record(dict(record or {}), options)
        for domain, record in dict(worker.get("domain_records") or {}).items()
    }
    compact = {
        "agent_index": worker.get("agent_index"),
        "agent_count": worker.get("agent_count"),
        "session_established": worker.get("session_established"),
        "session_id": worker.get("session_id"),
        "cdp_url": worker.get("cdp_url"),
        "metadata": worker.get("metadata", {}),
        "domain_records": domain_records,
        "errors": worker.get("errors", []),
    }
    if options["save_all_urls"]:
        compact.update(
            {
                "assigned_urls": worker.get("assigned_urls", []),
                "completed_urls": worker.get("completed_urls", []),
                "completed_job_urls": worker.get("completed_job_urls", []),
            }
        )
    if options["save_raw_extracted_jobs"]:
        compact["extracted_jobs"] = worker.get("extracted_jobs", [])
    return compact


def _build_debug_run_entry(run_entry: dict[str, Any]) -> dict[str, Any]:
    options = _debug_options(dict(run_entry.get("request") or {}))
    request_payload = dict(run_entry.get("request") or {})
    if not options["save_all_urls"]:
        request_payload.pop("urls", None)

    result = dict(run_entry.get("result") or {})
    compact_result = {
        "grid_url": result.get("grid_url"),
        "agent_count": result.get("agent_count"),
        "worker_results": [
            _compact_worker_result(dict(worker or {}), options)
            for worker in list(result.get("worker_results", []) or [])
            if isinstance(worker, dict)
        ],
        "errors": result.get("errors", []),
    }
    if options["save_all_urls"]:
        compact_result["urls"] = result.get("urls", [])
        compact_result["assignments"] = result.get("assignments", [])

    debug_entry = {
        "run_id": run_entry["run_id"],
        "created_at": run_entry["created_at"],
        "updated_at": run_entry["updated_at"],
        "status": run_entry["status"],
        "request": request_payload,
        "progress": run_entry.get("progress"),
        "error": run_entry.get("error"),
        "debug_options": options,
        "result": compact_result,
    }
    if options["save_main_result_in_debug"]:
        main_result = run_entry.get("main_result")
        debug_entry["main_result"] = _drop_url_heavy_fields(main_result) if not options["save_all_urls"] else main_result
    return debug_entry


def _build_compact_run_entry(run_entry: dict[str, Any]) -> dict[str, Any]:
    main_result = dict(run_entry.get("main_result") or {})
    compact_domains: dict[str, Any] = {}
    for domain, payload in dict(main_result.get("domains") or {}).items():
        if not isinstance(payload, dict):
            continue
        compact_domain = {
            "success": payload.get("success"),
            "run_status": payload.get("run_status"),
            "career_url": payload.get("career_url"),
            "ats_detection": payload.get("ats_detection"),
            "ats_check": payload.get("ats_check"),
            "jobs": payload.get("jobs", []),
        }
        if payload.get("listing_pages"):
            compact_domain["listing_pages"] = payload.get("listing_pages")
        if payload.get("errors"):
            compact_domain["errors"] = payload.get("errors")
        if payload.get("manual_reviews"):
            compact_domain["manual_reviews"] = payload.get("manual_reviews")
        if payload.get("token_used"):
            compact_domain["token_used"] = payload.get("token_used")
        compact_domains[str(domain)] = compact_domain

    return {
        "run_id": run_entry["run_id"],
        "created_at": run_entry["created_at"],
        "updated_at": run_entry["updated_at"],
        "status": run_entry["status"],
        "progress": run_entry.get("progress"),
        "error": run_entry.get("error"),
        "domains": compact_domains,
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
    debug_runs = _upsert_run_entry(debug_data, _build_debug_run_entry(run_entry))

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
