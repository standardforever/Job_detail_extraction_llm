from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import TypedDict

from .grid_session import BrowserSession


STATE_FILE_PATH = Path(__file__).resolve().parents[2] / "state.json"
_STATE_LOCK = Lock()


class PersistedAgentState(TypedDict):
    session_id: str
    cdp_url: str
    last_url: str | None


class PersistedStateFile(TypedDict):
    agents: dict[str, PersistedAgentState]
    shared_session: PersistedAgentState | None


def _read_state_file_unlocked() -> PersistedStateFile:
    if not STATE_FILE_PATH.exists():
        return {"agents": {}, "shared_session": None}

    try:
        payload = json.loads(STATE_FILE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[session_state] Warning: could not read state file: {exc}")
        return {"agents": {}, "shared_session": None}

    if "agents" not in payload or not isinstance(payload["agents"], dict):
        payload["agents"] = {}

    agents: dict[str, PersistedAgentState] = {}
    for agent_key, agent_state in payload["agents"].items():
        if not isinstance(agent_state, dict):
            continue
        session_id = agent_state.get("session_id")
        cdp_url = agent_state.get("cdp_url")
        if not session_id or not cdp_url:
            continue
        agents[str(agent_key)] = {
            "session_id": str(session_id),
            "cdp_url": str(cdp_url),
            "last_url": str(agent_state["last_url"]) if agent_state.get("last_url") else None,
        }

    shared_session_payload = payload.get("shared_session")
    shared_session: PersistedAgentState | None = None
    if isinstance(shared_session_payload, dict):
        session_id = shared_session_payload.get("session_id")
        cdp_url = shared_session_payload.get("cdp_url")
        if session_id and cdp_url:
            shared_session = {
                "session_id": str(session_id),
                "cdp_url": str(cdp_url),
                "last_url": str(shared_session_payload["last_url"]) if shared_session_payload.get("last_url") else None,
            }

    return {"agents": agents, "shared_session": shared_session}


def load_agent_state(agent_index: int) -> PersistedAgentState | None:
    with _STATE_LOCK:
        payload = _read_state_file_unlocked()
        agent_state = payload["agents"].get(str(agent_index))
        return dict(agent_state) if agent_state else None


def load_shared_session_state() -> PersistedAgentState | None:
    with _STATE_LOCK:
        payload = _read_state_file_unlocked()
        shared_session = payload.get("shared_session")
        return dict(shared_session) if shared_session else None


def save_agent_state(agent_index: int, session: BrowserSession, last_url: str | None) -> None:
    with _STATE_LOCK:
        payload = _read_state_file_unlocked()
        payload["agents"][str(agent_index)] = {
            "session_id": session.session_id,
            "cdp_url": session.cdp_url,
            "last_url": last_url,
        }
        STATE_FILE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def save_shared_session_state(session: BrowserSession, last_url: str | None = None) -> None:
    with _STATE_LOCK:
        payload = _read_state_file_unlocked()
        payload["shared_session"] = {
            "session_id": session.session_id,
            "cdp_url": session.cdp_url,
            "last_url": last_url,
        }
        STATE_FILE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
