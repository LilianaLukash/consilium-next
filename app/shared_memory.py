"""Shared council memory — single source for all agent prompts."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models import AgentMessage, Phase


@dataclass
class SharedMemory:
    goal: str
    task: str
    attachments: str = ""
    messages: list[AgentMessage] = field(default_factory=list)
    user_comments: list[str] = field(default_factory=list)
    compressed_rounds: str = ""
    intermediate_notes: list[str] = field(default_factory=list)

    def add_message(self, msg: AgentMessage) -> None:
        self.messages.append(msg)

    def add_comment(self, text: str) -> None:
        self.user_comments.append(text)

    def goal_block(self) -> str:
        return f"## Главная цель (не забывать)\n{self.goal}\n"

    def task_block(self) -> str:
        return f"## Задача пользователя\n{self.task}\n"

    def attachments_block(self) -> str:
        return self.attachments if self.attachments else ""

    def comments_block(self) -> str:
        if not self.user_comments:
            return ""
        parts = ["## Комментарии пользователя"]
        for i, c in enumerate(self.user_comments, 1):
            parts.append(f"### Комментарий {i}\n{c}")
        return "\n".join(parts) + "\n"

    def compressed_block(self) -> str:
        if not self.compressed_rounds:
            return ""
        return f"## Сжатие дебатов\n{self.compressed_rounds}\n"

    def build_context(self, *, extra: str = "") -> str:
        parts = [self.goal_block(), self.task_block()]
        if self.attachments_block():
            parts.append(self.attachments_block())
        if self.comments_block():
            parts.append(self.comments_block())
        if self.compressed_block():
            parts.append(self.compressed_block())
        if extra:
            parts.append(extra)
        return "\n".join(parts)

    def recent_summary(self, max_chars: int | None = 14000) -> str:
        """Краткая сводка для агентов (может обрезаться)."""
        lines: list[str] = []
        for m in self.messages[-20:]:
            lines.append(f"[{m.agent_id.value}/{m.phase.value}/r{m.round}] {m.content[:1200]}")
        text = "\n\n".join(lines)
        if max_chars is not None and len(text) > max_chars:
            return text[:max_chars] + "\n…[обрезано]"
        return text

    def full_council_transcript(self) -> str:
        """Полная стенограмма для синтеза — без обрезки по символам."""
        if not self.messages:
            return "(нет сообщений совета)"
        blocks: list[str] = []
        for m in self.messages:
            blocks.append(
                f"### {m.agent_id.value} · {m.phase.value} · раунд {m.round}\n{m.content}\n"
            )
        return "\n".join(blocks)
