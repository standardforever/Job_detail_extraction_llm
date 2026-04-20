from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from utils.build_result import _build_main_result


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    temp_path.replace(path)


def sanitize_state_for_storage(state: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(state)
    sanitized.pop("browser_session", None)
    sanitized.pop("agent_tab", None)
    return sanitized


def persist_worker_progress(state: dict[str, Any], output_dir: str = "progress_store") -> None:
    agent_index = state.get("agent_index")
    if agent_index is None:
        return

    sanitized_state = sanitize_state_for_storage(state)
    output_root = Path(output_dir)
    state_path = output_root / f"agent_{agent_index}_state.json"
    main_path = output_root / f"agent_{agent_index}_main.json"

    _write_json_atomic(state_path, sanitized_state)
    _write_json_atomic(main_path, _build_main_result({"worker_results": [sanitized_state]}))


def persist_run_progress(raw_result: dict[str, Any], output_dir: str = "progress_store") -> None:
    output_root = Path(output_dir)
    sanitized_result = dict(raw_result)
    worker_results = [sanitize_state_for_storage(worker) for worker in raw_result.get("worker_results", [])]
    sanitized_result["worker_results"] = worker_results

    _write_json_atomic(output_root / "run_state.json", sanitized_result)
    _write_json_atomic(output_root / "run_main.json", _build_main_result(sanitized_result))
