import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agents import get_agents, synthesis_model
from app.auth.context import ActorContext
from app.auth.deps import enforce_council_access, get_actor, require_registered_user
from app.auth.guest import register_guest_run_start
from app.auth.routes import router as auth_router
from app.billing.routes import router as billing_router
from app.security.bootstrap import validate_settings
from app.security.middleware import SecurityHeadersMiddleware
from app.billing.service import ensure_can_start_council, refresh_actor_balance
from app.config import settings
from app.database import init_db, list_sessions, load_session, messages_to_state
from app.files import build_attachments_context, extract_upload_text
from app.model_registry import (
    CouncilModelConfig,
    apply_preset,
    auto_select_stack,
    fetch_models,
    filter_models,
    snapshots_for_models,
)
from app.models import CouncilConfigBody, Phase, ReviseRequest, RunRequest, StreamEvent
from app.orchestrator import ConsiliumOrchestrator, run_with_sse_queue

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_settings()
    init_db()
    yield


app = FastAPI(title="Consilium", lifespan=lifespan)
app.add_middleware(SecurityHeadersMiddleware)
app.include_router(auth_router)
app.include_router(billing_router)


@app.get("/account.html")
async def account_page():
    p = STATIC_DIR / "account.html"
    return FileResponse(p) if p.exists() else HTTPException(404)

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    p = STATIC_DIR / "index.html"
    return FileResponse(p) if p.exists() else {"message": "Consilium API"}


@app.get("/auth.html")
async def auth_page():
    p = STATIC_DIR / "auth.html"
    return FileResponse(p) if p.exists() else HTTPException(404)


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "environment": settings.environment,
        "master_mode_allowed": settings.master_mode_allowed,
        "openrouter_configured": bool(settings.openrouter_api_key),
        "stripe_configured": bool(settings.stripe_secret_key),
        "google_oauth_configured": bool(settings.google_client_id),
        "models": {
            "diator": settings.resolved_diator_model(),
            "visionary": settings.model_visionary,
            "architect": settings.model_architect,
            "critic": settings.model_critic,
            "synthesis": settings.model_synthesis,
        },
        "synthesis_max_tokens": settings.max_tokens_synthesis,
    }


@app.get("/api/council/env-defaults")
async def council_env_defaults():
    """Модели из .env — приоритет над пресетом в UI при старте."""
    return {
        "models": {
            "diator": settings.resolved_diator_model(),
            "visionary": settings.model_visionary,
            "architect": settings.model_architect,
            "critic": settings.model_critic,
            "synthesis": settings.model_synthesis,
        }
    }


@app.get("/api/agents")
async def list_agents(council: str | None = None):
    cfg = CouncilModelConfig.from_json(council) if council else CouncilModelConfig()
    return [
        {
            "id": a.id.value,
            "name": a.name,
            "role": a.role,
            "model": a.model,
            "color": a.column_color,
        }
        for a in get_agents(cfg)
    ]


@app.get("/api/models")
async def api_models(
    price_threshold: float = Query(10.0, description="Max USD per 1M input tokens"),
    require_vision: bool = False,
):
    if not settings.openrouter_api_key:
        raise HTTPException(503, "OPENROUTER_API_KEY not configured")
    try:
        all_models = await fetch_models()
    except Exception as e:
        raise HTTPException(502, f"Не удалось загрузить модели: {e}") from e
    filtered = filter_models(all_models, price_threshold=price_threshold, require_vision=require_vision)
    return {"models": [m.to_dict() for m in filtered], "total": len(filtered)}


class AutoSelectBody(BaseModel):
    prompt: str = ""
    price_threshold: float = 10.0
    has_images: bool = False
    has_files: bool = False


@app.post("/api/council/auto-select")
async def council_auto_select(body: AutoSelectBody):
    if not settings.openrouter_api_key:
        raise HTTPException(503, "OPENROUTER_API_KEY not configured")
    all_models = await fetch_models()
    role_models = auto_select_stack(
        all_models,
        price_threshold=body.price_threshold,
        prompt=body.prompt,
        has_images=body.has_images,
        has_files=body.has_files,
    )
    snaps = snapshots_for_models(all_models, role_models)
    council = CouncilModelConfig(
        price_threshold=body.price_threshold,
        preset="auto",
        models=role_models,
        snapshots=snaps,
    )
    return {"council_config": json.loads(council.to_json())}


class PresetBody(BaseModel):
    preset: str = "balanced"
    price_threshold: float = 10.0


@app.post("/api/council/preset")
async def council_preset(body: PresetBody):
    if not settings.openrouter_api_key:
        raise HTTPException(503, "OPENROUTER_API_KEY not configured")
    all_models = await fetch_models()
    role_models = apply_preset(all_models, body.preset, body.price_threshold)
    snaps = snapshots_for_models(all_models, role_models)
    council = CouncilModelConfig(
        price_threshold=body.price_threshold,
        preset=body.preset,
        models=role_models,
        snapshots=snaps,
    )
    return {"council_config": json.loads(council.to_json())}


@app.get("/api/sessions")
async def sessions_list(actor: ActorContext = Depends(get_actor)):
    if actor.user_id:
        return list_sessions(user_id=actor.user_id)
    if actor.guest_id:
        return list_sessions(guest_id=actor.guest_id)
    return []


def _assert_session_access(data: dict, actor: ActorContext) -> None:
    if actor.bypass_limits:
        return
    sess = data.get("session") or {}
    owner_user = sess.get("user_id")
    owner_guest = sess.get("guest_id")
    if actor.user_id:
        if owner_user and owner_user != actor.user_id:
            raise HTTPException(403, detail="Нет доступа к сессии")
        if owner_guest and not owner_user:
            raise HTTPException(403, detail="Нет доступа к сессии")
        return
    if actor.guest_id:
        if owner_guest and owner_guest != actor.guest_id:
            raise HTTPException(403, detail="Нет доступа к сессии")
        if owner_user:
            raise HTTPException(403, detail="Нет доступа к сессии")
        return
    raise HTTPException(401, detail={"code": "AUTH_REQUIRED", "message": "Требуется вход"})


@app.get("/api/sessions/{session_id}")
async def session_detail(session_id: str, actor: ActorContext = Depends(get_actor)):
    data = load_session(session_id)
    if not data:
        raise HTTPException(404, "Сессия не найдена")
    _assert_session_access(data, actor)
    return data


@app.get("/api/sessions/{session_id}/verdicts/compare")
async def compare_verdicts(session_id: str, actor: ActorContext = Depends(get_actor)):
    data = load_session(session_id)
    if not data:
        raise HTTPException(404, "Сессия не найдена")
    _assert_session_access(data, actor)
    verdicts = data.get("verdicts", [])
    if len(verdicts) < 2:
        return {"versions": verdicts, "message": "Нужно минимум 2 версии для сравнения"}
    return {
        "older": verdicts[-2],
        "newer": verdicts[-1],
        "count": len(verdicts),
    }


def _council_from_json(raw: str | None) -> CouncilModelConfig | None:
    if not raw:
        return None
    try:
        d = json.loads(raw)
        return CouncilModelConfig(
            price_threshold=float(d.get("price_threshold", 10)),
            preset=d.get("preset", "balanced"),
            models=d.get("models", {}),
            snapshots=d.get("snapshots", {}),
        )
    except (json.JSONDecodeError, TypeError):
        return None


async def _attachments_from_files(files: list[UploadFile] | None) -> tuple[str, bool]:
    if not files:
        return "", False
    blocks: list[tuple[str, str]] = []
    has_images = False
    for f in files:
        if not f.filename:
            continue
        ext = Path(f.filename).suffix.lower()
        if ext in IMAGE_EXT:
            has_images = True
        raw = await f.read()
        if len(raw) > 5_000_000:
            raise HTTPException(400, f"Файл {f.filename} слишком большой")
        text = await extract_upload_text(f.filename, raw)
        blocks.append((f.filename, text))
    return build_attachments_context(blocks), has_images


def _stream_response(task_kwargs: dict):
    queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue()

    async def generate():
        prompt = task_kwargs.pop("prompt")
        task = asyncio.create_task(run_with_sse_queue(prompt, queue, **task_kwargs))
        try:
            while True:
                ev = await queue.get()
                if ev is None:
                    break
                payload = json.dumps(ev.model_dump(), ensure_ascii=False)
                yield f"event: {ev.type}\ndata: {payload}\n\n"
            state = await task
            done = StreamEvent(
                type="done",
                data={
                    "session_id": state.session_id,
                    "final_verdict": state.final_verdict,
                    "phase": state.phase.value,
                    "error": state.error,
                    "verdict_version": state.verdict_version,
                },
            )
            yield f"event: done\ndata: {json.dumps(done.model_dump(), ensure_ascii=False)}\n\n"
        except Exception as e:
            err = StreamEvent(type="error", data={"message": str(e)})
            yield f"event: error\ndata: {json.dumps(err.model_dump(), ensure_ascii=False)}\n\n"
            if not task.done():
                task.cancel()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _prepare_council_run(actor: ActorContext) -> ActorContext:
    actor = refresh_actor_balance(actor)
    enforce_council_access(actor)
    ensure_can_start_council(actor)
    if actor.is_guest and actor.guest_id:
        register_guest_run_start(actor.guest_id)
    return actor


@app.post("/api/run/stream")
async def run_stream(
    prompt: str = Form(...),
    max_debate_rounds: int | None = Form(None),
    council_config: str | None = Form(None),
    files: list[UploadFile] = File(default=[]),
    actor: ActorContext = Depends(get_actor),
):
    if not settings.openrouter_api_key:
        raise HTTPException(503, "OPENROUTER_API_KEY not configured")
    if len(prompt.strip()) < 10:
        raise HTTPException(400, "Минимум 10 символов в задаче")
    actor = _prepare_council_run(actor)
    attachments, has_images = await _attachments_from_files(files if files else None)
    council = _council_from_json(council_config)
    return _stream_response(
        {
            "prompt": prompt.strip(),
            "max_debate_rounds": max_debate_rounds,
            "attachments_context": attachments,
            "council_config": council,
            "has_images": has_images,
            "actor": actor,
        }
    )


@app.post("/api/run/stream/json")
async def run_stream_json(body: RunRequest, actor: ActorContext = Depends(get_actor)):
    if not settings.openrouter_api_key:
        raise HTTPException(503, "OPENROUTER_API_KEY not configured")
    actor = _prepare_council_run(actor)
    council = None
    if body.council_config:
        council = CouncilModelConfig(
            price_threshold=body.council_config.price_threshold,
            preset=body.council_config.preset,
            models=body.council_config.models,
        )
    return _stream_response(
        {
            "prompt": body.prompt,
            "max_debate_rounds": body.max_debate_rounds,
            "session_id": body.session_id,
            "council_config": council,
            "actor": actor,
        }
    )


@app.post("/api/sessions/{session_id}/revise/stream")
async def revise_stream(
    session_id: str,
    body: ReviseRequest,
    actor: ActorContext = Depends(get_actor),
):
    if not settings.openrouter_api_key:
        raise HTTPException(503, "OPENROUTER_API_KEY not configured")
    actor = refresh_actor_balance(actor)
    if not actor.bypass_limits:
        if not actor.is_authenticated:
            enforce_council_access(actor)
        ensure_can_start_council(actor)
    data = load_session(session_id)
    if not data:
        raise HTTPException(404, "Сессия не найдена")
    sess = data["session"]
    if actor.user_id and sess.get("user_id") and sess["user_id"] != actor.user_id:
        raise HTTPException(403, detail="Нет доступа к сессии")
    if actor.guest_id and sess.get("guest_id") and sess["guest_id"] != actor.guest_id:
        raise HTTPException(403, detail="Нет доступа к сессии")
    prior = messages_to_state(data)
    version = int(data["session"].get("verdict_version") or 1)
    council = CouncilModelConfig.from_json(data["session"].get("council_config"))
    return _stream_response(
        {
            "prompt": data["session"]["prompt"],
            "max_debate_rounds": body.max_debate_rounds or 1,
            "session_id": session_id,
            "attachments_context": data["session"].get("attachments_context") or "",
            "revision_comment": body.comment,
            "prior_messages": prior,
            "prior_verdict_version": version,
            "council_config": council,
            "actor": actor,
        }
    )
