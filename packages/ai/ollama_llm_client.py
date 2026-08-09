"""OllamaLLMClient — local-model implementation of LLMClient (research graph).

Adapter over local_llm.ollama_client.OllamaClient so research graph nodes can
route to a local model (e.g. qwen3:32b) instead of the Claude API. Returns the
model's JSON as a string — ai.service re-parses and validates it, keeping one
validation path for both providers.
"""

import asyncio
import json

from core.errors import LLMError
from core.logging import get_logger

from ai.client import _SYSTEM_PROMPT
from ai.interfaces import LLMClient

logger = get_logger(__name__)


class OllamaLLMClient(LLMClient):
    """
    Local Ollama client for research-graph LLM analysis.
    - Sends the same forbidden-keys system prompt as the Anthropic client.
    - think=False: qwen3 thinking mode conflicts with format=json.
    - Raises LLMError on all failures — never raw Ollama exceptions.
    """

    def __init__(
        self,
        base_url: str,
        model: str = "qwen3:32b",
        timeout_seconds: int = 120,
        max_retries: int = 1,
    ) -> None:
        self._base_url = base_url
        self._model = model
        self._timeout = timeout_seconds
        self._max_retries = max_retries

    async def complete(self, prompt: str, max_tokens: int = 2000) -> str:
        from local_llm.ollama_client import OllamaClient
        from local_llm.schemas import (
            OllamaConnectionError,
            OllamaMessage,
            OllamaParseError,
        )

        client = OllamaClient(
            base_url=self._base_url, model=self._model, timeout=self._timeout
        )
        messages = [
            OllamaMessage(role="system", content=_SYSTEM_PROMPT),
            OllamaMessage(role="user", content=prompt),
        ]

        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                result = await client.chat_json(messages, think=False)
                logger.info("ollama_complete_ok", model=self._model, attempt=attempt)
                return json.dumps(result)
            except OllamaConnectionError as exc:
                last_exc = exc
                logger.warning(
                    "ollama_connection_error", model=self._model, attempt=attempt, error=str(exc)
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(1.0)
            except OllamaParseError as exc:
                last_exc = exc
                logger.warning(
                    "ollama_parse_error", model=self._model, attempt=attempt, error=str(exc)
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(0.5)
            except Exception as exc:
                raise LLMError(
                    f"Unexpected Ollama error: {exc}", {"model": self._model}
                ) from exc

        raise LLMError(
            f"Ollama failed after {self._max_retries + 1} attempts: {last_exc}",
            {"model": self._model},
        )
