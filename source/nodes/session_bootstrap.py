from __future__ import annotations

from state import JobScraperState

from services.grid_session import attach_playwright_to_cdp
from services.tab_manager import ensure_agent_tab


async def bootstrap_browser_node(state: JobScraperState) -> JobScraperState:
    agent_index = state.get("agent_index", 0)
    cdp_url = state.get("cdp_url")
    session_id = state.get("session_id")
    metadata = dict(state.get("metadata", {}))
    bootstrap_attempt_count = int(metadata.get("bootstrap_attempt_count", 0) or 0) + 1

    if not cdp_url:
        errors = list(state.get("errors", []))
        errors.append("Missing shared CDP URL for Playwright attachment")
        return {
            **state,
            "agent_index": agent_index,
            "session_established": False,
            "errors": errors,
            "metadata": {
                **metadata,
                "bootstrap_attempt_count": bootstrap_attempt_count,
                "bootstrap_status": "missing_cdp_url",
            },
        }

    session = await attach_playwright_to_cdp(cdp_url)
    if session is None:
        errors = list(state.get("errors", []))
        errors.append("Unable to attach Playwright to the Selenium CDP session")
        return {
            **state,
            "agent_index": agent_index,
            "session_established": False,
            "errors": errors,
            "metadata": {
                **metadata,
                "bootstrap_attempt_count": bootstrap_attempt_count,
                "bootstrap_status": "attach_failed",
            },
        }

    agent_tab = await ensure_agent_tab(session, agent_index=agent_index)
    return {
        **state,
        "agent_index": agent_index,
        "browser_session": session,
        "session_id": session_id or session.session_id,
        "cdp_url": cdp_url,
        "session_established": True,
        "agent_tab": agent_tab,
        "metadata": {
            **metadata,
            "bootstrap_attempt_count": bootstrap_attempt_count,
            "bootstrap_status": "connected",
            "reused_existing_session": bool(metadata.get("reused_existing_session", False)),
        },
    }
