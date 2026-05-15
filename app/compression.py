from app.agents import get_agents, get_agents_ordered
from app.models import AgentMessage, Phase
from app.protocol import COUNCIL_ORDER


def format_prior_digest(
    messages: list[AgentMessage],
    *,
    exclude_agent: str | None = None,
    debate_round: int | None = None,
    include_same_round: bool = False,
) -> str:
    """Context from agents who already spoke (sequential council)."""
    lines: list[str] = []
    order = list(COUNCIL_ORDER)
    if exclude_agent and exclude_agent in order:
        stop_idx = order.index(exclude_agent)
        allowed_ids = set(order[:stop_idx])
    else:
        allowed_ids = {a.id.value for a in get_agents()}

    for agent in get_agents_ordered():
        if agent.id.value not in allowed_ids:
            continue
        if exclude_agent and agent.id.value == exclude_agent:
            continue

        agent_msgs = []
        for m in messages:
            if m.agent_id.value != agent.id.value:
                continue
            if m.phase in (Phase.INDEPENDENT, Phase.REVIEW):
                agent_msgs.append(m)
            elif m.phase == Phase.DEBATE and debate_round is not None:
                if m.round < debate_round:
                    agent_msgs.append(m)
                elif include_same_round and m.round == debate_round:
                    agent_msgs.append(m)

        if not agent_msgs:
            continue
        latest = agent_msgs[-1]
        snippet = latest.content[:2500]
        if len(latest.content) > 2500:
            snippet += "\n…[обрезано]"
        lines.append(f"### {agent.name} ({agent.role})\n{snippet}")

    return "\n\n".join(lines) if lines else "(предыдущих ответов пока нет)"


def format_peer_digest(messages: list[AgentMessage], *, exclude_agent: str, round_num: int) -> str:
    """Debate: all peers from prior rounds + same round before this agent."""
    return format_prior_digest(
        messages,
        exclude_agent=exclude_agent,
        debate_round=round_num,
        include_same_round=True,
    )


def compress_round(messages: list[AgentMessage], round_num: int) -> str:
    parts: list[str] = []
    for m in messages:
        if m.phase == Phase.DEBATE and m.round == round_num:
            cb = _extract_cb_block(m.content)
            parts.append(f"[{m.agent_id.value}] {cb or m.content[:400]}")
    return "\n".join(parts)


def _extract_cb_block(text: str) -> str:
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(("!", "?", "+", "-", "~", "@")):
            lines.append(s)
    return "\n".join(lines)


def build_synthesis_input(
    user_prompt: str,
    messages: list[AgentMessage],
    compressed_context: str,
) -> str:
    independent = [m for m in messages if m.phase == Phase.INDEPENDENT]
    debate = [m for m in messages if m.phase == Phase.DEBATE]

    sections = [f"## Задача пользователя\n{user_prompt}\n"]

    if independent:
        sections.append("## Независимые вклады (по порядку)")
        for m in independent:
            sections.append(f"### {m.agent_id.value}\n{m.content[:3500]}\n")

    if debate:
        sections.append("## Дебаты")
        for m in debate:
            cb = _extract_cb_block(m.content)
            body = cb if cb else m.content[:800]
            sections.append(f"### Раунд {m.round} — {m.agent_id.value}\n{body}\n")

    if compressed_context:
        sections.append(f"## Сжатие раундов\n{compressed_context}\n")

    return "\n".join(sections)
