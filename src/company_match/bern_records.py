"""Canton of Bern records from the navigator (teammates' extraction) → company matching.

This is the single integration point between the *company* side (this package)
and the *Bern expertise* side (UniBE / ARTORG / Diabetes Center Berne extraction
built by teammates). Teammates only have to drop files in a folder — no import
of this package needed on their side.

Where records are read from
---------------------------
1. ``$BERN_RECORDS_PATH`` (a file or folder), else
2. ``src/company_match/data/bern_records/`` (every ``*.json`` / ``*.jsonl``)

Accepted file shapes: a JSON array, ``{"records": [...]}``, or JSONL (one record per line).

Record schema (see BACKEND_CONTRACT.md for the full spec)
--------------------------------------------------------
Required:  ``id``, ``name``, ``type``, ``source_url``
Optional:  ``role``, ``unit``, ``institution``, ``expertise`` (list), ``projects`` (list),
           ``infrastructure`` (list), ``services`` (list), ``description``, ``contact``,
           ``extra_source_urls`` (list), ``language``

``type`` is one of: person | unit | group | project | infrastructure | service.

Unknown keys are kept and passed through untouched, so teammates can add
fields without breaking anything.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from .semantics import SEMANTIC_CLUSTERS

DEFAULT_DIR = Path(__file__).resolve().parent / "data" / "bern_records"
REQUIRED = ("id", "name", "type", "source_url")
VALID_TYPES = {"person", "unit", "group", "project", "infrastructure", "service"}
LIST_FIELDS = ("expertise", "projects", "infrastructure", "services", "extra_source_urls")

# Field weights: expertise text is the strongest signal of real capability
FIELD_WEIGHTS = {
    "expertise": 1.0,
    "projects": 0.8,
    "infrastructure": 0.6,
    "services": 0.6,
    "description": 0.5,
    "unit": 0.3,
    "name": 0.3,
    "role": 0.2,
}


@dataclass
class RecordIssue:
    file: str
    index: int
    problem: str


@dataclass
class RecordSet:
    records: list[dict[str, Any]] = field(default_factory=list)
    issues: list[RecordIssue] = field(default_factory=list)
    files: list[str] = field(default_factory=list)

    @property
    def loaded(self) -> bool:
        return bool(self.records)


# ---------------------------------------------------------------------------
# Loading + validation
# ---------------------------------------------------------------------------

def _iter_files(path: Path) -> Iterable[Path]:
    if path.is_file():
        yield path
    elif path.is_dir():
        for p in sorted(path.iterdir()):
            if p.suffix.lower() in {".json", ".jsonl"} and not p.name.startswith("_"):
                yield p


def _parse_file(path: Path) -> list[Any]:
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return []
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("records") or data.get("items") or [data]
    return data if isinstance(data, list) else []


def normalize_record(raw: dict[str, Any]) -> dict[str, Any]:
    rec = dict(raw)
    for key in LIST_FIELDS:
        val = rec.get(key)
        if isinstance(val, str):
            rec[key] = [v.strip() for v in re.split(r"[;,|]", val) if v.strip()]
        elif val is None:
            rec[key] = []
    rec["type"] = str(rec.get("type") or "").strip().lower()
    return rec


def validate_record(rec: dict[str, Any]) -> list[str]:
    problems = [f"missing '{k}'" for k in REQUIRED if not rec.get(k)]
    if rec.get("type") and rec["type"] not in VALID_TYPES:
        problems.append(f"type '{rec['type']}' not in {sorted(VALID_TYPES)}")
    url = str(rec.get("source_url") or "")
    if url and not url.startswith(("http://", "https://")):
        problems.append("source_url must be a public http(s) URL (traceability)")
    if not (rec.get("expertise") or rec.get("description") or rec.get("projects")):
        problems.append("no expertise/description/projects — record cannot be matched")
    return problems


def load_records(path: str | Path | None = None) -> RecordSet:
    """Load + validate teammate records. Invalid records are skipped, not fatal."""
    root = Path(path or os.getenv("BERN_RECORDS_PATH") or DEFAULT_DIR).expanduser()
    out = RecordSet()
    if not root.exists():
        return out
    seen: set[str] = set()
    for file in _iter_files(root):
        out.files.append(str(file))
        try:
            rows = _parse_file(file)
        except (OSError, json.JSONDecodeError) as exc:
            out.issues.append(RecordIssue(str(file), -1, f"unreadable: {exc}"))
            continue
        for idx, raw in enumerate(rows):
            if not isinstance(raw, dict):
                out.issues.append(RecordIssue(str(file), idx, "not an object"))
                continue
            rec = normalize_record(raw)
            problems = validate_record(rec)
            if problems:
                out.issues.append(RecordIssue(str(file), idx, "; ".join(problems)))
                continue
            if rec["id"] in seen:
                out.issues.append(RecordIssue(str(file), idx, f"duplicate id '{rec['id']}'"))
                continue
            seen.add(rec["id"])
            rec["_file"] = file.name
            out.records.append(rec)
    return out


@lru_cache(maxsize=4)
def _cached(path_key: str, mtime_key: float) -> RecordSet:
    return load_records(path_key or None)


def get_records() -> RecordSet:
    """Cached loader; reloads automatically when files change."""
    root = Path(os.getenv("BERN_RECORDS_PATH") or DEFAULT_DIR).expanduser()
    mtime = 0.0
    if root.exists():
        mtime = max([p.stat().st_mtime for p in _iter_files(root)] or [root.stat().st_mtime])
    return _cached(str(root), mtime)


# ---------------------------------------------------------------------------
# Matching (synonym-aware, traceable)
# ---------------------------------------------------------------------------

def _clean_terms(terms: Iterable[str]) -> list[str]:
    out = []
    for t in terms:
        t = str(t).lower().strip()
        if not t or "\\" in t or not re.search(r"[a-z]", t):
            continue  # skip regex fragments / non-Latin bridges
        out.append(t)
    return out


def _synonym_groups() -> list[set[str]]:
    groups = [set(_clean_terms(c.get("terms") or [])) for c in SEMANTIC_CLUSTERS]
    return [g for g in groups if g]


def expand_terms(terms: Iterable[str]) -> dict[str, str]:
    """Return {term_or_synonym: original_company_term} so lay terms reach expert wording."""
    out: dict[str, str] = {}
    groups = _synonym_groups()
    for t in _clean_terms(terms):
        out.setdefault(t, t)
        for g in groups:
            if t in g:
                for syn in g:
                    out.setdefault(syn, t)
    return out


def _present(term: str, text: str) -> bool:
    if " " in term or "-" in term:
        return term in text
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None


def _record_fields(rec: dict[str, Any]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for key in FIELD_WEIGHTS:
        val = rec.get(key)
        if isinstance(val, list):
            val = " ; ".join(str(v) for v in val)
        if val:
            fields[key] = re.sub(r"\s+", " ", str(val).lower())
    return fields


def match_records(
    company_terms: Iterable[str],
    records: list[dict[str, Any]] | None = None,
    *,
    limit: int = 8,
    min_score: float = 0.15,
) -> list[dict[str, Any]]:
    """Rank Bern records for a company. Every hit carries its ``source_url``.

    Score per record (0-1) = saturating sum of field-weighted term hits.
    Synonym hits count at 70 % of a direct hit.
    """
    if records is None:
        records = get_records().records
    if not records:
        return []
    expanded = expand_terms(company_terms)
    direct = set(_clean_terms(company_terms))
    results: list[dict[str, Any]] = []
    for rec in records:
        fields = _record_fields(rec)
        raw = 0.0
        hits: dict[str, list[str]] = {}
        matched_company_terms: set[str] = set()
        for term, origin in expanded.items():
            best_w = 0.0
            for fname, ftext in fields.items():
                if _present(term, ftext):
                    best_w = max(best_w, FIELD_WEIGHTS[fname])
                    hits.setdefault(fname, [])
                    if term not in hits[fname]:
                        hits[fname].append(term)
            if best_w and origin not in matched_company_terms:
                # count each company concept once (its best synonym hit)
                matched_company_terms.add(origin)
                raw += best_w * (1.0 if term in direct else 0.7)
        if not raw:
            continue
        score = 1.0 - pow(2.718281828, -raw / 2.0)
        if score < min_score:
            continue
        via_synonym = sorted(
            {t for ts in hits.values() for t in ts if t not in direct}
        )
        reason = (
            f"{rec.get('name')} ({rec.get('type')}"
            + (f", {rec.get('unit')}" if rec.get("unit") else "")
            + (f", {rec.get('institution')}" if rec.get("institution") else "")
            + ") matches on "
            + "; ".join(f"{k}: {', '.join(v[:4])}" for k, v in hits.items())
            + (f" (synonyms: {', '.join(via_synonym[:4])})" if via_synonym else "")
            + "."
        )
        results.append(
            {
                "record_id": rec.get("id"),
                "name": rec.get("name"),
                "type": rec.get("type"),
                "role": rec.get("role"),
                "unit": rec.get("unit"),
                "institution": rec.get("institution"),
                "expertise": rec.get("expertise") or [],
                "projects": rec.get("projects") or [],
                "infrastructure": rec.get("infrastructure") or [],
                "services": rec.get("services") or [],
                "contact": rec.get("contact"),
                "source_url": rec.get("source_url"),
                "extra_source_urls": rec.get("extra_source_urls") or [],
                "score": round(score, 3),
                "matched_terms": sorted(matched_company_terms),
                "matched_fields": hits,
                "reason": reason,
            }
        )
    results.sort(key=lambda r: (-r["score"], str(r.get("name"))))
    return results[:limit]
