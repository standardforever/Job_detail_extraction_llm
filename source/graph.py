from __future__ import annotations

from pathlib import Path
from typing import Awaitable, Callable

from langgraph.graph import END, START, StateGraph

from state import JobScraperState

from nodes.ats_check import ats_check_node
from nodes.button_click import button_click_node
from nodes.career_page_category import career_page_category_node
from nodes.convert_job_page_to_json import convert_job_page_to_json_node
from nodes.extract_page_content import extract_page_content_node
from nodes.job_detail_page_extraction import job_detail_page_extraction_node
from nodes.navigation import navigation_node
from nodes.next_job_url_selection import next_job_url_selection_node
from nodes.select_next_url import select_next_url_node
from nodes.session_bootstrap import bootstrap_browser_node
from nodes.url_extraction import career_url_extraction_node
from services.api_artifact_store import upsert_run_to_artifact
from services.api_task_store import should_stop_task, update_task_record, update_task_worker_state
from services.domain_state import current_domain_record, set_domain_record
from services.progress_persistence import persist_worker_progress
from utils.routes import (
    _route_after_bootstrap, _route_after_select_next_url, _route_after_url_extraction, _route_after_navigation,
    _route_after_career_page_category, _route_after_ats_check,
    _route_after_convert_job_page_to_json, _route_after_extract_page_content, _route_after_job_detail_page_extraction,
    _route_after_next_job_url_selection
)


class StopRunRequested(Exception):
    def __init__(self, state: JobScraperState):
        super().__init__("Run stop requested")
        self.state = state


def _persist_api_task_progress(state: JobScraperState, status: str | None = None) -> None:
    metadata = dict(state.get("metadata", {}) or {})
    task_id = metadata.get("task_id")
    artifact_path = metadata.get("artifact_path")
    if not task_id:
        return

    task_record = update_task_worker_state(task_id, state)
    if task_record is None:
        return
    if status:
        task_record = update_task_record(task_id, status=status) or task_record

    if artifact_path:
        upsert_run_to_artifact(
            artifact_path=Path(str(artifact_path)),
            request_payload=task_record.get("request", {}) or {},
            run_id=task_id,
            status=status or task_record.get("status", "running"),
            run_result=task_record.get("run_result"),
            main_result=task_record.get("main_result"),
            progress=task_record.get("progress"),
            error=task_record.get("error"),
        )


def _wrap_node(name: str, node_fn: Callable[[JobScraperState], Awaitable[JobScraperState]]) -> Callable[[JobScraperState], Awaitable[JobScraperState]]:
    async def _wrapped(state: JobScraperState) -> JobScraperState:
        try:
            metadata = dict(state.get("metadata", {}) or {})
            task_id = metadata.get("task_id")
            if should_stop_task(task_id):
                stopped_state: JobScraperState = {**state}
                stopped_metadata = dict(metadata)
                stopped_metadata["task_status"] = "stopped"
                stopped_metadata["stop_requested"] = True
                stopped_state["metadata"] = stopped_metadata
                persist_worker_progress(stopped_state)
                _persist_api_task_progress(stopped_state, status="stopped")
                raise StopRunRequested(stopped_state)

            result = await node_fn(state)
            persist_worker_progress(result)
            _persist_api_task_progress(result)
            return result
        except StopRunRequested:
            raise
        except Exception as exc:
            updated_state: JobScraperState = {**state}
            domain_key, record = current_domain_record(updated_state)
            if domain_key and record is not None:
                record_errors = list(record.get("errors", []))
                record_errors.append(f"{name} failed: {exc}")
                record["errors"] = record_errors
                record_metadata = dict(record.get("metadata", {}) or {})
                record_metadata[f"{name}_status"] = "failed"
                record_metadata[f"{name}_error"] = str(exc)
                record["metadata"] = record_metadata
                failed_state = set_domain_record(updated_state, domain_key, record)
                persist_worker_progress(failed_state)
                _persist_api_task_progress(failed_state)
                return failed_state
            errors = list(state.get("errors", []))
            errors.append(f"{name} failed: {exc}")
            updated_state["errors"] = errors
            updated_state["metadata"] = {
                **state.get("metadata", {}),
                f"{name}_status": "failed",
                f"{name}_error": str(exc),
            }
            persist_worker_progress(updated_state)
            _persist_api_task_progress(updated_state)
            return updated_state

    return _wrapped


async def _fallback_runner(state: JobScraperState) -> JobScraperState:
    current_state = state
    for _ in range(3):
        current_state = await _wrap_node("bootstrap_browser", bootstrap_browser_node)(current_state)
        if current_state.get("session_established", False):
            break
    if not current_state.get("session_established", False):
        return current_state

    while True:
        current_state = await _wrap_node("select_next_url", select_next_url_node)(current_state)
        if _route_after_select_next_url(current_state) == END:
            return current_state

        current_state = await _wrap_node("url_extraction", career_url_extraction_node)(current_state)
        if _route_after_url_extraction(current_state) == "select_next_url":
            continue

        while True:
            current_state = await _wrap_node("navigation", navigation_node)(current_state)
            navigation_route = _route_after_navigation(current_state)
            if navigation_route == "navigation":
                continue
            if navigation_route == "select_next_url":
                break

            while True:
                current_state = await _wrap_node("extract_page_content", extract_page_content_node)(current_state)
                extract_route = _route_after_extract_page_content(current_state)
                if extract_route == "navigation":
                    domain_key, record = current_domain_record(current_state)
                    if domain_key and record is not None:
                        record = dict(record)
                        record_metadata = dict(record.get("metadata", {}) or {})
                        record_metadata["navigation_attempt_count"] = 0
                        record["metadata"] = record_metadata
                        current_state = set_domain_record(current_state, domain_key, record)
                    break
                if extract_route == "select_next_url":
                    domain_key, record = current_domain_record(current_state)
                    if domain_key and record is not None:
                        record = dict(record)
                        record_metadata = dict(record.get("metadata", {}) or {})
                        record_metadata["navigation_attempt_count"] = 0
                        record["metadata"] = record_metadata
                        current_state = set_domain_record(current_state, domain_key, record)
                    break

                current_state = await _wrap_node("career_page_category", career_page_category_node)(current_state)
                route = _route_after_career_page_category(current_state)
                if route == "navigation":
                    domain_key, record = current_domain_record(current_state)
                    if domain_key and record is not None:
                        record = dict(record)
                        record_metadata = dict(record.get("metadata", {}) or {})
                        record_metadata["navigation_attempt_count"] = 0
                        record["metadata"] = record_metadata
                        current_state = set_domain_record(current_state, domain_key, record)
                    continue
                if route == "button_click":
                    current_state = await _wrap_node("button_click", button_click_node)(current_state)
                    continue
                if route == "ats_check":
                    current_state = await _wrap_node("ats_check", ats_check_node)(current_state)
                    if _route_after_ats_check(current_state) == "select_next_url":
                        break
                if route == "select_next_url":
                    break
                while True:
                    current_state = await _wrap_node("next_job_url_selection", next_job_url_selection_node)(current_state)
                    if _route_after_next_job_url_selection(current_state) == "select_next_url":
                        break

                    current_state = await _wrap_node("job_detail_page_extraction", job_detail_page_extraction_node)(current_state)
                    if _route_after_job_detail_page_extraction(current_state) != "convert_job_page_to_json":
                        continue

                    current_state = await _wrap_node("convert_job_page_to_json", convert_job_page_to_json_node)(current_state)
                    if _route_after_convert_job_page_to_json(current_state) == "select_next_url":
                        break

                break

            if extract_route == "navigation":
                continue
            break


def build_graph() -> Callable[[JobScraperState], Awaitable[JobScraperState]]:
    if StateGraph is None:
        return _fallback_runner

    graph = StateGraph(JobScraperState)
    graph.add_node("bootstrap_browser", _wrap_node("bootstrap_browser", bootstrap_browser_node))
    graph.add_node("select_next_url", _wrap_node("select_next_url", select_next_url_node))
    graph.add_node("url_extraction", _wrap_node("url_extraction", career_url_extraction_node))
    graph.add_node("navigation", _wrap_node("navigation", navigation_node))
    graph.add_node("extract_page_content", _wrap_node("extract_page_content", extract_page_content_node))
    graph.add_node("button_click", _wrap_node("button_click", button_click_node))
    graph.add_node("career_page_category", _wrap_node("career_page_category", career_page_category_node))
    
    graph.add_node("ats_check", _wrap_node("ats_check", ats_check_node))
    graph.add_node("next_job_url_selection", _wrap_node("next_job_url_selection", next_job_url_selection_node))
    graph.add_node("job_detail_page_extraction", _wrap_node("job_detail_page_extraction", job_detail_page_extraction_node))
    graph.add_node("convert_job_page_to_json", _wrap_node("convert_job_page_to_json", convert_job_page_to_json_node))

    graph.add_edge(START, "bootstrap_browser")
    graph.add_conditional_edges(
        "bootstrap_browser",
        _route_after_bootstrap,
        {
            "bootstrap_browser": "bootstrap_browser",
            "select_next_url": "select_next_url",
            END: END,
        },
    )
    graph.add_conditional_edges(
        "select_next_url",
        _route_after_select_next_url,
        {
            "url_extraction": "url_extraction",
            END: END,
        },
    )
    graph.add_conditional_edges(
        "url_extraction",
        _route_after_url_extraction,
        {
            "navigation": "navigation",
            "select_next_url": "select_next_url",
        },
    )
    graph.add_conditional_edges(
        "navigation",
        _route_after_navigation,
        {
            "navigation": "navigation",
            "extract_page_content": "extract_page_content",
            "select_next_url": "select_next_url",
        },
    )
    graph.add_conditional_edges(
        "extract_page_content",
        _route_after_extract_page_content,
        {
            "navigation": "navigation",
            "career_page_category": "career_page_category",
            "select_next_url": "select_next_url",
        },
    )
    graph.add_conditional_edges(
        "career_page_category",
        _route_after_career_page_category,
        {
            "navigation": "navigation",
            "button_click": "button_click",
            "ats_check": "ats_check",
            "next_job_url_selection": "next_job_url_selection",
            "select_next_url": "select_next_url",
        },
    )
    graph.add_edge("button_click", "extract_page_content")
    
    graph.add_conditional_edges(
        "ats_check",
        _route_after_ats_check,
        {
            "next_job_url_selection": "next_job_url_selection",
            "select_next_url": "select_next_url",
        },
    )
    graph.add_conditional_edges(
        "next_job_url_selection",
        _route_after_next_job_url_selection,
        {
            "job_detail_page_extraction": "job_detail_page_extraction",
            "select_next_url": "select_next_url",
        },
    )
    graph.add_conditional_edges(
        "job_detail_page_extraction",
        _route_after_job_detail_page_extraction,
        {
            "convert_job_page_to_json": "convert_job_page_to_json",
            "next_job_url_selection": "next_job_url_selection",
        },
    )
    graph.add_conditional_edges(
        "convert_job_page_to_json",
        _route_after_convert_job_page_to_json,
        {
            "next_job_url_selection": "next_job_url_selection",
            "select_next_url": "select_next_url",
        },
    )
    return graph.compile()
