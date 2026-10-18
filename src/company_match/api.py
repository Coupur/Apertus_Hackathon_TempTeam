"""HTTP API for the company matching layer (+ React UI backend).

Run:
  uvicorn company_match.api:app --app-dir src --reload --port 8088
"""

from __future__ import annotations

import os

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .engine import CompanyMatchEngine
from .handoff import write_handoff
from .ingest import ingest_and_match

app = FastAPI(
    title="Bern Company Match Layer (Life Science)",
    description=(
        "Life-science domain only. Ingest company information from text, PDF, or website URLs; "
        "extract fields automatically; match against Canton of Bern life-science expertise "
        "(UniBE / ARTORG / Diabetes Center Berne). Non-life-science inputs are returned out of scope."
    ),
    version="0.3.0",
)

_MODEL_READY: dict[str, Any] = {"status": "starting"}


@app.on_event("startup")
def _warm_llm() -> None:
    """Pull (if missing) + pre-load the Ollama model in the background, so the first
    AI refinement isn't slowed by a 5-20 s cold model load."""
    import threading

    def _run() -> None:
        from . import llm_client
        from .kimi_summary import _load_dotenv

        _load_dotenv()
        try:
            if llm_client.resolve_provider() == "ollama":
                _MODEL_READY.update(llm_client.ensure_ollama_model_ready(), status="ready")
            else:
                _MODEL_READY.update(status="not-ollama")
        except Exception as exc:  # never block startup
            _MODEL_READY.update(status="error", error=str(exc))

    threading.Thread(target=_run, daemon=True).start()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_engine: CompanyMatchEngine | None = None


def get_engine() -> CompanyMatchEngine:
    global _engine
    if _engine is None:
        _engine = CompanyMatchEngine()
    return _engine


class CompanyPayload(BaseModel):
    name: str | None = None
    id: str | None = None
    sector: str | None = None
    subsector: str | None = None
    description: str | None = None
    information: str | None = Field(default=None, description="Free-text company info")
    keywords: list[str] | str | None = None
    needs: list[str] | str | None = None
    hq_country: str | None = None
    hq_city: str | None = None
    canton_bern_presence: bool = False
    website: str | None = None
    size: str | None = None
    save: bool = False


class IngestPayload(BaseModel):
    text: str | None = Field(default=None, description="Plain text; may contain multiple companies")
    urls: list[str] = Field(default_factory=list)
    files: list[str] = Field(
        default_factory=list,
        description="Server-local paths — only honoured when ALLOW_LOCAL_PATHS=1 (dev). Use /ingest/upload.",
    )
    sources: list[str] = Field(default_factory=list, description="Mixed paths/URLs/text snippets")
    save: bool = False
    use_llm: bool = False
    extract_only: bool = False
    write_handoff: bool = False


def _pipeline_steps() -> list[dict[str, str]]:
    """Layer-view steps; LLM label follows the active provider (Ollama / Apertus / Kimi)."""
    from .kimi_summary import summary_model_label

    try:
        model = summary_model_label()
    except Exception:
        model = "local LLM"
    if model.startswith("ollama:"):
        llm_label, llm_detail = "LLM summary", f"{model} on page/search context"
    elif model.startswith("apertus:"):
        llm_label, llm_detail = "Apertus summary", f"{model} on page/search context"
    elif model and model != "rules":
        llm_label, llm_detail = "LLM summary", f"{model} on page/search context"
    else:
        llm_label, llm_detail = "LLM summary", "Optional — Ollama / Apertus when configured"
    return [
        {"id": "ingest", "label": "Ingest", "detail": "PDF / text / website (any language)"},
        {"id": "translate", "label": "Translate", "detail": "→ English (bridge / Apertus)"},
        {"id": "web", "label": "Web enrich", "detail": "Search by company name → context + keywords"},
        {"id": "llm", "label": llm_label, "detail": llm_detail},
        {"id": "extract", "label": "Extract", "detail": "Basics from website / PDF / text"},
        {"id": "priority", "label": "Prioritize", "detail": "Semantic frequency → early front"},
        {"id": "match", "label": "Match", "detail": "Collaboration potential % + judge verdict"},
        {"id": "qdrant", "label": "Qdrant", "detail": "Later-stage vector index"},
        {"id": "handoff", "label": "Handoff", "detail": "Queries for navigator teammate"},
    ]


def _ui_view(batch_dict: dict[str, Any]) -> dict[str, Any]:
    """Shape batch output for the React company layer view."""
    cards = []
    for item in batch_dict.get("items") or []:
        ext = item.get("extraction") or {}
        company = (ext.get("company") or {})
        match = item.get("match") or {}
        cards.append(
            {
                "queue_position": item.get("queue_position"),
                "company_name": item.get("company_name") or company.get("name"),
                "in_scope": item.get("in_scope", True),
                "source_type": ext.get("source_type"),
                "source_ref": ext.get("source_ref"),
                "extraction_confidence": ext.get("confidence"),
                "extraction_method": ext.get("method"),
                "main_info": {
                    "name": company.get("name"),
                    "sector": company.get("sector"),
                    "subsector": company.get("subsector"),
                    "description": company.get("description"),
                    "what_they_do": company.get("what_they_do")
                    or match.get("activity_summary")
                    or "",
                    "needs": company.get("needs") or [],
                    "website": company.get("website"),
                    "hq_city": company.get("hq_city"),
                    "hq_country": company.get("hq_country"),
                    "canton_bern_presence": company.get("canton_bern_presence"),
                    "meta_title": company.get("meta_title"),
                    "meta_description": company.get("meta_description"),
                    "source_language": company.get("source_language") or "en",
                    "translated_to_english": bool(company.get("translated_to_english")),
                    "translation_method": company.get("translation_method") or "identity",
                    "original_excerpt": company.get("original_excerpt") or "",
                    "summary_method": company.get("summary_method")
                    or (
                        "llm"
                        if ext.get("method") in {"llm-summary", "kimi-summary"}
                        else "rules"
                    ),
                    "web_enrich_method": company.get("web_enrich_method") or "",
                    "web_sources": company.get("web_sources") or [],
                    "focus_label": company.get("focus_label"),
                    "hq_source": company.get("hq_source"),
                    "bern_sites": company.get("bern_sites") or [],
                    "pipeline_notes": [
                        w for w in (ext.get("warnings") or [])
                        if any(k in w.lower() for k in ("llm", "apertus", "kimi", "profile", "hq ", "http"))
                    ],
                    "medical_profile": company.get("medical_profile"),
                },
                "keywords": {
                    "all": company.get("keywords") or [],
                    "early": item.get("early_keywords") or match.get("early_keywords") or [],
                    "mid": match.get("mid_keywords") or [],
                    "late": match.get("late_keywords") or [],
                    "early_relevance": match.get("early_relevance") or [],
                    "mid_relevance": match.get("mid_relevance") or [],
                    "late_relevance": match.get("late_relevance") or [],
                },
                "semantics": {
                    "activity_summary": match.get("activity_summary")
                    or company.get("what_they_do")
                    or "",
                    "focus_clusters": match.get("focus_clusters")
                    or (company.get("semantic_profile") or {}).get("focus_clusters")
                    or [],
                },
                "priority": {
                    "rating": item.get("priority_rating") or match.get("priority_rating"),
                    "stage": item.get("priority_stage") or match.get("priority_stage"),
                    "score": item.get("priority_score") or match.get("priority_score"),
                    "handoff_note": item.get("handoff_note") or match.get("handoff_note"),
                },
                "match": {
                    "match_rate": item.get("match_rate") or match.get("match_rate"),
                    "tier": match.get("tier"),
                    "verdict": (match.get("score_breakdown") or {}).get("verdict")
                    or ((match.get("score_breakdown") or {}).get("details") or {}).get("verdict"),
                    "verdict_label": (match.get("score_breakdown") or {}).get("verdict_label")
                    or ((match.get("score_breakdown") or {}).get("details") or {}).get("verdict_label")
                    or match.get("tier"),
                    "reasons": item.get("reasons") or match.get("reasons") or [],
                    "score_breakdown": match.get("score_breakdown") or {},
                    "reasoning": match.get("reasoning") or {},
                    "bern_units": match.get("bern_units") or [],
                    "economic_hooks": match.get("economic_hooks") or [],
                    "capability_matches": match.get("capability_matches") or [],
                    "bern_matches": match.get("bern_matches") or [],
                },
                "teammate_layer": {
                    "run_first": item.get("teammate_queries_early")
                    or match.get("teammate_queries_early")
                    or [],
                    "run_later": item.get("teammate_queries_later")
                    or match.get("teammate_queries_later")
                    or [],
                    "suggested_queries": match.get("suggested_queries") or [],
                },
                "warnings": ext.get("warnings") or [],
            }
        )

    return {
        "domain": batch_dict.get("domain", "life_science"),
        "domain_label": batch_dict.get("domain_label", "Life Science"),
        "source_count": batch_dict.get("source_count", 0),
        "company_count": batch_dict.get("company_count", 0),
        "timings": batch_dict.get("timings") or {},
        "in_scope_count": batch_dict.get("in_scope_count", 0),
        "out_of_scope_count": batch_dict.get("out_of_scope_count", 0),
        "pipeline": _pipeline_steps(),
        "teammate_queue": batch_dict.get("teammate_queue") or [],
        "qdrant_index": batch_dict.get("qdrant_index"),
        "cards": cards,
        "raw": batch_dict,
    }


@app.get("/health")
def health() -> dict[str, Any]:
    from . import llm_client
    from .kimi_summary import kimi_configured, summary_model_label

    return {
        "status": "ok",
        "layer": "company_match",
        "kimi_configured": kimi_configured(),  # any summary LLM available
        "summary_model": summary_model_label(),
        "llm": llm_client.status(),
        "llm_warmup": _MODEL_READY,
    }


@app.get("/bern/records/status")
def bern_records_status() -> dict[str, Any]:
    """What teammate Bern records are loaded (data/bern_records/ or $BERN_RECORDS_PATH)."""
    from .bern_records import get_records

    rs = get_records()
    by_type: dict[str, int] = {}
    for r in rs.records:
        by_type[r["type"]] = by_type.get(r["type"], 0) + 1
    return {
        "loaded": len(rs.records),
        "files": [Path(f).name for f in rs.files],
        "by_type": by_type,
        "issues": [
            {"file": Path(i.file).name, "index": i.index, "problem": i.problem} for i in rs.issues[:100]
        ],
    }


@app.get("/companies")
def list_companies() -> list[dict[str, Any]]:
    return get_engine().list_companies()


@app.get("/search")
def search_companies(
    q: str = Query(default="", description="Keyword / sector / company text"),
    min_rate: float = Query(default=0.0, ge=0, le=100),
    sector: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, Any]]:
    results = get_engine().search_companies(
        query=q, min_match_rate=min_rate, sector=sector, limit=limit
    )
    return [r.to_dict() for r in results]


@app.get("/match/{company_id}")
def match_existing(company_id: str) -> dict[str, Any]:
    result = get_engine().match_by_id(company_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Company not found: {company_id}")
    return result.to_dict()


@app.post("/match")
def match_company_info(payload: CompanyPayload) -> dict[str, Any]:
    """Pass structured company information; returns match_rate + reasons."""
    data = payload.model_dump(exclude={"save"})
    if data.get("information") and not data.get("description"):
        data["description"] = data["information"]
    result = get_engine().match_payload(data, persist_company=payload.save)
    return result.to_dict()


@app.post("/ingest")
def ingest_sources(payload: IngestPayload) -> dict[str, Any]:
    """Auto-extract from text / URLs (one or many), then match.

    Server-local file paths are refused unless ALLOW_LOCAL_PATHS=1 (local dev only);
    use ``/ingest/upload`` to send files.
    """
    allow_paths = os.getenv("ALLOW_LOCAL_PATHS", "0").strip().lower() in {"1", "true", "yes", "on"}
    if payload.files and not allow_paths:
        raise HTTPException(
            status_code=400,
            detail="'files' (server paths) is disabled. Upload via POST /ingest/upload, "
            "or set ALLOW_LOCAL_PATHS=1 for local development.",
        )
    batch = ingest_and_match(
        payload.sources or None,
        text=payload.text,
        files=payload.files or None,
        urls=payload.urls or None,
        engine=get_engine(),
        save=payload.save,
        use_llm=payload.use_llm,
        match=not payload.extract_only,
        allow_local_paths=allow_paths,
    )
    if payload.write_handoff:
        write_handoff(batch)
    return batch.to_dict()


@app.post("/ingest/upload")
async def ingest_upload(
    files: list[UploadFile] = File(default=[]),
    text: str | None = Form(default=None),
    urls: str | None = Form(default=None, description="Comma-separated URLs"),
    save: bool = Form(default=False),
    use_llm: bool = Form(default=False),
    write_handoff_flag: bool = Form(default=False, alias="write_handoff"),
) -> dict[str, Any]:
    """Browser-friendly multipart ingest: upload PDFs/text + optional URLs/text."""
    tmp_paths: list[Path] = []
    try:
        for upload in files:
            suffix = Path(upload.filename or "upload.bin").suffix or ".txt"
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            tmp.write(await upload.read())
            tmp.close()
            tmp_paths.append(Path(tmp.name))

        url_list = [u.strip() for u in (urls or "").split(",") if u.strip()]
        batch = ingest_and_match(
            text=text,
            files=tmp_paths,
            urls=url_list,
            allow_local_paths=False,  # uploads are Path objects; strings never open files
            engine=get_engine(),
            save=save,
            use_llm=use_llm,
            match=True,
        )
        if write_handoff_flag:
            write_handoff(batch)
        return batch.to_dict()
    finally:
        for path in tmp_paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


@app.post("/ui/analyze")
async def ui_analyze(
    files: list[UploadFile] = File(default=[]),
    text: str | None = Form(default=None),
    urls: str | None = Form(default=None),
    write_handoff_flag: bool = Form(default=True, alias="write_handoff"),
    translate: bool = Form(default=True),
    use_llm: bool = Form(default=False),
    index_qdrant: bool = Form(default=True),
    llm_mode: str | None = Form(default=None),
) -> dict[str, Any]:
    """UI endpoint: ingest → translate→EN → extract → prioritize → match → Qdrant → handoff.

    ``llm_mode``: off (instant, no LLM — the UI's first pass) | lite (one fast LLM call) |
    deep (full profile). The UI shows the instant result, then refines in the background.
    """
    mode = (llm_mode or ("deep" if use_llm else "lite")).strip().lower()
    if mode not in {"off", "lite", "deep"}:
        mode = "lite"
    use_llm = mode == "deep"
    tmp_paths: list[Path] = []
    try:
        for upload in files:
            suffix = Path(upload.filename or "upload.bin").suffix or ".txt"
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            tmp.write(await upload.read())
            tmp.close()
            tmp_paths.append(Path(tmp.name))

        url_list = [u.strip() for u in (urls or "").split(",") if u.strip()]
        if not text and not url_list and not tmp_paths:
            raise HTTPException(status_code=400, detail="Provide text, URL, and/or a file.")

        # Blocking ingest in a worker thread (keeps UI/health responsive).
        # Do NOT reuse get_engine() here — SQLite connections are thread-bound.
        def _run_ingest():
            from . import budget

            # Stay well inside the UI's own timeout (90 s normal / 180 s Deep LLM)
            env_key, default = {
                "off": ("ANALYZE_BUDGET_FAST_S", "15"),
                "lite": ("ANALYZE_BUDGET_S", "25"),
                "deep": ("ANALYZE_BUDGET_DEEP_S", "150"),
            }[mode]
            secs = float(os.getenv(env_key) or default)
            with budget.budget(secs, llm_mode=mode):
                return ingest_and_match(
                    text=text,
                    files=tmp_paths,
                    urls=url_list,
                    allow_local_paths=False,  # uploads are Path objects; strings never open files
                    engine=CompanyMatchEngine(),
                    save=False,
                    use_llm=use_llm,
                    translate=translate,
                    match=True,
                    index_qdrant=index_qdrant,
                )

        batch = await asyncio.to_thread(_run_ingest)
        handoff_paths = None
        if write_handoff_flag:
            paths = await asyncio.to_thread(write_handoff, batch)
            handoff_paths = {k: str(v) for k, v in paths.items()}

        view = _ui_view(batch.to_dict())
        view["handoff_paths"] = handoff_paths
        return view
    finally:
        for path in tmp_paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


@app.get("/qdrant/info")
def qdrant_info() -> dict[str, Any]:
    try:
        from .vectorstore import get_qdrant_store

        return get_qdrant_store().info()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/qdrant/search")
def qdrant_search(
    q: str = Query(..., description="Later-stage semantic query"),
    limit: int = Query(default=8, ge=1, le=50),
) -> dict[str, Any]:
    try:
        from .vectorstore import get_qdrant_store

        store = get_qdrant_store()
        return {"info": store.info(), "hits": store.search(q, limit=limit)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
