import asyncio
from collections.abc import Callable

from app.agents import build_system_prompt, get_agent_waves, synthesis_model
from app.auth.context import ActorContext
from app.billing.service import InsufficientBalanceError, record_chat_usage
from app.compression import compress_round, format_peer_digest, format_prior_digest
from app.config import settings
from app.consensus import ConsensusEngine
from app.database import (
    create_session,
    load_council_config,
    save_council_config,
    save_message,
    save_user_comment,
    save_verdict,
    update_session_meta,
)
from app.model_registry import CouncilModelConfig
from app.agents import AgentDef
from app.models import AgentMessage, Phase, SessionState, StreamEvent
from app.openrouter import OpenRouterClient
from app.providers.openrouter_provider import OpenRouterProvider
from app.shared_memory import SharedMemory


EventCallback = Callable[[StreamEvent], None]


class ConsiliumOrchestrator:
    def __init__(self, provider: OpenRouterProvider | None = None) -> None:
        self.provider = provider or OpenRouterProvider()
        self.client = self.provider.client
        self.consensus = ConsensusEngine(self.client)

    async def run(
        self,
        prompt: str,
        *,
        max_debate_rounds: int | None = None,
        on_event: EventCallback | None = None,
        session_id: str | None = None,
        attachments_context: str = "",
        revision_comment: str | None = None,
        prior_messages: list[AgentMessage] | None = None,
        prior_verdict_version: int = 0,
        council_config: CouncilModelConfig | None = None,
        has_images: bool = False,
        actor: ActorContext | None = None,
    ) -> SessionState:
        self._actor = actor
        self._session_id: str | None = None
        max_rounds = max_debate_rounds if max_debate_rounds is not None else settings.max_debate_rounds
        goal = prompt.strip()[:500]
        is_revision = bool(revision_comment and prior_messages)
        council = council_config or CouncilModelConfig()

        if session_id:
            sid = session_id
            self._session_id = sid
            if not council.models:
                council = load_council_config(sid)
        else:
            sid = create_session(
                prompt,
                goal=goal,
                attachments_context=attachments_context,
                council_config=council,
                user_id=actor.user_id if actor else None,
                guest_id=actor.guest_id if actor else None,
            )

        self._session_id = sid
        save_council_config(sid, council)
        version = prior_verdict_version + 1 if is_revision else 1

        memory = SharedMemory(
            goal=goal,
            task=prompt,
            attachments=attachments_context,
            messages=list(prior_messages) if prior_messages else [],
        )
        if revision_comment:
            memory.add_comment(revision_comment)

        state = SessionState(
            session_id=sid,
            user_prompt=prompt,
            goal=goal,
            attachments_context=attachments_context,
            user_comment=revision_comment,
            verdict_version=version,
            messages=memory.messages,
        )

        def emit(type_: str, **data) -> None:
            if on_event:
                on_event(StreamEvent(type=type_, data={**data, "session_id": sid}))

        def persist(msg: AgentMessage) -> None:
            save_message(sid, msg, verdict_version=version)

        wave1, wave2 = get_agent_waves(council)

        try:
            if is_revision:
                emit("phase", phase=Phase.REVISION.value)
                emit("status", message="Уточнение пользователя — новый раунд")
                save_user_comment(sid, revision_comment or "")
                state.phase = Phase.REVISION
            else:
                emit("phase", phase=Phase.INDEPENDENT.value)
                state.phase = Phase.INDEPENDENT
                await self._independent_phase(state, memory, wave1, wave2, emit, persist)

            for r in range(1, max_rounds + 1):
                emit("phase", phase=Phase.DEBATE.value, round=r)
                state.phase = Phase.DEBATE
                state.current_round = r
                note = revision_comment if is_revision and r == 1 else None
                await self._debate_round(state, memory, wave1, wave2, r, emit, persist, note)

                chunk = compress_round(state.messages, r)
                memory.compressed_rounds = (
                    memory.compressed_rounds + f"\n\n--- Раунд {r} ---\n{chunk}"
                ).strip()
                state.compressed_context = memory.compressed_rounds

            emit("phase", phase=Phase.REVIEW.value)
            emit("status", message="Пересмотр позиций…")
            state.phase = Phase.REVIEW
            await self._review_phase(state, memory, wave1, wave2, emit, persist)

            emit("phase", phase=Phase.SYNTHESIS.value)
            emit("status", message="Консенсус: топ-3 решения…")
            state.phase = Phase.SYNTHESIS
            async def on_synthesis_usage(model: str, usage, label: str) -> None:
                if actor:
                    await record_chat_usage(
                        actor, session_id=sid, model=model, usage=usage, label=label
                    )

            verdict = await self.consensus.generate(
                memory,
                synthesis_model=synthesis_model(council),
                on_usage=on_synthesis_usage if actor else None,
            )
            state.final_verdict = verdict
            state.phase = Phase.COMPLETE
            save_verdict(sid, verdict, version)
            emit("verdict", content=verdict, version=version)
            emit("phase", phase=Phase.COMPLETE.value)
            emit("status", message="Готово.")
            update_session_meta(sid, phase=Phase.COMPLETE.value, verdict_version=version)

        except InsufficientBalanceError:
            state.phase = Phase.ERROR
            state.error = "Недостаточно средств на балансе"
            emit("error", message=state.error, code="INSUFFICIENT_BALANCE")
            emit("phase", phase=Phase.ERROR.value)
            update_session_meta(sid, phase=Phase.ERROR.value)
        except Exception as e:
            state.phase = Phase.ERROR
            state.error = str(e)
            emit("error", message=str(e))
            emit("phase", phase=Phase.ERROR.value)
            update_session_meta(sid, phase=Phase.ERROR.value)

        return state

    def _token_limit(self, agent: AgentDef, *, debate: bool) -> int:
        if debate and agent.max_tokens_debate is not None:
            return agent.max_tokens_debate
        if not debate and agent.max_tokens_independent is not None:
            return agent.max_tokens_independent
        return settings.max_tokens_per_agent

    async def _chat_and_bill(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None,
        temperature: float,
        timeout: float,
        label: str,
    ) -> str:
        result = await self.provider.chat(
            model,
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )
        if self._actor:
            await record_chat_usage(
                self._actor,
                session_id=self._session_id,
                model=result.model or model,
                usage=result.usage,
                label=label,
            )
        return result.content

    async def _call_agent(
        self,
        agent: AgentDef,
        user_content: str,
        *,
        debate: bool,
        goal: str,
    ) -> str:
        ideation = agent.id.value in ("diator", "visionary") and not debate
        messages = [
            {
                "role": "system",
                "content": build_system_prompt(agent, debate=debate, goal=goal, ideation=ideation),
            },
            {"role": "user", "content": user_content},
        ]
        timeout = agent.timeout_seconds or settings.agent_timeout_seconds
        max_tokens = self._token_limit(agent, debate=debate)
        label = agent.id.value

        async def _do() -> str:
            return await self._chat_and_bill(
                agent.model,
                messages,
                max_tokens=max_tokens,
                temperature=0.68 if debate else 0.72,
                timeout=timeout,
                label=label,
            )

        try:
            return await asyncio.wait_for(_do(), timeout=timeout + 15)
        except asyncio.TimeoutError:
            if agent.id.value == "diator":
                short = user_content + "\n\n**Макс. 350 слов, буллеты.**"
                retry_msg = [
                    {"role": "system", "content": build_system_prompt(agent, debate=debate, goal=goal)},
                    {"role": "user", "content": short},
                ]

                async def _retry() -> str:
                    return await self._chat_and_bill(
                        agent.model,
                        retry_msg,
                        max_tokens=min(max_tokens, 450),
                        temperature=0.6,
                        timeout=timeout,
                        label=label,
                    )

                try:
                    return await asyncio.wait_for(_retry(), timeout=timeout + 15)
                except asyncio.TimeoutError:
                    pass
            raise TimeoutError(
                f"{agent.name} не ответил за {int(timeout)}с ({agent.model})"
            ) from None

    async def _run_agent(
        self,
        agent: AgentDef,
        state: SessionState,
        memory: SharedMemory,
        emit: Callable[..., None],
        persist: Callable[[AgentMessage], None],
        *,
        phase: Phase,
        round_num: int,
        user_block: str,
        debate: bool,
    ) -> AgentMessage:
        emit("agent_start", agent_id=agent.id.value, phase=phase.value, round=round_num)
        emit("status", message=f"Думает: {agent.name} (лимит 3 мин)…")

        content = await self._call_agent(agent, user_block, debate=debate, goal=state.goal)
        msg = AgentMessage(
            agent_id=agent.id,
            phase=phase,
            round=round_num,
            content=content,
            model=agent.model,
        )
        emit(
            "agent_message",
            agent_id=agent.id.value,
            phase=phase.value,
            round=round_num,
            content=content,
            model=agent.model,
        )
        persist(msg)
        memory.add_message(msg)
        state.messages.append(msg)
        return msg

    async def _run_agent_list(
        self,
        agents: list[AgentDef],
        state: SessionState,
        memory: SharedMemory,
        emit: Callable[..., None],
        persist: Callable[[AgentMessage], None],
        *,
        phase: Phase,
        round_num: int,
        debate: bool,
        extra_builder,
    ) -> None:
        is_ideation = agents and agents[0].id.value in ("diator", "visionary") and not debate
        time_limit = (
            "\n\n**Лимит ответа: до 3 минут. Идеаторы: не режь список — нужны все 10+ идей.**"
            if is_ideation
            else "\n\n**Лимит: до 3 минут. Структурированно, без воды.**"
        )
        for agent in agents:
            prior = format_prior_digest(memory.messages, exclude_agent=agent.id.value)
            extra = extra_builder(agent, prior)
            user_block = memory.build_context(extra=extra) + time_limit
            await self._run_agent(
                agent, state, memory, emit, persist,
                phase=phase, round_num=round_num, user_block=user_block, debate=debate,
            )

    async def _independent_phase(self, state, memory, wave1, wave2, emit, persist) -> None:
        emit("wave", wave=1, label="Идеи: Генератор идей → Визионер")
        emit("status", message="Сначала идеатор и креатив…")
        await self._run_agent_list(
            wave1, state, memory, emit, persist,
            phase=Phase.INDEPENDENT, round_num=0, debate=False,
            extra_builder=lambda a, prior: (
                f"---\nУже высказались:\n{prior}\n\n---\n"
                f"Твой вклад ({a.name}): сначала спрос/рынок, затем минимум 10 нумерованных идей, "
                f"потом топ-5 лучших по спросу."
            ),
        )
        emit("wave", wave=2, label="Анализ: Архитектор → Критик")
        emit("status", message="Теперь архитектор и критик (видят идеи выше)…")
        await self._run_agent_list(
            wave2, state, memory, emit, persist,
            phase=Phase.INDEPENDENT, round_num=0, debate=False,
            extra_builder=lambda a, prior: (
                f"---\nИдеи и креатив коллег (обязательно учти):\n{prior}\n\n"
                f"---\nТвой вклад ({a.name}) — реализм, риски, цифры."
            ),
        )

    async def _debate_round(self, state, memory, wave1, wave2, round_num, emit, persist, note=None) -> None:
        emit("status", message=f"Дебаты {round_num}: сначала идеи, потом анализ")
        note_block = f"\n\nУточнение пользователя:\n{note}" if note else ""

        def debate_extra(agent, prior):
            peers = format_peer_digest(memory.messages, exclude_agent=agent.id.value, round_num=round_num)
            return f"---\nПозиции коллег:\n{peers}\n\nРаунд {round_num}. CB + резюме.{note_block}"

        await self._run_agent_list(
            wave1, state, memory, emit, persist,
            phase=Phase.DEBATE, round_num=round_num, debate=True, extra_builder=debate_extra,
        )
        await self._run_agent_list(
            wave2, state, memory, emit, persist,
            phase=Phase.DEBATE, round_num=round_num, debate=True, extra_builder=debate_extra,
        )

    async def _review_phase(self, state, memory, wave1, wave2, emit, persist) -> None:
        def review_extra(agent, prior):
            return f"""---
Пересмотр после критики ({agent.name}). CB кратко, затем `---` и 3–5 предложений.

Коллеги:
{prior}
"""

        await self._run_agent_list(
            wave1, state, memory, emit, persist,
            phase=Phase.REVIEW, round_num=0, debate=True, extra_builder=review_extra,
        )
        await self._run_agent_list(
            wave2, state, memory, emit, persist,
            phase=Phase.REVIEW, round_num=0, debate=True, extra_builder=review_extra,
        )


async def run_with_sse_queue(
    prompt: str,
    queue: asyncio.Queue[StreamEvent | None],
    **kwargs,
) -> SessionState:
    def on_event(ev: StreamEvent) -> None:
        queue.put_nowait(ev)

    orch = ConsiliumOrchestrator()
    state = await orch.run(prompt, on_event=on_event, **kwargs)
    queue.put_nowait(None)
    return state
