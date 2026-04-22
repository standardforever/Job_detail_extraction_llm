from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from core.config import load_environment

load_environment()

@dataclass(slots=True)
class AnalysisResult:
    response: dict[str, Any]
    success: bool
    token_usage: int = 0
    error: str = ""


class OpenAIAnalysisService:
    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        self._model = model or os.getenv("OPENAI_MODEL", "gpt-5-nano")
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self._api_key:
            raise ValueError("OPENAI_API_KEY is not configured")
        self._client = OpenAI(api_key=self._api_key)

    async def analyze_data(
        self,
        prompt: str,
        json_response: bool = True,
    ) -> AnalysisResult:
        return await asyncio.to_thread(self._analyze_sync, prompt, json_response)

    def _analyze_sync(self, prompt: str, json_response: bool) -> AnalysisResult:
        error = ""
        for _ in range(2):
            try:
                response = self._client.responses.create(
                    model=self._model,
                    input=prompt,
                )
                output: Any = response.output_text

                if json_response:
                    output = json.loads(output)

                return AnalysisResult(
                    response=output if isinstance(output, dict) else {},
                    success=True,
                    token_usage=response.usage.total_tokens if response.usage else 0,
                )
            except Exception as exc:
                error = str(exc)
                continue

        return AnalysisResult(
            response={},
            success=False,
            error=error,
        )
