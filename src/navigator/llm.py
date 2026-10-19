"""Minimal client for Apertus served behind an OpenAI-compatible /v1/chat/completions endpoint."""
import json
import re

import httpx

from . import config


class LLMUnavailable(RuntimeError):
    pass


class InvalidModelResponse(ValueError):
    """A response is empty, truncated, or violates the requested JSON syntax."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidModelResponse("Duplicate key in structured response")
        result[key] = value
    return result


def _invalid_constant(value):
    raise InvalidModelResponse("Non-JSON number in structured response")


def chat(system: str, user: str, max_tokens: int = 1500, temperature: float = 0.0,
         json_schema: dict | None = None, model: str | None = None) -> str:
    if not config.LLM_ENABLED:
        raise LLMUnavailable("LLM_BASE_URL is not set")
    url = config.LLM_BASE_URL.rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"} if config.LLM_API_KEY else {}
    body = {
        "model": model or config.LLM_NAME,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_schema is not None:
        body["response_format"] = {"type": "json_schema", "json_schema": {
            "name": "response", "strict": True, "schema": json_schema}}
    r = httpx.post(url, json=body, headers=headers, timeout=180)
    r.raise_for_status()
    choice = r.json()["choices"][0]
    if json_schema is not None and choice.get("finish_reason") != "stop":
        raise InvalidModelResponse("Structured response did not finish normally")
    content = choice["message"]["content"]
    if not isinstance(content, str) or not content.strip():
        raise InvalidModelResponse("Empty model response")
    return content


def chat_json(system: str, user: str, **kw) -> dict:
    """Strictly parse schema-bound JSON; tolerate surrounding prose only for legacy calls."""
    raw = chat(system + "\nRespond with a single valid JSON object and nothing else.", user, **kw)
    if kw.get("json_schema") is not None:
        # Structured calls never salvage incomplete objects or rewrite their facts.
        try:
            result = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
        except json.JSONDecodeError as error:
            raise InvalidModelResponse("Structured response is not valid JSON") from error
        if not isinstance(result, dict):
            raise InvalidModelResponse("Structured response must be a JSON object")
        return result
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S)
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ValueError(f"No JSON in LLM reply: {raw[:200]}")
    return json.loads(m.group(0))
