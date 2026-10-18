"""Export handoff files your teammate can use WITHOUT running this package.

Writes stable JSON + Markdown into `handoff/` (or a path you choose).
Teammate only needs to open/read those files (or load JSON in their code).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .company_output import write_company_outputs
from .ingest import IngestBatchResult, ingest_and_match

# Use outbox/ (not handoff/) so this module name does not clash with a folder package
DEFAULT_HANDOFF_DIR = Path(__file__).resolve().parent / "outbox"
SCHEMA_VERSION = "1.1"


def build_handoff_payload(batch: IngestBatchResult) -> dict[str, Any]:
    """Compact, teammate-friendly payload (no need to import company_match)."""
    queue = batch.teammate_queue()
    companies = []
    for item in batch.prioritized_items():
        m = item.match
        ext = item.extraction
        companies.append(
            {
                "queue_position": item.queue_position,
                "company_name": m.company_name if m else ext.company.get("name"),
                "in_scope": m.in_scope if m else ext.company.get("in_scope", True),
                "domain": "life_science",
                "priority_rating": m.priority_rating if m else None,
                "priority_stage": m.priority_stage if m else None,
                "priority_score": m.priority_score if m else None,
                "match_rate": m.match_rate if m else None,
                "tier": m.tier if m else None,
                "run_first": m.teammate_queries_early if m else [],
                "run_later": m.teammate_queries_later if m else [],
                "early_keywords": m.early_keywords if m else [],
                "mid_keywords": m.mid_keywords if m else [],
                "late_keywords": m.late_keywords if m else [],
                "bern_units": m.bern_units if m else [],
                "reasons": m.reasons if m else [],
                "score_breakdown": m.score_breakdown if m else {},
                "reasoning": m.reasoning if m else {},
                "handoff_note": m.handoff_note if m else "",
                "source_type": ext.source_type,
                "source_ref": ext.source_ref,
                "website_info": {
                    "url": ext.company.get("website") or (
                        ext.source_ref if ext.source_type == "url" else None
                    ),
                    "meta_title": ext.company.get("meta_title"),
                    "meta_description": ext.company.get("meta_description"),
                    "web_enrich_method": ext.company.get("web_enrich_method"),
                    "web_sources": ext.company.get("web_sources") or [],
                    "summary_method": ext.company.get("summary_method"),
                },
                "extracted": {
                    "sector": ext.company.get("sector"),
                    "subsector": ext.company.get("subsector"),
                    "keywords": ext.company.get("keywords") or [],
                    "needs": ext.company.get("needs") or [],
                    "website": ext.company.get("website"),
                    "hq_city": ext.company.get("hq_city"),
                    "hq_country": ext.company.get("hq_country"),
                    "description": (ext.company.get("description") or "")[:500],
                },
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "domain": "life_science",
        "domain_label": "Life Science",
        "owner_layer": "company_match",
        "how_to_use": (
            "Teammate does NOT need to run company_match. "
            "Read teammate_queue in order. For each company, run navigator "
            "search with run_first queries, then run_later. Keep source_ref for traceability."
        ),
        "source_count": batch.source_count,
        "company_count": batch.company_count,
        "teammate_queue": queue,
        "companies": companies,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Company match handoff (Life Science)",
        "",
        f"- Generated: `{payload.get('generated_at')}`",
        f"- Schema: `{payload.get('schema_version')}`",
        f"- Companies: **{payload.get('company_count')}**",
        "",
        "> Your navigator teammate can use this file alone — no need to import `company_match`.",
        "",
        "## Queue (run in this order)",
        "",
    ]
    for row in payload.get("teammate_queue") or []:
        lines.append(
            f"### #{row.get('queue_position')} — {row.get('company_name')} "
            f"[{row.get('priority_rating')}/{row.get('priority_stage')}]"
        )
        lines.append("")
        lines.append(f"- Match rate: **{row.get('match_rate')}%**")
        lines.append(f"- Priority score: {row.get('priority_score')}")
        if row.get("handoff_note"):
            lines.append(f"- Note: {row['handoff_note']}")
        if row.get("run_first"):
            lines.append(f"- **Run first (navigator queries):** {', '.join(row['run_first'])}")
        if row.get("run_later"):
            lines.append(f"- **Run later:** {', '.join(row['run_later'][:8])}")
        if row.get("bern_units"):
            lines.append(f"- Bern units: {', '.join(row['bern_units'][:6])}")
        if row.get("source_ref"):
            lines.append(f"- Source: `{row['source_ref']}`")
        lines.append("")

    lines.extend(["## Full company cards", ""])
    for c in payload.get("companies") or []:
        if c.get("in_scope") is False:
            continue
        lines.append(f"### {c.get('company_name')}")
        lines.append("")
        extracted = c.get("extracted") or {}
        if extracted.get("sector"):
            lines.append(f"- Sector: {extracted.get('sector')} / {extracted.get('subsector') or '-'}")
        if extracted.get("keywords"):
            lines.append(f"- Keywords: {', '.join(extracted['keywords'][:10])}")
        if c.get("reasons"):
            lines.append("- Why matched:")
            for r in c["reasons"][:5]:
                lines.append(f"  - {r}")
        lines.append("")
    return "\n".join(lines)


def write_handoff(
    batch: IngestBatchResult,
    out_dir: str | Path | None = None,
    *,
    stem: str = "latest",
) -> dict[str, Path]:
    """Write `latest.json` + `latest.md` (and a timestamped copy)."""
    out = Path(out_dir) if out_dir else DEFAULT_HANDOFF_DIR
    out.mkdir(parents=True, exist_ok=True)

    payload = build_handoff_payload(batch)
    json_path = out / f"{stem}.json"
    md_path = out / f"{stem}.md"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stamped_json = out / f"handoff_{stamp}.json"
    stamped_md = out / f"handoff_{stamp}.md"
    stamped_json.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
    stamped_md.write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")

    # Backend-ready company dictionaries (primary artifact for teammate push)
    company_paths = write_company_outputs(batch)

    # Tiny pointer file for teammates
    readme = out / "README_FOR_TEAMMATE.md"
    readme.write_text(
        "\n".join(
            [
                "# For the expertise-navigator teammate",
                "",
                "You do **not** need to install or run `company_match`.",
                "",
                "1. Open `latest.md` for a human checklist, or",
                "2. Load `latest.json` in your code, or",
                "3. **Preferred for backend:** load `companies/latest_batch.json` "
                "(full company dict + `match.reasoning` + `website_info`).",
                "",
                "Use `teammate_queue` in order:",
                "- run navigator search with each `run_first` query",
                "- then `run_later`",
                "- keep `source_ref` / reasons / score_breakdown for traceability",
                "",
                f"Schema version: {SCHEMA_VERSION}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    return {
        "json": json_path,
        "md": md_path,
        "stamped_json": stamped_json,
        "stamped_md": stamped_md,
        "readme": readme,
        "companies_batch": company_paths["latest_batch"],
    }


def export_handoff_from_sources(
    sources: str | Path | Iterable[str | Path] | None = None,
    *,
    text: str | None = None,
    files: Iterable[str | Path] | None = None,
    urls: Iterable[str] | None = None,
    out_dir: str | Path | None = None,
    use_llm: bool = False,
) -> dict[str, Any]:
    batch = ingest_and_match(
        sources,
        text=text,
        files=files,
        urls=urls,
        use_llm=use_llm,
        match=True,
        save=False,
    )
    paths = write_handoff(batch, out_dir=out_dir)
    payload = build_handoff_payload(batch)
    return {
        "paths": {k: str(v) for k, v in paths.items()},
        "payload": payload,
    }
