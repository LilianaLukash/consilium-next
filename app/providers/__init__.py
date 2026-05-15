"""Model provider abstraction — OpenRouter today, LiteLLM/MCP later."""

from app.providers.base import ModelProvider
from app.providers.openrouter_provider import OpenRouterProvider

__all__ = ["ModelProvider", "OpenRouterProvider"]
