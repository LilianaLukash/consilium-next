"""Consensus engine — structured Top-3 verdict (no character truncation)."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from app.config import settings
from app.openrouter import ChatUsage, OpenRouterClient
from app.protocol import SYNTHESIS_SYSTEM
from app.shared_memory import SharedMemory

CONSENSUS_USER = """
На основе всей дискуссии совета сформируй финальный вердикт СТРОГО по структуре из system prompt.

Обязательно:
1. Все ТРИ варианта А, B и В — каждый с полной таблицей (не пропускай B и В).
2. В каждой таблице: Описание | Плюсы | Минусы | Потенциал | Мнение | Аргументы | Риски | Вывод.
3. Варианты = лучшие идеи из дискуссии идеаторов, ранжированные по реальному спросу.
4. Финальная рекомендация и 3 шага на 2 недели.
5. Только русский язык.

Материалы совета:
"""

CONTINUE_USER = """
Предыдущий ответ оборвался до конца. Продолжи СТРОГО с места обрыва.
Не повторяй уже выданные разделы. Допиши недостающие:
- **Вариант B** (полная таблица), если его нет;
- **Вариант В** (полная таблица), если его нет;
- **### 3. Рекомендация совета** и **### 4. Нерешённые споры** (если не были).
"""

UsageCallback = Callable[[str, ChatUsage, str], Awaitable[None]]


def verdict_is_complete(text: str) -> bool:
    low = text.lower()
    has_b = bool(re.search(r"вариант\s*b\b", low)) or "#### 2." in text
    has_v = bool(re.search(r"вариант\s*в\b", low)) or "#### 3." in text
    has_rec = "рекомендация совета" in low or "### 3." in text
    return has_b and has_v and has_rec


class ConsensusEngine:
    def __init__(self, client: OpenRouterClient | None = None) -> None:
        self.client = client or OpenRouterClient()

    async def generate(
        self,
        memory: SharedMemory,
        *,
        synthesis_model: str | None = None,
        on_usage: UsageCallback | None = None,
    ) -> str:
        transcript = memory.full_council_transcript()
        body = memory.build_context(extra=f"## Полная стенограмма совета\n{transcript}")
        model = synthesis_model or settings.model_synthesis
        timeout = settings.synthesis_timeout_seconds
        max_tokens = settings.max_tokens_synthesis

        messages: list[dict[str, str]] = [
            {"role": "system", "content": SYNTHESIS_SYSTEM},
            {"role": "user", "content": CONSENSUS_USER + body},
        ]

        result = await self.client.chat(
            model,
            messages,
            max_tokens=max_tokens,
            temperature=0.4,
            timeout=timeout,
        )
        if on_usage:
            await on_usage(result.model or model, result.usage, "synthesis")
        verdict = result.content

        for _ in range(settings.synthesis_continuation_attempts):
            if verdict_is_complete(verdict):
                break
            continuation = [
                *messages,
                {"role": "assistant", "content": verdict},
                {"role": "user", "content": CONTINUE_USER},
            ]
            extra_result = await self.client.chat(
                model,
                continuation,
                max_tokens=max_tokens,
                temperature=0.35,
                timeout=timeout,
            )
            if on_usage:
                await on_usage(extra_result.model or model, extra_result.usage, "synthesis_continue")
            extra = extra_result.content
            if not extra.strip():
                break
            verdict = f"{verdict.rstrip()}\n\n{extra.lstrip()}"

        return verdict
