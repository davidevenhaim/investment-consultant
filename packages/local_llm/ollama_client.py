"""Async Ollama HTTP client."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from local_llm.schemas import (
    OllamaConnectionError,
    OllamaMessage,
    OllamaParseError,
)

logger = logging.getLogger(__name__)


class OllamaClient:
    """Thin async wrapper around the Ollama /api/chat endpoint."""

    def __init__(self, base_url: str, model: str, timeout: int) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    async def chat_json(
        self,
        messages: list[OllamaMessage],
        think: bool | None = None,
    ) -> dict[str, Any]:
        """POST to /api/chat with format=json. Returns parsed dict.

        ``think=False`` disables thinking mode on models like qwen3 — thinking
        output conflicts with format=json.

        Raises:
            OllamaConnectionError: Ollama unreachable or returned HTTP error.
            OllamaParseError: Response content is not valid JSON.
        """
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [m.model_dump() for m in messages],
            "stream": False,
            "format": "json",
        }
        if think is not None:
            payload["think"] = think
        try:
            async with httpx.AsyncClient(timeout=float(self._timeout)) as http:
                resp = await http.post(f"{self._base_url}/api/chat", json=payload)
                resp.raise_for_status()
        except httpx.ConnectError as exc:
            raise OllamaConnectionError(f"Cannot connect to Ollama at {self._base_url}") from exc
        except httpx.TimeoutException as exc:
            raise OllamaConnectionError(f"Ollama request timed out after {self._timeout}s") from exc
        except httpx.HTTPStatusError as exc:
            raise OllamaConnectionError(f"Ollama returned HTTP {exc.response.status_code}") from exc

        raw: dict[str, Any] = resp.json()
        message = raw.get("message", {})
        if not isinstance(message, dict):
            raise OllamaParseError("Unexpected Ollama response structure (no message dict)")
        content = message.get("content", "")
        if not isinstance(content, str):
            raise OllamaParseError("Unexpected Ollama response content type")
        try:
            result: dict[str, Any] = json.loads(content)
            return result
        except (json.JSONDecodeError, TypeError) as exc:
            raise OllamaParseError("Ollama response content is not valid JSON") from exc
