"""List OpenRouter models for ideation roles."""
import asyncio
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()
KEY = os.getenv("OPENROUTER_API_KEY")
KEYWORDS = (
    "grok",
    "owl",
    "gemini-2",
    "llama",
    "mistral",
    "deepseek",
    "qwen",
    "hermes",
    "dolphin",
    "nemotron",
    "sonar",
    "perplexity",
)


async def main() -> None:
    if not KEY:
        print("No OPENROUTER_API_KEY", file=sys.stderr)
        sys.exit(1)
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {KEY}"},
        )
        r.raise_for_status()
        data = r.json()["data"]

    rows = []
    for m in data:
        mid = m.get("id", "")
        if not any(k in mid.lower() for k in KEYWORDS):
            continue
        p = m.get("pricing") or {}
        inp = float(p.get("prompt") or 0) * 1_000_000
        out = float(p.get("completion") or 0) * 1_000_000
        rows.append((inp + out, mid, m.get("context_length", 0), inp, out, m.get("name", "")))

    rows.sort(key=lambda x: x[0])
    print(f"{'model_id':<52} {'ctx':>8} {'$/M in':>8} {'$/M out':>8}  name")
    print("-" * 100)
    for _, mid, ctx, inp, out, name in rows:
        print(f"{mid:<52} {ctx:>8} {inp:>8.2f} {out:>8.2f}  {name[:45]}")


if __name__ == "__main__":
    asyncio.run(main())
