"""AnthropicLLMClient — production implementation of LLMClient."""
import asyncio
from typing import Any

from core.errors import LLMError
from core.logging import get_logger

from ai.interfaces import LLMClient

logger = get_logger(__name__)

_SYSTEM_PROMPT = (
    "You are a research analyst assistant. "
    "Respond ONLY with valid JSON. No preamble, no markdown, no commentary. "
    "Do NOT include any field named action, recommendation, score, buy, sell, hold, "
    "target_price, or position_size."
)


class AnthropicLLMClient(LLMClient):
    """
    Async Anthropic SDK client.
    - Retries on transient network/rate-limit errors up to max_retries.
    - Times out after timeout_seconds.
    - Raises LLMError on all failures — never raw Anthropic exceptions.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        timeout_seconds: int = 30,
        max_retries: int = 2,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds
        self._max_retries = max_retries

    async def complete(self, prompt: str, max_tokens: int = 2000) -> str:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=self._api_key)
        last_exc: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                response: Any = await asyncio.wait_for(
                    client.messages.create(
                        model=self._model,
                        max_tokens=max_tokens,
                        system=_SYSTEM_PROMPT,
                        messages=[{"role": "user", "content": prompt}],
                    ),
                    timeout=self._timeout,
                )
                text: str = response.content[0].text
                logger.info(
                    "llm_complete_ok",
                    model=self._model,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    attempt=attempt,
                )
                return text
            except TimeoutError as exc:
                last_exc = exc
                logger.warning("llm_timeout", model=self._model, attempt=attempt)
            except anthropic.RateLimitError as exc:
                last_exc = exc
                logger.warning("llm_rate_limit", model=self._model, attempt=attempt)
                if attempt < self._max_retries:
                    await asyncio.sleep(2.0 * (attempt + 1))
            except anthropic.APIConnectionError as exc:
                last_exc = exc
                logger.warning("llm_connection_error", model=self._model, attempt=attempt)
                if attempt < self._max_retries:
                    await asyncio.sleep(1.0)
            except anthropic.APIStatusError as exc:
                # 5xx are transient; 4xx (except rate limit) are fatal
                if exc.status_code >= 500:
                    last_exc = exc
                    logger.warning(
                        "llm_server_error",
                        status=exc.status_code,
                        model=self._model,
                        attempt=attempt,
                    )
                    if attempt < self._max_retries:
                        await asyncio.sleep(1.0)
                else:
                    raise LLMError(
                        f"Anthropic API error {exc.status_code}: {exc.message}",
                        {"model": self._model, "status": exc.status_code},
                    ) from exc
            except Exception as exc:
                raise LLMError(
                    f"Unexpected LLM error: {exc}",
                    {"model": self._model},
                ) from exc

        raise LLMError(
            f"LLM failed after {self._max_retries + 1} attempts: {last_exc}",
            {"model": self._model},
        )
