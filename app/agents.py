from dataclasses import dataclass, replace

from app.config import settings
from app.model_registry import CouncilModelConfig
from app.models import AgentId
from app.protocol import DEBATE_SYSTEM_SUFFIX, IDEATION_WAVE_SUFFIX, INDEPENDENT_SYSTEM_SUFFIX


@dataclass(frozen=True)
class AgentDef:
    id: AgentId
    name: str
    role: str
    model: str
    personality: str
    column_color: str
    max_tokens_independent: int | None = None
    max_tokens_debate: int | None = None
    timeout_seconds: float | None = None


def _base_agents() -> list[AgentDef]:
    return [
        AgentDef(
            id=AgentId.DIATOR,
            name="Генератор идей",
            role="R&D · безумный учёный",
            model=settings.resolved_diator_model(),
            personality=(
                "Ты Генератор идей — R&D-директор. Сначала анализ спроса и рынка, потом минимум 10 идей. "
                "Отбираешь лучшие по платящему спросу, не по креативности. "
                "Хаки: Reddit, PH, indie hackers, X, growth. Комбинируешь чужие идеи."
            ),
            column_color="#c4a35a",
            max_tokens_independent=settings.max_tokens_diator,
            max_tokens_debate=settings.max_tokens_diator_debate,
            timeout_seconds=settings.diator_timeout_seconds,
        ),
        AgentDef(
            id=AgentId.VISIONARY,
            name="Визионер",
            role="Креатив · маркетинг",
            model=settings.model_visionary,
            personality=(
                "Ты Визионер — креативный директор. Сначала спрос, потом 10+ идей с углом viral/бренд. "
                "Усиливаешь идеи Генератора идей, добавляешь свои. Топ-5 по рынку — развёрнуто."
            ),
            column_color="#9b6bd4",
            max_tokens_independent=settings.max_tokens_visionary,
            max_tokens_debate=550,
        ),
        AgentDef(
            id=AgentId.ARCHITECT,
            name="Архитектор",
            role="Инженер-стратег",
            model=settings.model_architect,
            personality=(
                "Ты Архитектор — инженер-стратег с открытым умом. "
                "Не убийца идей: «Как это реализовать на практике?»"
            ),
            column_color="#5b8def",
        ),
        AgentDef(
            id=AgentId.CRITIC,
            name="Критик",
            role="Холодный аналитик",
            model=settings.model_critic,
            personality=(
                "Ты Критик — холодный аналитик с данными. "
                "«Что убьёт идею в реальном мире?» — без токсичности."
            ),
            column_color="#e05b6a",
        ),
    ]


def get_agents(council: CouncilModelConfig | None = None) -> list[AgentDef]:
    agents = _base_agents()
    if not council or not council.models:
        return agents
    out: list[AgentDef] = []
    for a in agents:
        mid = council.get_model(a.id.value, a.model)
        out.append(replace(a, model=mid))
    return out


def get_agents_ordered(council: CouncilModelConfig | None = None) -> list[AgentDef]:
    from app.protocol import COUNCIL_ORDER

    by_id = {a.id.value: a for a in get_agents(council)}
    return [by_id[aid] for aid in COUNCIL_ORDER]


def get_agent_waves(council: CouncilModelConfig | None = None) -> tuple[list[AgentDef], list[AgentDef]]:
    from app.protocol import WAVE_ANALYSIS, WAVE_IDEATION

    by_id = {a.id.value: a for a in get_agents(council)}
    w1 = [by_id[i] for i in WAVE_IDEATION if i in by_id]
    w2 = [by_id[i] for i in WAVE_ANALYSIS if i in by_id]
    return w1, w2


def synthesis_model(council: CouncilModelConfig | None = None) -> str:
    if council and council.models.get("synthesis"):
        return council.models["synthesis"]
    return settings.model_synthesis


def build_system_prompt(agent: AgentDef, *, debate: bool, goal: str, ideation: bool = False) -> str:
    if debate:
        mode = DEBATE_SYSTEM_SUFFIX
    elif ideation:
        mode = INDEPENDENT_SYSTEM_SUFFIX + IDEATION_WAVE_SUFFIX
    else:
        mode = INDEPENDENT_SYSTEM_SUFFIX
    goal_block = f"\n## Цель задачи (не забывать)\n{goal}\n" if goal else ""
    return f"{agent.personality}\n{goal_block}\nТвой id в CB: `{agent.id.value}`.\n{mode}"
