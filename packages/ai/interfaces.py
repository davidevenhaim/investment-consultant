"""LLM client abstract interface."""
from abc import ABC, abstractmethod


class LLMClient(ABC):
    @abstractmethod
    async def complete(self, prompt: str, max_tokens: int = 2000) -> str:
        """Send prompt, return raw text response. Raises LLMError on failure."""
        ...
