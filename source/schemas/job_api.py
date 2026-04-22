from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


ProcessingMode = Literal["ats_check", "convert_jobs_to_dict", "both"]


class DebugOutputOptions(BaseModel):
    save_markdown: bool = False
    save_selector_map: bool = False
    save_all_urls: bool = False
    save_raw_extracted_jobs: bool = False
    save_main_result_in_debug: bool = False


class URLListRunRequest(BaseModel):
    urls: list[str] = Field(..., min_length=1)
    processing_mode: ProcessingMode = "both"
    agent_count: int = Field(default=1, ge=1)
    artifact_name: str | None = None
    debug_options: DebugOutputOptions = Field(default_factory=DebugOutputOptions)

    @field_validator("urls")
    @classmethod
    def _normalize_urls(cls, value: list[str]) -> list[str]:
        normalized = [str(item).strip() for item in value if str(item).strip()]
        if not normalized:
            raise ValueError("urls must contain at least one non-empty value")
        return normalized


class JobRunResponse(BaseModel):
    artifact_name: str
    artifact_path: str
    run_count: int
    latest_run_id: str
    main_result: dict


class JobRunTaskResponse(BaseModel):
    task_id: str
    status: str
    artifact_name: str
    artifact_path: str


class JobRunTaskStatusResponse(BaseModel):
    task_id: str
    status: str
    artifact_name: str
    artifact_path: str
    run_id: str | None = None
    error: str | None = None
    main_result: dict | None = None
    progress: dict | None = None
    stop_requested: bool | None = None
    domains: dict | None = None


class JobRunProgressResponse(BaseModel):
    task_id: str
    status: str
    artifact_name: str
    artifact_path: str
    progress: dict | None = None
    main_result: dict | None = None
    error: str | None = None
    domains: dict | None = None


class JobRunTaskListResponse(BaseModel):
    tasks: list[JobRunTaskStatusResponse]
    total: int
