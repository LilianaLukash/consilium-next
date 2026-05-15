from typing import Any

from app.model_registry import fetch_models
from app.openrouter import ChatResult, OpenRouterClient
from app.providers.base import ModelProvider


class OpenRouterProvider(ModelProvider):
    def __init__(self, client: OpenRouterClient | None = None) -> None:
        self.client = client or OpenRouterClient()

    async def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
        temperature: float = 0.7,
        timeout: float | None = None,
    ) -> ChatResult:
        return await self.client.chat(
            model, messages, max_tokens=max_tokens, temperature=temperature, timeout=timeout
        )

    async def list_models(self) -> list[dict[str, Any]]:
        models = await fetch_models()
        return [m.to_dict() for m in models]
