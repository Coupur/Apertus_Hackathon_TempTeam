"""Per-request time budget + step timings.

Every network / LLM call asks ``clamp(timeout)`` for how long it may wait, so one
analysis can never exceed the budget (default ``ANALYZE_BUDGET_S=80``; the UI waits 90 s, the proxy
gives up at 180 s). Optional steps check ``has(seconds)`` and are skipped — with a
note — when time is short.

Also tracks: an LLM time-out "circuit" (Ollama serves one request at a time; after a
time-out the model is still busy, so further calls in this request would just queue),
and per-step timings that the API returns to the UI.

Uses ``contextvars`` so concurrent API requests don't share a budget.
``asyncio.to_thread`` copies the context automatically; for thread pools use ``wrap()``.
"""

from __future__ import annotations

import contextvars
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator


@dataclass
class _Budget:
    deadline: float
    started: float
    timings: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    llm_dead: bool = False
    llm_mode: str = "lite"  # off | lite | deep


_current: contextvars.ContextVar[_Budget | None] = contextvars.ContextVar("cm_budget", default=None)


def default_seconds() -> float:
    try:
        return float(os.getenv("ANALYZE_BUDGET_S") or "25")
    except ValueError:
        return 25.0


def start(seconds: float | None = None, llm_mode: str = "lite") -> contextvars.Token:
    now = time.monotonic()
    return _current.set(
        _Budget(deadline=now + (seconds or default_seconds()), started=now, llm_mode=llm_mode)
    )


def reset(token: contextvars.Token) -> None:
    _current.reset(token)


@contextmanager
def budget(seconds: float | None = None, llm_mode: str = "lite") -> Iterator[None]:
    tok = start(seconds, llm_mode)
    try:
        yield
    finally:
        reset(tok)


def active() -> bool:
    return _current.get() is not None


def remaining() -> float:
    b = _current.get()
    if b is None:
        return float("inf")
    return max(0.0, b.deadline - time.monotonic())


def has(seconds: float) -> bool:
    return remaining() >= seconds


def clamp(timeout: float, *, reserve: float = 1.0, floor: float = 1.0) -> float:
    """Timeout limited to what is left of the budget (minus a small reserve)."""
    left = remaining() - reserve
    return max(floor, min(timeout, left)) if left != float("inf") else timeout


def note(msg: str) -> None:
    b = _current.get()
    if b is not None and msg not in b.notes:
        b.notes.append(msg)


def mark_llm_dead(reason: str) -> None:
    b = _current.get()
    if b is not None:
        b.llm_dead = True
        note(reason)


def llm_mode() -> str:
    """off = no LLM calls at all (instant mode) · lite = one fast call · deep = full profile."""
    b = _current.get()
    return b.llm_mode if b is not None else "lite"


def llm_dead() -> bool:
    b = _current.get()
    return bool(b and b.llm_dead)


@contextmanager
def step(name: str) -> Iterator[None]:
    t = time.monotonic()
    try:
        yield
    finally:
        b = _current.get()
        if b is not None:
            b.timings[name] = round(b.timings.get(name, 0.0) + time.monotonic() - t, 2)


def report() -> dict[str, Any]:
    b = _current.get()
    if b is None:
        return {}
    return {
        "total_s": round(time.monotonic() - b.started, 2),
        "budget_s": round(b.deadline - b.started, 1),
        "steps_s": dict(b.timings),
        "notes": list(b.notes),
        "llm_mode": b.llm_mode,
    }


def wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Run ``fn`` in the caller's context (for ThreadPoolExecutor.submit)."""
    ctx = contextvars.copy_context()
    return lambda *a, **k: ctx.run(fn, *a, **k)
