"""Ingest pipeline: sources → extract → (optional) save → match.

Accepts one or many entries: plain text, PDF paths, website URLs, or mixed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .engine import CompanyMatchEngine, CompanyMatchResult
from .extractors import ExtractionResult, extract_from_sources, read_source
from .priority import sort_key_for_priority


@dataclass
class IngestItemResult:
    extraction: ExtractionResult
    match: CompanyMatchResult | None = None
    saved: bool = False
    errors: list[str] = field(default_factory=list)
    queue_position: int | None = None

    def to_dict(self) -> dict[str, Any]:
        in_scope = True
        if self.match is not None:
            in_scope = self.match.in_scope
        else:
            in_scope = bool(self.extraction.company.get("in_scope", True))
        m = self.match
        return {
            "domain": "life_science",
            "in_scope": in_scope,
            "queue_position": self.queue_position,
            "priority_rating": m.priority_rating if m else None,
            "priority_stage": m.priority_stage if m else None,
            "priority_score": m.priority_score if m else None,
            "early_keywords": m.early_keywords if m else [],
            "teammate_queries_early": m.teammate_queries_early if m else [],
            "teammate_queries_later": m.teammate_queries_later if m else [],
            "handoff_note": m.handoff_note if m else "",
            "extraction": self.extraction.to_dict(),
            "match": m.to_dict() if m else None,
            "saved": self.saved,
            "errors": self.errors,
            "match_rate": m.match_rate if m else None,
            "company_name": (m.company_name if m else self.extraction.company.get("name")),
            "reasons": m.reasons if m else [],
        }


@dataclass
class IngestBatchResult:
    items: list[IngestItemResult]
    source_count: int
    company_count: int
    domain: str = "life_science"
    qdrant_index: dict[str, Any] | None = None
    timings: dict[str, Any] | None = None

    def prioritized_items(self) -> list[IngestItemResult]:
        decorated = []
        for item in self.items:
            d = item.to_dict()
            decorated.append((sort_key_for_priority(d), item))
        decorated.sort(key=lambda x: x[0])
        ordered = [item for _, item in decorated]
        for idx, item in enumerate(ordered, 1):
            item.queue_position = idx
        return ordered

    def teammate_queue(self) -> list[dict[str, Any]]:
        """Compact ordered list for the expertise-navigator teammate."""
        queue = []
        for item in self.prioritized_items():
            if item.match and not item.match.in_scope:
                continue
            m = item.match
            name = m.company_name if m else item.extraction.company.get("name")
            queue.append(
                {
                    "queue_position": item.queue_position,
                    "company_name": name,
                    "priority_rating": m.priority_rating if m else "P4",
                    "priority_stage": m.priority_stage if m else "none",
                    "priority_score": m.priority_score if m else 0,
                    "match_rate": m.match_rate if m else 0,
                    "run_first": m.teammate_queries_early if m else [],
                    "run_later": m.teammate_queries_later if m else [],
                    "bern_units": m.bern_units if m else [],
                    "handoff_note": m.handoff_note if m else "",
                    "source_ref": item.extraction.source_ref,
                }
            )
        return queue

    def to_dict(self) -> dict[str, Any]:
        ordered = self.prioritized_items()
        in_scope_items = [
            i for i in ordered if (i.match.in_scope if i.match else i.extraction.company.get("in_scope", True))
        ]
        return {
            "domain": self.domain,
            "domain_label": "Life Science",
            "source_count": self.source_count,
            "company_count": self.company_count,
            "in_scope_count": len(in_scope_items),
            "out_of_scope_count": self.company_count - len(in_scope_items),
            "teammate_queue": self.teammate_queue(),
            "qdrant_index": self.qdrant_index,
            "timings": self.timings,
            "items": [i.to_dict() for i in ordered],
        }


def normalize_sources(
    sources: str | Path | Iterable[str | Path] | None = None,
    *,
    text: str | None = None,
    files: Iterable[str | Path] | None = None,
    urls: Iterable[str] | None = None,
) -> list[str | Path]:
    """Build a flat source list from mixed CLI/API inputs."""
    out: list[str | Path] = []
    if text and text.strip():
        out.append(text)
    if sources is not None:
        if isinstance(sources, (str, Path)):
            out.append(sources)
        else:
            out.extend(list(sources))
    if files:
        out.extend(list(files))
    if urls:
        out.extend(list(urls))
    # drop empties, preserve order
    cleaned: list[str | Path] = []
    for s in out:
        if s is None:
            continue
        if isinstance(s, str) and not s.strip():
            continue
        cleaned.append(s)
    return cleaned


def ingest_and_match(
    sources: str | Path | Iterable[str | Path] | None = None,
    *,
    text: str | None = None,
    files: Iterable[str | Path] | None = None,
    urls: Iterable[str] | None = None,
    engine: CompanyMatchEngine | None = None,
    save: bool = False,
    use_llm: bool = False,
    translate: bool = True,
    match: bool = True,
    index_qdrant: bool = False,
    allow_local_paths: bool = True,
) -> IngestBatchResult:
    """Sustainable entrypoint: read sources, extract companies, score Bern fit."""
    source_list = normalize_sources(sources, text=text, files=files, urls=urls)
    if not source_list:
        return IngestBatchResult(items=[], source_count=0, company_count=0)

    from . import budget

    # One time budget for the whole request (ANALYZE_BUDGET_S, default 80 s)
    own_budget = not budget.active()
    token = budget.start() if own_budget else None
    try:
        batch = _ingest_and_match(
            source_list, engine=engine, save=save, use_llm=use_llm, translate=translate,
            match=match, index_qdrant=index_qdrant, allow_local_paths=allow_local_paths,
        )
        batch.timings = budget.report()
        return batch
    finally:
        if token is not None:
            budget.reset(token)


def _ingest_and_match(
    source_list: list,
    *,
    engine: CompanyMatchEngine | None,
    save: bool,
    use_llm: bool,
    translate: bool,
    match: bool,
    index_qdrant: bool,
    allow_local_paths: bool,
) -> IngestBatchResult:

    owns_engine = engine is None
    engine = engine or CompanyMatchEngine()

    extractions = extract_from_sources(
        source_list, use_llm=use_llm, translate=translate, allow_local_paths=allow_local_paths
    )
    items: list[IngestItemResult] = []

    for ext in extractions:
        item = IngestItemResult(extraction=ext)
        try:
            if match:
                result = engine.match_payload(ext.company, persist_company=save)
                item.match = result
                item.saved = save
            elif save:
                engine.match_payload(ext.company, persist_company=True)
                item.saved = True
        except Exception as exc:  # keep batch resilient
            item.errors.append(str(exc))
        items.append(item)

    batch = IngestBatchResult(
        items=items,
        source_count=len(source_list),
        company_count=len(items),
    )
    # Assign queue positions (early keywords / P1 first)
    batch.prioritized_items()

    if index_qdrant:
        try:
            from .vectorstore import index_ingest_batch

            batch.qdrant_index = index_ingest_batch(batch.items)
        except Exception as exc:
            batch.qdrant_index = {"error": str(exc), "indexed": 0}

    if owns_engine:
        engine.close()
    return batch


def preview_source(source: str | Path) -> dict[str, Any]:
    """Debug helper: show what the reader pulled from a source."""
    doc = read_source(source, inline_text=True)
    data = doc.to_dict()
    data["text_preview"] = (doc.text or "")[:1200]
    data["char_count"] = len(doc.text or "")
    return data
