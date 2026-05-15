"""OpenRouter model registry: fetch, filter, presets, auto-stack."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

MODELS_URL = "https://openrouter.ai/api/v1/models"
CACHE_TTL = 3600
_VERIFIED_PATH = Path(__file__).resolve().parent.parent / "data" / "chat_models_verified.json"

# Дороже порога UI, но проверены вручную (chat/completions 200)
_EXTRA_VERIFIED_CHAT = frozenset(
    {
        "anthropic/claude-sonnet-4",
        "openai/gpt-4o",
        "openai/gpt-4o-mini",
    }
)

# Не chat/completions (audio, image-gen, router-only, …)
_CHAT_ID_BLOCKLIST = (
    "lyria",
    "gpt-audio",
    "dall-e",
    "stable-diffusion",
    "/flux",
    "embed",
    "whisper",
    "moderation",
    "switchpoint/router",
    "relace/apply",
    "spotlight",
    "virtuoso-large",
    "coder-large",
    "maestro-reasoning",
)

_cache: dict[str, Any] = {"at": 0.0, "models": []}
_verified_chat_ids: frozenset[str] | None = None
_verified_loaded: bool = False


def _load_verified_chat_ids() -> frozenset[str] | None:
    """None = не фильтровать (файла нет); иначе только id из probe + extra."""
    global _verified_chat_ids, _verified_loaded
    if _verified_loaded:
        return _verified_chat_ids
    _verified_loaded = True
    if not _VERIFIED_PATH.is_file():
        return None
    ids: set[str] = set(_EXTRA_VERIFIED_CHAT)
    try:
        data = json.loads(_VERIFIED_PATH.read_text(encoding="utf-8"))
        ids.update(data.get("ok") or [])
        _verified_chat_ids = frozenset(ids)
    except (json.JSONDecodeError, OSError):
        _verified_chat_ids = None
    return _verified_chat_ids


def _raw_is_chat_capable(raw: dict[str, Any]) -> bool:
    mid = (raw.get("id") or "").lower()
    if any(b in mid for b in _CHAT_ID_BLOCKLIST):
        return False
    arch = raw.get("architecture") or {}
    modality = (arch.get("modality") or "").lower()
    out_mod = arch.get("output_modalities") or []
    outs = [str(x).lower() for x in out_mod] if isinstance(out_mod, list) else []
    if outs and not any("text" in o for o in outs):
        return False
    if modality and "text" not in modality and "->text" not in modality:
        if not outs or not any("text" in o for o in outs):
            return False
    return True

ROLE_KEYS = ("diator", "visionary", "architect", "critic", "synthesis")


@dataclass
class ModelInfo:
    id: str
    name: str
    provider: str
    input_price_per_m: float  # USD per 1M input tokens
    output_price_per_m: float
    context_length: int
    supports_tools: bool
    supports_vision: bool
    recommended_use: str
    is_stable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "input_price_per_m": round(self.input_price_per_m, 4),
            "output_price_per_m": round(self.output_price_per_m, 4),
            "context_length": self.context_length,
            "supports_tools": self.supports_tools,
            "supports_vision": self.supports_vision,
            "recommended_use": self.recommended_use,
            "tags": self._tags(),
        }

    def _tags(self) -> list[str]:
        tags: list[str] = []
        avg = (self.input_price_per_m + self.output_price_per_m) / 2
        if avg < 0.5:
            tags.append("cheap")
        if self.context_length >= 128_000:
            tags.append("long_context")
        if self.supports_vision:
            tags.append("vision")
        if self.supports_tools:
            tags.append("tools")
        if "claude" in self.id or "o1" in self.id or "o3" in self.id:
            tags.append("reasoning")
        if "grok" in self.id or "owl" in self.id or "hermes" in self.id or "dolphin" in self.id:
            tags.append("creative")
        if any(x in self.id for x in ("grok-4.3", "grok-4-fast", "grok-3-mini", "flash", "gemini-2.5-flash-lite")):
            tags.append("fast")
        return tags


@dataclass
class CouncilModelConfig:
    price_threshold: float = 10.0
    preset: str = "balanced"
    models: dict[str, str] = field(default_factory=dict)
    snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)

    def get_model(self, role: str, default: str) -> str:
        return self.models.get(role) or default

    def to_json(self) -> str:
        return json.dumps(
            {
                "price_threshold": self.price_threshold,
                "preset": self.preset,
                "models": self.models,
                "snapshots": self.snapshots,
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: str | None) -> CouncilModelConfig:
        if not raw:
            return cls()
        try:
            d = json.loads(raw)
            return cls(
                price_threshold=float(d.get("price_threshold", 10)),
                preset=d.get("preset", "balanced"),
                models=d.get("models", {}),
                snapshots=d.get("snapshots", {}),
            )
        except (json.JSONDecodeError, TypeError):
            return cls()


def _price_per_m(val: str | float | None) -> float:
    if val is None:
        return 0.0
    try:
        p = float(val)
        # OpenRouter returns per-token; convert to per 1M
        return p * 1_000_000
    except (TypeError, ValueError):
        return 0.0


def _parse_model(raw: dict[str, Any]) -> ModelInfo | None:
    mid = raw.get("id") or ""
    if not mid or not _raw_is_chat_capable(raw):
        return None
    verified = _load_verified_chat_ids()
    if verified is not None and mid not in verified:
        return None
    name = raw.get("name") or mid
    arch = raw.get("architecture") or {}
    modality = (arch.get("modality") or "").lower()
    pricing = raw.get("pricing") or {}
    inp = _price_per_m(pricing.get("prompt"))
    out = _price_per_m(pricing.get("completion"))
    ctx = int(raw.get("context_length") or 32_000)
    provider = mid.split("/")[0] if "/" in mid else "unknown"
    unstable = any(x in mid.lower() for x in ("deprecated", "old", "expired"))
    if unstable:
        return None
    supports_vision = "image" in modality or "vision" in mid.lower()
    supports_tools = True  # most OR models support tools
    use = "general"
    if "claude" in mid:
        use = "analysis / reasoning"
    elif "grok" in mid or "owl" in mid:
        use = "creative / ideation"
    elif "gemini" in mid:
        use = "synthesis / long context"
    elif "gpt" in mid:
        use = "architecture / tools"
    return ModelInfo(
        id=mid,
        name=name,
        provider=provider,
        input_price_per_m=inp,
        output_price_per_m=out,
        context_length=ctx,
        supports_tools=supports_tools,
        supports_vision=supports_vision,
        recommended_use=use,
    )


async def fetch_models(force: bool = False) -> list[ModelInfo]:
    now = time.time()
    if not force and _cache["models"] and now - _cache["at"] < CACHE_TTL:
        return _cache["models"]

    headers = {"Authorization": f"Bearer {settings.openrouter_api_key}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(MODELS_URL, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    parsed: list[ModelInfo] = []
    for raw in data.get("data", []):
        m = _parse_model(raw)
        if m:
            parsed.append(m)

    parsed.sort(key=lambda x: (x.input_price_per_m + x.output_price_per_m) / 2)
    _cache["models"] = parsed
    _cache["at"] = now
    return parsed


def filter_models(
    models: list[ModelInfo],
    *,
    price_threshold: float,
    require_vision: bool = False,
    min_context: int = 0,
) -> list[ModelInfo]:
    out: list[ModelInfo] = []
    for m in models:
        if m.input_price_per_m > price_threshold and m.output_price_per_m > price_threshold:
            continue
        if require_vision and not m.supports_vision:
            continue
        if m.context_length < min_context:
            continue
        out.append(m)
    return out


def _pick(
    models: list[ModelInfo],
    *,
    prefer: list[str],
    tag: str | None = None,
    cheap: bool = False,
) -> str:
    by_id = {m.id: m for m in models}
    for pid in prefer:
        if pid in by_id:
            return pid
    if tag:
        tagged = [m for m in models if tag in m._tags()]
        if tagged:
            tagged.sort(key=lambda x: (x.input_price_per_m + x.output_price_per_m) / 2)
            return tagged[0].id if cheap else tagged[-1].id
    return models[0].id if models else prefer[0]


# Grok 4.3 — актуальный fast; grok-3-mini — дешевле.
PRESET_STACKS: dict[str, dict[str, list[str]]] = {
    "cheap": {
        "diator": [
            "x-ai/grok-3-mini",
            "x-ai/grok-4.3",
            "google/gemini-2.5-flash-lite",
        ],
        "visionary": [
            "x-ai/grok-3-mini",
            "nousresearch/hermes-3-llama-3.1-70b",
            "google/gemini-2.0-flash-001",
        ],
        "architect": ["openai/gpt-4o-mini", "google/gemini-2.0-flash-001"],
        "critic": ["openai/gpt-4o-mini", "anthropic/claude-3-haiku"],
        "synthesis": ["google/gemini-2.0-flash-001", "openai/gpt-4o-mini"],
    },
    "balanced": {
        "diator": [
            "x-ai/grok-4.3",
            "x-ai/grok-3-mini",
            "google/gemini-2.5-flash-lite",
        ],
        "visionary": [
            "nousresearch/hermes-4-70b",
            "mistralai/mistral-saba",
            "google/gemini-2.5-flash",
            "x-ai/grok-4.3",
        ],
        "architect": ["anthropic/claude-sonnet-4", "openai/gpt-4o"],
        "critic": ["anthropic/claude-sonnet-4", "openai/gpt-4o"],
        "synthesis": ["google/gemini-2.5-pro-preview", "anthropic/claude-sonnet-4"],
    },
    "creative": {
        "diator": ["x-ai/grok-4.3", "x-ai/grok-3-mini"],
        "visionary": [
            "nousresearch/hermes-4-70b",
            "openrouter/owl-alpha",
            "mistralai/mistral-saba",
            "x-ai/grok-4.3",
        ],
        "architect": ["anthropic/claude-sonnet-4", "openai/gpt-4o"],
        "critic": ["anthropic/claude-sonnet-4"],
        "synthesis": ["google/gemini-2.5-pro-preview", "x-ai/grok-4.3"],
    },
    "analyst": {
        "diator": [
            "x-ai/grok-4.3",
            "perplexity/sonar",
            "google/gemini-2.5-flash-lite",
        ],
        "visionary": ["nousresearch/hermes-4-70b", "anthropic/claude-sonnet-4"],
        "architect": ["anthropic/claude-sonnet-4", "openai/gpt-4o"],
        "critic": ["anthropic/claude-sonnet-4", "openai/gpt-4o-mini"],
        "synthesis": ["anthropic/claude-sonnet-4", "google/gemini-2.5-pro-preview"],
    },
    "startup_war_room": {
        "diator": ["x-ai/grok-4.3", "x-ai/grok-3-mini"],
        "visionary": ["nousresearch/hermes-4-70b", "x-ai/grok-4.3"],
        "architect": ["anthropic/claude-sonnet-4"],
        "critic": ["anthropic/claude-sonnet-4"],
        "synthesis": ["google/gemini-2.5-pro-preview"],
    },
}


def apply_preset(
    models: list[ModelInfo],
    preset: str,
    price_threshold: float,
) -> dict[str, str]:
    filtered = filter_models(models, price_threshold=price_threshold)
    stack = PRESET_STACKS.get(preset, PRESET_STACKS["balanced"])
    result: dict[str, str] = {}
    for role in ROLE_KEYS:
        prefs = stack.get(role, [])
        result[role] = _pick(filtered, prefer=prefs, cheap=(preset == "cheap"))
    return result


def auto_select_stack(
    models: list[ModelInfo],
    *,
    price_threshold: float,
    prompt: str,
    has_images: bool,
    has_files: bool,
) -> dict[str, str]:
    filtered = filter_models(
        models,
        price_threshold=price_threshold,
        require_vision=has_images,
        min_context=64_000 if len(prompt) > 4000 else 0,
    )
    if not filtered:
        filtered = filter_models(models, price_threshold=price_threshold * 2)

    long_task = len(prompt) > 2000
    market = any(w in prompt.lower() for w in ("рынок", "market", "revenue", "конкурент"))

    result = apply_preset(filtered, "balanced", price_threshold)

    if has_images:
        vision = [m for m in filtered if m.supports_vision]
        if vision:
            v = vision[0].id
            result["critic"] = _pick(vision, prefer=[v], tag="vision")

    if market:
        result["critic"] = _pick(
            filtered,
            prefer=["anthropic/claude-sonnet-4", "openai/gpt-4o"],
            tag="reasoning",
        )

    if long_task:
        long_ctx = sorted(filtered, key=lambda m: m.context_length, reverse=True)
        if long_ctx:
            result["synthesis"] = long_ctx[0].id

    result["diator"] = _pick(
        filtered,
        prefer=[
            "x-ai/grok-4.3",
            "x-ai/grok-3-mini",
            "google/gemini-2.5-flash-lite",
        ],
        tag="fast",
    )
    result["visionary"] = _pick(
        filtered,
        prefer=[
            "nousresearch/hermes-4-70b",
            "mistralai/mistral-saba",
            "x-ai/grok-4.3",
            "google/gemini-2.5-flash",
        ],
        tag="creative",
    )

    return result


def snapshots_for_models(models: list[ModelInfo], role_models: dict[str, str]) -> dict[str, dict]:
    by_id = {m.id: m for m in models}
    out: dict[str, dict] = {}
    for role, mid in role_models.items():
        m = by_id.get(mid)
        if m:
            out[role] = m.to_dict()
    return out
