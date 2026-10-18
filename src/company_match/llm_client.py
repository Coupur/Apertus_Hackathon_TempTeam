"""Single LLM provider layer for the company pipeline (profile, summary, translation).

Providers (``LLM_PROVIDER`` = auto | apertus | ollama | kimi; default auto):

* ``apertus`` — OpenAI-compatible endpoint from LLM_NAME / LLM_BASE_URL / LLM_API_KEY
  (the challenge's required model family).
* ``ollama``  — the local Ollama app at OLLAMA_HOST (default http://localhost:11434).
  **No API key in this project.** Prefers a **local** (free) model already pulled
  (e.g. ``qwen2.5:7b``). Cloud models like ``kimi-k2.6:cloud`` need Ollama credits;
  on HTTP 402/429 we automatically retry with a local model.
* ``kimi``    — Moonshot API with KIMI_API_KEY / MOONSHOT_API_KEY.

``auto`` picks the first available: apertus (if LLM_* set) → ollama (if the app answers)
→ kimi (if a key is set).

Thinking models: the reasoning trace is discarded; only the final answer is returned.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

OLLAMA_DEFAULT_HOST = "http://localhost:11434"
# Prefer a free local model. Cloud Kimi needs paid Ollama usage.
# Speed target: AI refinement < 10 s on a laptop → 3B model by default
OLLAMA_DEFAULT_MODEL = "qwen2.5:3b"
OLLAMA_LOCAL_FALLBACKS = (
    "qwen2.5:3b",
    "qwen2.5:7b",
    "qwen2.5:latest",
    "llama3.2:latest",
    "llama3.1:8b",
    "deepseek-r1:7b",
    "deepseek-r1:latest",
    "mistral:latest",
    "gemma2:9b",
)
KIMI_DEFAULT_BASE = "https://api.moonshot.ai/v1"
KIMI_DEFAULT_MODEL = "kimi-k2.6"

_ollama_probe: tuple[float, bool] = (0.0, False)
_ollama_tags_cache: tuple[float, list[str]] = (0.0, [])
_ollama_active_model: str | None = None  # sticky after a successful call / fallback
_kimi_circuit_open = False


def _env_on(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() not in {"0", "false", "off", "no", ""}


def _apertus_configured() -> bool:
    return bool(os.getenv("LLM_BASE_URL") and os.getenv("LLM_API_KEY") and os.getenv("LLM_NAME"))


def _kimi_key() -> str:
    return os.getenv("KIMI_API_KEY") or os.getenv("MOONSHOT_API_KEY") or ""


def ollama_host() -> str:
    host = (os.getenv("OLLAMA_HOST") or OLLAMA_DEFAULT_HOST).rstrip("/")
    return host if host.startswith("http") else f"http://{host}"


def _is_cloud_model(name: str) -> bool:
    return ":cloud" in (name or "").lower() or (name or "").endswith("-cloud")


def list_ollama_models(force: bool = False) -> list[str]:
    """Installed model names from the local Ollama app."""
    global _ollama_tags_cache
    ts, cached = _ollama_tags_cache
    if not force and cached and time.time() - ts < 120:
        return cached
    names: list[str] = []
    try:
        with urllib.request.urlopen(f"{ollama_host()}/api/tags", timeout=2.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for m in data.get("models") or []:
            n = str(m.get("name") or "").strip()
            if n:
                names.append(n)
    except Exception:
        names = list(cached)
    _ollama_tags_cache = (time.time(), names)
    return names


def _pick_local_model(available: list[str] | None = None) -> str | None:
    avail = available if available is not None else list_ollama_models()
    if not avail:
        return None
    lower_map = {a.lower(): a for a in avail}
    for cand in OLLAMA_LOCAL_FALLBACKS:
        if cand.lower() in lower_map:
            return lower_map[cand.lower()]
        # allow prefix match e.g. qwen2.5:7b-instruct
        for a in avail:
            if a.lower().startswith(cand.split(":")[0].lower()) and not _is_cloud_model(a):
                return a
    for a in avail:
        if not _is_cloud_model(a):
            return a
    return None


def ollama_model() -> str:
    """Model used for Ollama calls — prefers free local over paid cloud."""
    global _ollama_active_model
    if _ollama_active_model:
        return _ollama_active_model
    explicit = (os.getenv("OLLAMA_MODEL") or "").strip()
    if explicit and not _is_cloud_model(explicit):
        return explicit
    local = _pick_local_model()
    if local:
        return local
    if explicit:
        return explicit
    return OLLAMA_DEFAULT_MODEL


def ollama_available(force: bool = False) -> bool:
    """Is the Ollama app answering? Cached for 60 s (cheap 1.5 s probe)."""
    global _ollama_probe
    ts, ok = _ollama_probe
    if not force and time.time() - ts < 60:
        return ok
    try:
        with urllib.request.urlopen(f"{ollama_host()}/api/version", timeout=1.5) as resp:
            ok = resp.status == 200
    except Exception:
        ok = False
    _ollama_probe = (time.time(), ok)
    return ok


def resolve_provider() -> str | None:
    """Return 'apertus' | 'ollama' | 'kimi' | None."""
    choice = (os.getenv("LLM_PROVIDER") or "auto").strip().lower()
    if choice == "apertus":
        return "apertus" if _apertus_configured() else None
    if choice == "ollama":
        return "ollama"  # explicit: call it and report the error if the app is down
    if choice == "kimi":
        return "kimi" if _kimi_key() else None
    if _apertus_configured():
        return "apertus"
    if ollama_available():
        return "ollama"
    if _kimi_key() and not _kimi_circuit_open:
        return "kimi"
    return None


def model_label(provider: str | None = None) -> str:
    provider = provider or resolve_provider()
    if provider == "apertus":
        return f"apertus:{os.getenv('LLM_NAME')}"
    if provider == "ollama":
        return f"ollama:{ollama_model()}"
    if provider == "kimi":
        return os.getenv("KIMI_MODEL") or KIMI_DEFAULT_MODEL
    return "rules"


def configured() -> bool:
    return resolve_provider() is not None


def _strip_thinking(text: str) -> str:
    text = re.sub(r"(?is)<think>.*?</think>", "", text or "")
    text = re.sub(r"(?is)^.*?</think>", "", text)  # unterminated opening tag
    return text.strip()


def _post(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _ollama_chat_once(
    model: str,
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    temperature: float,
    json_mode: bool,
    timeout: float,
) -> tuple[str | None, list[str]]:
    """Single Ollama /api/chat attempt. Returns (content, warnings)."""
    think = _env_on("OLLAMA_THINK", "0" if not _is_cloud_model(model) else "1")
    # Local small models: keep think off for speed / JSON reliability
    if not _is_cloud_model(model):
        think = _env_on("OLLAMA_THINK", "0")
    # Ollama's default context is 2048 tokens and it silently drops the start of longer
    # prompts (system prompt + schema!). Size the window to the prompt instead.
    prompt_chars = sum(len(m.get("content") or "") for m in messages)
    need = int(prompt_chars / 3.2) + max_tokens + 256
    num_ctx = 4096 if need <= 4096 else 8192 if need <= 8192 else 16384
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": think,
        # keep the model in memory between calls (cold load of a 7B model = 5–20 s)
        "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
        "options": {
            "temperature": temperature,
            "num_ctx": int(os.getenv("OLLAMA_NUM_CTX") or num_ctx),
            "num_predict": max_tokens + (
                int(os.getenv("OLLAMA_THINK_BUDGET", "6000")) if think else 0
            ),
        },
    }
    if json_mode:
        payload["format"] = "json"
    try:
        body = _post(f"{ollama_host()}/api/chat", payload, {}, timeout)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:400]
        if exc.code == 400 and "think" in detail.lower():
            payload.pop("think", None)
            body = _post(f"{ollama_host()}/api/chat", payload, {}, timeout)
        else:
            return None, [f"Ollama HTTP {exc.code}: {detail or exc.reason}"]
    msg = body.get("message") or {}
    return _strip_thinking(str(msg.get("content") or "")), []


_CACHE_DIR = Path(__file__).resolve().parent / "data" / "llm_cache" / "calls"
MIN_LLM_SECONDS = 8.0  # don't start an LLM call with less budget than this


def _cache_key(provider: str, messages: list[dict[str, str]], max_tokens: int, json_mode: bool) -> Path:
    raw = json.dumps(
        [provider, model_label(provider), messages, max_tokens, json_mode], ensure_ascii=False
    )
    return _CACHE_DIR / (hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32] + ".json")


def chat(
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 900,
    temperature: float = 0.1,
    json_mode: bool = False,
    timeout: float | None = None,
) -> tuple[str | None, str, list[str]]:
    """Budget-aware + cached LLM call. Returns (answer_text, model_label, warnings)."""
    from . import budget

    if budget.llm_mode() == "off":
        return None, "", ["LLM skipped: instant mode (AI refinement runs separately)."]
    provider = resolve_provider()
    if provider is None:
        return _chat_uncached(messages, max_tokens=max_tokens, temperature=temperature,
                              json_mode=json_mode, timeout=timeout)
    use_cache = _env_on("LLM_CACHE", "1")
    cache = _cache_key(provider, messages, max_tokens, json_mode)
    if use_cache and cache.is_file():
        try:
            hit = json.loads(cache.read_text(encoding="utf-8"))
            budget.note("LLM answer served from cache.")
            return hit["content"], hit["label"], []
        except (OSError, json.JSONDecodeError, KeyError):
            pass
    if budget.llm_dead():
        return None, model_label(provider), ["LLM skipped: an earlier call in this request timed out."]
    if not budget.has(MIN_LLM_SECONDS):
        msg = f"LLM skipped: time budget nearly used ({budget.remaining():.0f}s left)."
        budget.note(msg)
        return None, model_label(provider), [msg]
    default_t = float(os.getenv("OLLAMA_TIMEOUT_S" if provider == "ollama" else "LLM_TIMEOUT_S") or "120")
    t = budget.clamp(timeout or default_t)
    with budget.step("llm"):
        content, label, warns = _chat_uncached(
            messages, max_tokens=max_tokens, temperature=temperature, json_mode=json_mode, timeout=t
        )
    blob = " ".join(warns).lower()
    if content is None and ("timed out" in blob or "timeout" in blob):
        budget.mark_llm_dead(
            f"LLM timed out after {t:.0f}s — skipped further LLM calls in this request "
            "(a busy Ollama model would only queue them). Try a smaller model or OLLAMA_THINK=0."
        )
    if content and use_cache:
        try:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"content": content, "label": label}, ensure_ascii=False),
                             encoding="utf-8")
        except OSError:
            pass
    return content, label, warns


def _chat_uncached(
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 900,
    temperature: float = 0.1,
    json_mode: bool = False,
    timeout: float | None = None,
) -> tuple[str | None, str, list[str]]:
    """Return (answer_text, model_label, warnings). answer_text is None on failure."""
    global _kimi_circuit_open, _ollama_active_model
    provider = resolve_provider()
    if provider is None:
        return None, "", [
            "No LLM available: start the Ollama app and pull a local model "
            f"(e.g. `ollama pull {OLLAMA_DEFAULT_MODEL}`), or set LLM_NAME / "
            "LLM_BASE_URL / LLM_API_KEY (Apertus)."
        ]
    label = model_label(provider)
    try:
        if provider == "ollama":
            t = timeout or float(os.getenv("OLLAMA_TIMEOUT_S") or "300")
            primary = ollama_model()
            content, warns = _ollama_chat_once(
                primary,
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                json_mode=json_mode,
                timeout=t,
            )
            if content:
                _ollama_active_model = primary
                return content, f"ollama:{primary}", []

            # Cloud credit / auth failure → automatic free local retry
            blob = " ".join(warns).lower()
            need_local = any(
                x in blob
                for x in (
                    "402",
                    "429",
                    "insufficient",
                    "usage credits",
                    "not included in your free",
                    "pay as you go",
                    "quota",
                )
            )
            from . import budget as _b

            if (need_local or _is_cloud_model(primary)) and not any(
                "timed out" in w.lower() for w in warns
            ) and _b.has(MIN_LLM_SECONDS):
                local = _pick_local_model()
                if local and local != primary:
                    t = _b.clamp(t)
                    content2, warns2 = _ollama_chat_once(
                        local,
                        messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        json_mode=json_mode,
                        timeout=t,
                    )
                    if content2:
                        _ollama_active_model = local
                        return content2, f"ollama:{local}", [
                            f"Switched to free local model {local} "
                            f"(cloud model {primary} needs Ollama credits)."
                        ]
                    return None, f"ollama:{local}", warns + warns2
            return None, label, warns

        if provider == "apertus":
            base, key, model = os.environ["LLM_BASE_URL"], os.environ["LLM_API_KEY"], os.environ["LLM_NAME"]
            extra: dict[str, Any] = {}
        else:
            base = os.getenv("KIMI_BASE_URL") or KIMI_DEFAULT_BASE
            key, model = _kimi_key(), os.getenv("KIMI_MODEL") or KIMI_DEFAULT_MODEL
            # Moonshot k2.6: disable thinking by default (faster + JSON-friendly)
            extra = (
                {"thinking": {"type": "enabled"}}
                if _env_on("KIMI_THINK", "0")
                else {"thinking": {"type": "disabled"}}
            )
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **extra,
        }
        t = timeout or float(os.getenv("LLM_TIMEOUT_S") or "120")
        try:
            body = _post(
                base.rstrip("/") + "/chat/completions",
                payload,
                {"Authorization": f"Bearer {key}"},
                t,
            )
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:300]
            if provider == "kimi" and exc.code in {401, 402, 403, 429}:
                _kimi_circuit_open = True
            return None, label, [f"{provider} HTTP {exc.code}: {detail or exc.reason}"]
        content = body["choices"][0]["message"].get("content")
        if isinstance(content, list):
            content = " ".join(
                str(p.get("text") or "") if isinstance(p, dict) else str(p) for p in content
            )
        return _strip_thinking(str(content or "")), label, []
    except Exception as exc:
        hint = ""
        if provider == "ollama":
            hint = f" — is the Ollama app running at {ollama_host()}?"
        return None, label, [f"{provider} call failed: {exc}{hint}"]


def status() -> dict[str, Any]:
    """For /health: which provider would be used and why."""
    prov = resolve_provider()
    models = list_ollama_models(force=True) if ollama_available(force=True) else []
    return {
        "provider": prov,
        "model": model_label(prov),
        "apertus_configured": _apertus_configured(),
        "ollama_host": ollama_host(),
        "ollama_available": ollama_available(force=True),
        "ollama_model": ollama_model(),
        "ollama_models_installed": models[:20],
        "ollama_local_pick": _pick_local_model(models),
        "kimi_key_present": bool(_kimi_key()),
        "selection": os.getenv("LLM_PROVIDER") or "auto",
    }


def ensure_ollama_model_ready() -> dict[str, Any]:
    """Startup helper: pull the default model if missing, then load it into memory.

    Pull runs only when OLLAMA_AUTO_PULL != 0 (default on, ~2 GB for qwen2.5:3b, one time).
    Warm-up makes the first real request fast (cold load of a model costs 5-20 s).
    """
    info: dict[str, Any] = {"available": ollama_available(force=True)}
    if not info["available"]:
        return info
    want = (os.getenv("OLLAMA_MODEL") or OLLAMA_DEFAULT_MODEL).strip()
    installed = [m.lower() for m in list_ollama_models(force=True)]
    info["model"] = want
    if not _is_cloud_model(want) and want.lower() not in installed and want.lower() + ":latest" not in installed:
        if _env_on("OLLAMA_AUTO_PULL", "1"):
            try:
                _post(f"{ollama_host()}/api/pull", {"model": want, "stream": False}, {}, 1800)
                info["pulled"] = True
                list_ollama_models(force=True)
            except Exception as exc:
                info["pull_error"] = str(exc)
        else:
            info["missing"] = True
    try:
        t = time.time()
        _post(
            f"{ollama_host()}/api/generate",
            {"model": ollama_model(), "prompt": "", "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m")},
            {},
            120,
        )
        info["warmed_s"] = round(time.time() - t, 1)
    except Exception as exc:
        info["warm_error"] = str(exc)
    return info
