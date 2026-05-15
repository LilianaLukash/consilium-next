"""Probe OpenRouter models with a 1-token chat; print OK / fail."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env")

KEY = os.getenv("OPENROUTER_API_KEY", "")
CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS_URL = "https://openrouter.ai/api/v1/models"
THRESHOLD = float(os.getenv("PROBE_PRICE_THRESHOLD", "10"))


def is_chat_capable(raw: dict) -> bool:
    arch = raw.get("architecture") or {}
    modality = (arch.get("modality") or "").lower()
    out_mod = (arch.get("output_modalities") or [])
    if isinstance(out_mod, list):
        outs = [str(x).lower() for x in out_mod]
    else:
        outs = [str(out_mod).lower()] if out_mod else []
    mid = (raw.get("id") or "").lower()
    block_sub = (
        "lyria",
        "image",
        "dall-e",
        "stable-diffusion",
        "flux",
        "embed",
        "whisper",
        "tts",
        "moderation",
    )
    if any(b in mid for b in block_sub):
        return False
    if outs and not any("text" in o for o in outs):
        return False
    if modality and "text" not in modality and "->text" not in modality:
        if not any("text" in o for o in outs):
            return False
    return True


def price_per_m(raw: dict) -> float:
    p = raw.get("pricing") or {}
    try:
        inp = float(p.get("prompt") or 0) * 1_000_000
        out = float(p.get("completion") or 0) * 1_000_000
        return max(inp, out)
    except (TypeError, ValueError):
        return 0.0


async def probe_one(client: httpx.AsyncClient, sem: asyncio.Semaphore, model_id: str) -> tuple[str, bool, str]:
    async with sem:
        try:
            r = await client.post(
                CHAT_URL,
                headers={
                    "Authorization": f"Bearer {KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": "Say: ok"}],
                    "max_tokens": 8,
                    "temperature": 0,
                },
                timeout=45.0,
            )
            if r.status_code == 200:
                return model_id, True, "ok"
            body = r.text[:200]
            try:
                err = r.json().get("error", {})
                if isinstance(err, dict) and err.get("message"):
                    body = str(err["message"])[:200]
            except Exception:
                pass
            return model_id, False, f"{r.status_code} {body}"
        except Exception as e:
            return model_id, False, str(e)[:120]


async def main() -> None:
    if not KEY:
        print("OPENROUTER_API_KEY missing", file=sys.stderr)
        sys.exit(1)

    async with httpx.AsyncClient() as client:
        r = await client.get(MODELS_URL, headers={"Authorization": f"Bearer {KEY}"}, timeout=60)
        r.raise_for_status()
        all_raw = r.json().get("data", [])

    candidates: list[str] = []
    for raw in all_raw:
        mid = raw.get("id") or ""
        if not mid or not is_chat_capable(raw):
            continue
        if price_per_m(raw) > THRESHOLD:
            continue
        if "deprecated" in mid.lower():
            continue
        candidates.append(mid)

    print(f"Probing {len(candidates)} chat models (price <= ${THRESHOLD}/M)...", flush=True)
    sem = asyncio.Semaphore(8)
    ok: list[str] = []
    bad: list[tuple[str, str]] = []

    async with httpx.AsyncClient() as client:
        tasks = [probe_one(client, sem, mid) for mid in candidates]
        for coro in asyncio.as_completed(tasks):
            mid, success, msg = await coro
            if success:
                ok.append(mid)
                print(f"  OK  {mid}")
            else:
                bad.append((mid, msg))
                print(f"  FAIL {mid}: {msg}")

    out_path = ROOT / "data" / "chat_models_verified.json"
    import json

    out_path.write_text(json.dumps({"ok": sorted(ok), "failed": bad}, indent=2), encoding="utf-8")
    print(f"\nOK: {len(ok)} / {len(candidates)} -> {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
