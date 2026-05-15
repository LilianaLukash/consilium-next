"""E2E: Lisbon $100k prompt — verify wave order and completion."""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.model_registry import CouncilModelConfig, apply_preset, fetch_models, snapshots_for_models
from app.models import Phase
from app.orchestrator import ConsiliumOrchestrator

PROMPT = (
    "Нужно заработать 100000 долл через интернет за 6 мес , вложив 2000. "
    "Я в Лиссабоне, португалия. Лично общаться с клиентами не хочу. "
    "есть кампания в штатах. Автоматизация всего чего можно"
)

MAX_SEC_PER_AGENT = 180


async def main() -> int:
    all_models = await fetch_models()
    role_models = apply_preset(all_models, "balanced", 10.0)
    council = CouncilModelConfig(
        price_threshold=10.0,
        preset="balanced",
        models=role_models,
        snapshots=snapshots_for_models(all_models, role_models),
    )
    print("models:", role_models)

    order_log: list[str] = []
    agent_times: dict[str, float] = {}
    t_agent: dict[str, float] = {}

    def on_event(ev):
        d = ev.data
        if ev.type == "agent_start" and d.get("agent_id"):
            t_agent[d["agent_id"]] = time.perf_counter()
            order_log.append(f"start:{d['agent_id']}")
        if ev.type == "agent_message" and d.get("agent_id"):
            started = t_agent.pop(d["agent_id"], time.perf_counter())
            elapsed = time.perf_counter() - started
            agent_times[d["agent_id"]] = elapsed
            order_log.append(f"done:{d['agent_id']}:{elapsed:.0f}s")
            if elapsed > MAX_SEC_PER_AGENT:
                print(f"WARN slow {d['agent_id']}: {elapsed:.0f}s")
        if ev.type == "wave":
            order_log.append(f"wave:{d.get('wave')}")

    t0 = time.perf_counter()
    state = await ConsiliumOrchestrator().run(
        PROMPT,
        max_debate_rounds=1,
        council_config=council,
        on_event=on_event,
    )
    total = time.perf_counter() - t0

    print("phase", state.phase.value, "total", f"{total:.0f}s")
    print("order:", " -> ".join(order_log))
    print("verdict_len", len(state.final_verdict or ""))

    if state.error:
        print("FAIL", state.error)
        return 1

    def first_done(agent: str) -> int:
        for i, x in enumerate(order_log):
            if x.startswith(f"done:{agent}:"):
                return i
        return 999

    d_done, v_done, a_done, c_done = first_done("diator"), first_done("visionary"), first_done("architect"), first_done("critic")
    if not (d_done < a_done and v_done < a_done):
        print("FAIL order: architect/critic before diator/visionary")
        return 1
    slow = [f"{a}:{t:.0f}s" for a, t in agent_times.items() if t > MAX_SEC_PER_AGENT]
    if slow:
        print("WARN slow agents:", slow)

    if state.phase != Phase.COMPLETE or not state.final_verdict:
        print("FAIL no verdict")
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
