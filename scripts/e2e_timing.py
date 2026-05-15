"""End-to-end timing test — must reach verdict."""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import Phase
from app.orchestrator import ConsiliumOrchestrator


PROMPT = (
    "MVP: парсер ресторанов Лиссабона без сайта, продажа лендинга за $200. "
    "Нужны архитектура, риски, план на 2 недели."
)


async def main() -> int:
    t0 = time.perf_counter()
    events: list[str] = []

    def on_event(ev) -> None:
        d = ev.data
        if ev.type == "agent_message":
            events.append(f"{d.get('agent_id')}:{d.get('phase')}")
        elif ev.type == "status":
            events.append(f"status:{d.get('message')}")
        elif ev.type == "verdict":
            events.append("verdict")

    state = await ConsiliumOrchestrator().run(
        PROMPT,
        max_debate_rounds=2,
        on_event=on_event,
    )
    elapsed = time.perf_counter() - t0

    print(f"phase={state.phase.value} elapsed={elapsed:.1f}s")
    print(f"messages={len(state.messages)} verdict_len={len(state.final_verdict or '')}")
    for e in events:
        print(" ", e)
    if state.error:
        print("ERROR:", state.error)
        return 1
    if state.phase != Phase.COMPLETE or not state.final_verdict:
        return 1
    print("OK — verdict ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
