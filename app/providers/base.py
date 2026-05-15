from abc import ABC, abstractmethod
from typing import Any

from app.openrouter import ChatResult


class ModelProvider(ABC):
    """Routing layer — do not hardcode a single vendor."""

    @abstractmethod
    async def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
        temperature: float = 0.7,
        timeout: float | None = None,
    ) -> ChatResult:
        ...

    @abstractmethod
    async def list_models(self) -> list[dict[str, Any]]:
        ...
