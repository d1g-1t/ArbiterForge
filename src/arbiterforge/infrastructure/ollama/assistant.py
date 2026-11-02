from __future__ import annotations

from functools import cache
from pathlib import Path

import httpx

from arbiterforge.core.config import get_settings

PROMPT_PATH = Path(__file__).with_name("po_summary_prompt.txt")
FALLBACK_PREFIX = "[ЧЕРНОВИК — требует проверки человеком] "


@cache
def system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def fallback_summary(gist: str) -> str:
    text = gist.strip()
    return FALLBACK_PREFIX + text[:280] + ("…" if len(text) > 280 else "")


async def request_summary(gist: str, *, client: httpx.AsyncClient | None = None) -> str:
    settings = get_settings()
    body = {
        "model": settings.ollama_model,
        "stream": False,
        "options": {"temperature": 0.2},
        "messages": [
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": gist},
        ],
    }
    owns = client is None
    http = client or httpx.AsyncClient(
        base_url=settings.ollama_base_url, timeout=settings.ollama_timeout_seconds
    )
    try:
        response = await http.post("/api/chat", json=body)
        response.raise_for_status()
        content = str(response.json()["message"]["content"]).strip()
    finally:
        if owns:
            await http.aclose()
    if not content:
        raise ValueError("Empty model response")
    return FALLBACK_PREFIX + content


async def draft_procedural_order_summary(
    gist: str, *, client: httpx.AsyncClient | None = None
) -> str:
    try:
        return await request_summary(gist, client=client)
    except (httpx.HTTPError, KeyError, ValueError):
        return fallback_summary(gist)
