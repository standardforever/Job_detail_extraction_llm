from __future__ import annotations

from typing import Awaitable, Callable

from langgraph.graph import END, START, StateGraph

from state import JobScraperState

from nodes.button_click import button_click_node
from nodes.convert_job_page_to_json import convert_job_page_to_json_node
from nodes.extract_page_content import extract_page_content_node
from nodes.job_detail_page_extraction import job_detail_page_extraction_node
from nodes.job_page_features import job_page_features_node
from nodes.job_url_extraction import job_url_extraction_node
from nodes.navigation import navigation_node
from nodes.next_job_url_selection import next_job_url_selection_node
from nodes.page_category import page_category_node
from nodes.page_filter import page_filter_node
from nodes.select_next_url import select_next_url_node
from nodes.session_bootstrap import bootstrap_browser_node
from nodes.sort_page import sort_page_node
from utils.routes import (
    _route_after_bootstrap, _route_after_select_next_url, _route_after_navigation,
    _route_after_convert_job_page_to_json, _route_after_extract_page_content, _route_after_job_detail_page_extraction,
    _route_after_next_job_url_selection, _route_after_page_category
)


def _wrap_node(name: str, node_fn: Callable[[JobScraperState], Awaitable[JobScraperState]]) -> Callable[[JobScraperState], Awaitable[JobScraperState]]:
    async def _wrapped(state: JobScraperState) -> JobScraperState:
        try:
            return await node_fn(state)
        except Exception as exc:
            errors = list(state.get("errors", []))
            errors.append(f"{name} failed: {exc}")
            return {
                **state,
                "errors": errors,
                "metadata": {
                    **state.get("metadata", {}),
                    f"{name}_status": "failed",
                    f"{name}_error": str(exc),
                },
            }

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
                    current_state = {
                        **current_state,
                        "metadata": {
                            **current_state.get("metadata", {}),
                            "navigation_attempt_count": 0,
                        },
                    }
                    break
                if extract_route == "select_next_url":
                    current_state = {
                        **current_state,
                        "metadata": {
                            **current_state.get("metadata", {}),
                            "navigation_attempt_count": 0,
                        },
                    }
                    break

                for _ in range(4):
                    current_state = await _wrap_node("page_category", page_category_node)(current_state)
                    route = _route_after_page_category(current_state)
                    if route == "button_click":
                        current_state = await _wrap_node("button_click", button_click_node)(current_state)
                        current_state = await _wrap_node("extract_page_content", extract_page_content_node)(current_state)
                        continue
                    if route == "select_next_url":
                        break
                    if route == "job_page_features":
                        break
                    return current_state

                if route == "select_next_url":
                    break

                current_state = await _wrap_node("job_page_features", job_page_features_node)(current_state)
                current_state = await _wrap_node("page_filter", page_filter_node)(current_state)
                current_state = await _wrap_node("sort_page", sort_page_node)(current_state)
                current_state = await _wrap_node("job_url_extraction", job_url_extraction_node)(current_state)
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
    graph.add_node("navigation", _wrap_node("navigation", navigation_node))
    graph.add_node("extract_page_content", _wrap_node("extract_page_content", extract_page_content_node))
    graph.add_node("page_category", _wrap_node("page_category", page_category_node))
    graph.add_node("button_click", _wrap_node("button_click", button_click_node))
    graph.add_node("job_page_features", _wrap_node("job_page_features", job_page_features_node))
    graph.add_node("page_filter", _wrap_node("page_filter", page_filter_node))
    graph.add_node("sort_page", _wrap_node("sort_page", sort_page_node))
    graph.add_node("job_url_extraction", _wrap_node("job_url_extraction", job_url_extraction_node))
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
            "navigation": "navigation",
            END: END,
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
            "page_category": "page_category",
            "select_next_url": "select_next_url",
        },
    )
    
    graph.add_conditional_edges(
        "page_category",
        _route_after_page_category,
        {
            "button_click": "button_click",
            "select_next_url": "select_next_url",
            "job_page_features": "job_page_features",
            END: END,
        },
    )
    graph.add_edge("button_click", "extract_page_content")
    graph.add_edge("job_page_features", "page_filter")
    graph.add_edge("page_filter", "sort_page")
    graph.add_edge("sort_page", "job_url_extraction")
    graph.add_edge("job_url_extraction", "next_job_url_selection")
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
