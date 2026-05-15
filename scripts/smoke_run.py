"""One-shot smoke test: 1 debate round, short prompt."""
import asyncio
import sys

from app.models import Phase
from app.orchestrator import ConsiliumOrchestrator


async def main() -> int:
    prompt = (
        "Микро-SaaS: напоминания о поливе комнатных растений через Telegram-бот. "
        "Нужен MVP за 2 недели. Дайте архитектуру и риски."
    )
    events: list[str] = []

    def on_event(ev) -> None:
        d = ev.data
        if ev.type == "phase":
            events.append(f"phase:{d.get('phase')} r={d.get('round', '')}")
        elif ev.type == "agent_message":
            n = len(d.get("content", ""))
            events.append(f"msg:{d.get('agent_id')} {d.get('phase')} chars={n}")
        elif ev.type == "error":
            events.append(f"ERROR:{d.get('message')}")

    orch = ConsiliumOrchestrator()
    state = await orch.run(prompt, max_debate_rounds=1, on_event=on_event)

    print("session:", state.session_id)
    print("phase:", state.phase.value)
    if state.error:
        print("error:", state.error)
        return 1
    print("messages:", len(state.messages))
    for e in events:
        print(" ", e)
    verdict = state.final_verdict or ""
    print("verdict_chars:", len(verdict))
    print("verdict_preview:", verdict[:400].replace("\n", " ") + ("…" if len(verdict) > 400 else ""))
    return 0 if state.phase == Phase.COMPLETE else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
