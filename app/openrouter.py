from dataclasses import dataclass

import httpx

from app.config import settings

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


@dataclass
class ChatUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ChatResult:
    content: str
    model: str
    usage: ChatUsage


class OpenRouterClient:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or settings.openrouter_api_key
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(180.0, connect=15.0),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
        temperature: float = 0.7,
        timeout: float | None = None,
    ) -> ChatResult:
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY is not set")

        req_timeout = timeout or settings.agent_timeout_seconds
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": settings.openrouter_app_url,
            "X-OpenRouter-Title": settings.openrouter_app_name,
        }
        body: dict = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        client = self._get_client()
        resp = await client.post(OPENROUTER_URL, headers=headers, json=body, timeout=req_timeout)
        if resp.is_error:
            detail = resp.text[:500]
            try:
                err = resp.json().get("error", {})
                if isinstance(err, dict) and err.get("message"):
                    detail = str(err["message"])
            except Exception:
                pass
            raise httpx.HTTPStatusError(
                f"OpenRouter {resp.status_code}: {detail}",
                request=resp.request,
                response=resp,
            )
        data = resp.json()

        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content", "")
        if isinstance(content, list):
            parts = [p.get("text", "") for p in content if isinstance(p, dict)]
            content = "\n".join(parts).strip()
        else:
            content = (content or "").strip()

        raw_usage = data.get("usage") or {}
        usage = ChatUsage(
            prompt_tokens=int(raw_usage.get("prompt_tokens") or 0),
            completion_tokens=int(raw_usage.get("completion_tokens") or 0),
            total_tokens=int(raw_usage.get("total_tokens") or 0),
        )
        used_model = data.get("model") or model
        return ChatResult(content=content, model=used_model, usage=usage)
