"""Minimal client for Apertus served behind an OpenAI-compatible /v1/chat/completions endpoint."""
import json
import re

import httpx

from . import config


class LLMUnavailable(RuntimeError):
    pass


def chat(system: str, user: str, max_tokens: int = 1500, temperature: float = 0.0) -> str:
    if not config.LLM_ENABLED:
        raise LLMUnavailable("LLM_BASE_URL is not set")
    url = config.LLM_BASE_URL.rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"} if config.LLM_API_KEY else {}
    body = {
        "model": config.LLM_NAME,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    r = httpx.post(url, json=body, headers=headers, timeout=180)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def chat_json(system: str, user: str, **kw) -> dict:
    """Ask for JSON and parse the first JSON object in the reply (tolerates code fences / prose)."""
    raw = chat(system + "\nRespond with a single valid JSON object and nothing else.", user, **kw)
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S)
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ValueError(f"No JSON in LLM reply: {raw[:200]}")
    return json.loads(m.group(0))
