"""Durable company JSON output for backend / teammate consumption.

UI is demo-only. Every analyze/ingest writes structured company dicts to:
  outbox/companies/<slug>.json
  outbox/companies/latest_batch.json
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ingest import IngestBatchResult

DEFAULT_COMPANIES_DIR = Path(__file__).resolve().parent / "outbox" / "companies"
SCHEMA_VERSION = "2.0"


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (name or "unknown").lower()).strip("_")
    return s or "unknown"


def build_company_record(item: Any) -> dict[str, Any]:
    """One company as a backend-ready dictionary."""
    ext = item.extraction
    m = item.match
    company = ext.company or {}

    website_info = {
        "url": company.get("website") or (
            ext.source_ref if ext.source_type == "url" else None
        ),
        "source_type": ext.source_type,
        "source_ref": ext.source_ref,
        "meta_title": company.get("meta_title"),
        "meta_description": company.get("meta_description"),
        "fetched_language": company.get("source_language"),
        "translated_to_english": bool(company.get("translated_to_english")),
        "translation_method": company.get("translation_method"),
        "web_enrich_method": company.get("web_enrich_method") or "",
        "web_sources": company.get("web_sources") or [],
        "summary_method": company.get("summary_method") or "rules",
    }

    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "id": company.get("id") or _slug(company.get("name") or "unknown"),
        "name": company.get("name") or (m.company_name if m else "Unknown company"),
        "domain": "life_science",
        "in_scope": m.in_scope if m else bool(company.get("in_scope", True)),
        "website_info": website_info,
        "profile": {
            "sector": company.get("sector"),
            "subsector": company.get("subsector"),
            "description": company.get("description") or "",
            "what_they_do": company.get("what_they_do") or "",
            "keywords": company.get("keywords") or [],
            "needs": company.get("needs") or [],
            "hq_city": company.get("hq_city"),
            "hq_country": company.get("hq_country"),
            "canton_bern_presence": bool(company.get("canton_bern_presence")),
            # Where the HQ came from: source | json_ld | llm_quote | footer | imprint |
            # wikidata | llm_knowledge (verified=False) | domain_hint
            "hq_source": company.get("hq_source"),
            "bern_sites": company.get("bern_sites") or [],
            "medical_profile": company.get("medical_profile"),
            "semantic_profile": company.get("semantic_profile") or {},
        },
        "match": None,
        "extraction": {
            "confidence": ext.confidence,
            "method": ext.method,
            "warnings": list(ext.warnings or []),
        },
        "queue": {
            "position": item.queue_position,
            "priority_rating": m.priority_rating if m else None,
            "priority_stage": m.priority_stage if m else None,
            "priority_score": m.priority_score if m else None,
        },
        # Full corpus for backend embedding / re-score (truncated)
        "source_text_excerpt": (company.get("source_text") or "")[:6000],
    }

    if m is not None:
        record["match"] = {
            "match_rate": m.match_rate,
            "tier": m.tier,
            "reasons": list(m.reasons or []),
            "score_breakdown": dict(m.score_breakdown or {}),
            "reasoning": dict(m.reasoning or {}),
            "early_keywords": list(m.early_keywords or []),
            "mid_keywords": list(m.mid_keywords or []),
            "late_keywords": list(m.late_keywords or []),
            "early_relevance": list(m.early_relevance or []),
            "focus_clusters": list(m.focus_clusters or []),
            "bern_units": list(m.bern_units or []),
            # Traceable teammate records (person/unit/project) — each has source_url
            "bern_matches": list(m.bern_matches or []),
            "economic_hooks": list(m.economic_hooks or []),
            "capability_matches": [
                {
                    "id": c.capability_id,
                    "name": c.capability_name,
                    "score": c.score,
                    "overlap_terms": c.overlap_terms,
                    "source": c.source,
                    "units": c.units,
                    "reason": c.reason,
                }
                for c in (m.capability_matches or [])
            ],
            "teammate_queries_early": list(m.teammate_queries_early or []),
            "teammate_queries_later": list(m.teammate_queries_later or []),
            "suggested_queries": list(m.suggested_queries or []),
            "handoff_note": m.handoff_note or "",
        }
    return record


def build_batch_payload(batch: IngestBatchResult) -> dict[str, Any]:
    companies = [build_company_record(item) for item in batch.prioritized_items()]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "domain": "life_science",
        "owner_layer": "company_match",
        "how_to_use": (
            "Backend / teammate: load companies[]. "
            "Use match.score_breakdown.components (sums to match_rate) and "
            "match.bern_matches (records from data/bern_records with source_url). "
            "See src/company_match/BACKEND_CONTRACT.md. "
            "website_info holds the ingested site metadata. "
            "Push each company object (or this batch) to your API."
        ),
        "source_count": batch.source_count,
        "company_count": batch.company_count,
        "companies": companies,
    }


def write_company_outputs(
    batch: IngestBatchResult,
    out_dir: str | Path | None = None,
) -> dict[str, Path]:
    """Write per-company JSON + latest_batch.json for backend push."""
    out = Path(out_dir) if out_dir else DEFAULT_COMPANIES_DIR
    out.mkdir(parents=True, exist_ok=True)

    payload = build_batch_payload(batch)
    batch_path = out / "latest_batch.json"
    batch_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stamped = out / f"batch_{stamp}.json"
    stamped.write_text(batch_path.read_text(encoding="utf-8"), encoding="utf-8")

    paths: dict[str, Path] = {
        "latest_batch": batch_path,
        "stamped_batch": stamped,
    }
    for rec in payload["companies"]:
        slug = _slug(str(rec.get("name") or rec.get("id")))
        path = out / f"{slug}.json"
        path.write_text(
            json.dumps(rec, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        paths[f"company:{slug}"] = path

    readme = out / "README.md"
    readme.write_text(
        "\n".join(
            [
                "# Company output (backend)",
                "",
                "Written automatically on each UI/API analyze.",
                "",
                "- `latest_batch.json` — full batch for your backend",
                "- `<company_slug>.json` — one file per company",
                "- `batch_*.json` — timestamped archive",
                "",
                "Each company has `website_info`, `profile`, `match.reasoning`, "
                "and `match.score_breakdown` for navigator alignment.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    paths["readme"] = readme
    return paths
