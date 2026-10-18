"""Integration helper: pass company info (structured or raw sources) into the layer.

Other navigator components should import from here rather than wiring DB details.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .engine import CompanyMatchEngine, CompanyMatchResult
from .handoff import export_handoff_from_sources
from .ingest import ingest_and_match

_engine: CompanyMatchEngine | None = None


def get_company_layer(db_path: str | None = None) -> CompanyMatchEngine:
    global _engine
    if _engine is None:
        _engine = CompanyMatchEngine(db_path=db_path)
    return _engine


def match_company_information(
    company_info: dict[str, Any],
    *,
    save: bool = False,
) -> dict[str, Any]:
    """Match an already-structured company dict."""
    result: CompanyMatchResult = get_company_layer().match_payload(
        company_info, persist_company=save
    )
    return result.to_dict()


def auto_search_companies(
    query: str = "",
    *,
    min_match_rate: float = 0.0,
    sector: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Automatic ranked search over the company database."""
    results = get_company_layer().search_companies(
        query=query,
        min_match_rate=min_match_rate,
        sector=sector,
        limit=limit,
    )
    return [r.to_dict() for r in results]


def ingest_company_sources(
    sources: str | Path | Iterable[str | Path] | None = None,
    *,
    text: str | None = None,
    files: Iterable[str | Path] | None = None,
    urls: Iterable[str] | None = None,
    save: bool = False,
    use_llm: bool = False,
) -> dict[str, Any]:
    """Sustainable multi-entry ingest: text / PDF / URL → extract → match.

    Examples
    --------
    ingest_company_sources(text="Company Name: Acme\\nCGM wearable...")
    ingest_company_sources(files=["pitch.pdf", "notes.txt"])
    ingest_company_sources(urls=["https://example.com/about"])
    ingest_company_sources(["a.pdf", "https://...", "plain text block"])
    """
    batch = ingest_and_match(
        sources,
        text=text,
        files=files,
        urls=urls,
        engine=get_company_layer(),
        save=save,
        use_llm=use_llm,
        match=True,
    )
    return batch.to_dict()


def teammate_match_queue(
    sources: str | Path | Iterable[str | Path] | None = None,
    *,
    text: str | None = None,
    files: Iterable[str | Path] | None = None,
    urls: Iterable[str] | None = None,
    use_llm: bool = False,
) -> list[dict[str, Any]]:
    """Ordered queue for the expertise-navigator teammate.

    Early-stage keyword hits (CGM / diabetes / biosensing) come first;
    mid/late keyword companies follow. Each row has `run_first` and `run_later` queries.
    """
    batch = ingest_and_match(
        sources,
        text=text,
        files=files,
        urls=urls,
        engine=get_company_layer(),
        save=False,
        use_llm=use_llm,
        match=True,
    )
    return batch.teammate_queue()


def export_for_teammate(
    sources: str | Path | Iterable[str | Path] | None = None,
    *,
    text: str | None = None,
    files: Iterable[str | Path] | None = None,
    urls: Iterable[str] | None = None,
    out_dir: str | Path | None = None,
    use_llm: bool = False,
) -> dict[str, Any]:
    """Write shared JSON/MD files. Teammate only reads files — no import needed."""
    return export_handoff_from_sources(
        sources,
        text=text,
        files=files,
        urls=urls,
        out_dir=out_dir,
        use_llm=use_llm,
    )
