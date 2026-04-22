from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def load_environment() -> None:
    """Load env files from both repo root and source/ for local API runs."""
    source_env = Path(__file__).resolve().parents[1] / ".env"
    repo_env = Path(__file__).resolve().parents[2] / ".env"
    for env_path in (repo_env, source_env):
        if env_path.exists():
            load_dotenv(env_path, override=False)


load_environment()


@dataclass(slots=True)
class Settings:
    selenium_remote_url: str = os.getenv("SELENIUM_REMOTE_URL", "http://127.0.0.1:4445/wd/hub")
    default_agent_count: int = int(os.getenv("DEFAULT_AGENT_COUNT", "1"))
    post_navigation_delay_ms: int = int(os.getenv("POST_NAVIGATION_DELAY_MS", "5000"))


def get_settings() -> Settings:
    return Settings()
