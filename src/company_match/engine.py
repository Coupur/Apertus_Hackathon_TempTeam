"""Company ↔ Canton of Bern life-science matching engine.

Takes company information (from DB or free-form payload) and returns:
- match_rate (0–100)
- structured match reasons
- linked Bern capabilities / units / suggested navigator queries
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from .database import (
    get_company,
    init_db,
    list_capabilities,
    list_companies,
    save_match_run,
    upsert_company,
)
from .domain import DOMAIN, DOMAIN_LABEL, is_life_science_company, scope_note
from .bern_records import get_records, match_records
from .priority import STAGE_RANK, compute_priority
from .scoring import formula_text, score_company

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-+/]*", re.I)

# Bonuses only for in-scope life-science sectors
SECTOR_BOOST = {
    "medtech": 8.0,
    "pharma": 7.0,
    "biopharma": 8.0,
    "digital_health": 7.0,
    "nutrition": 5.0,
    "labtech": 5.0,
    "cdmo": 6.0,
    "biotech": 7.0,
}


@dataclass
class CapabilityMatch:
    capability_id: str
    capability_name: str
    source: str
    score: float
    overlap_terms: list[str]
    units: list[str]
    reason: str


@dataclass
class CompanyMatchResult:
    company_id: str | None
    company_name: str
    match_rate: float
    tier: str
    reasons: list[str]
    domain: str = DOMAIN
    domain_label: str = DOMAIN_LABEL
    in_scope: bool = True
    scope_reason: str = ""
    # Prioritization for teammate navigator handoff
    priority_score: float = 0.0
    priority_rating: str = "P4"  # P1 front … P4 last
    priority_stage: str = "none"  # early | mid | late | none
    early_keywords: list[str] = field(default_factory=list)
    mid_keywords: list[str] = field(default_factory=list)
    late_keywords: list[str] = field(default_factory=list)
    early_relevance: list[dict[str, Any]] = field(default_factory=list)
    mid_relevance: list[dict[str, Any]] = field(default_factory=list)
    late_relevance: list[dict[str, Any]] = field(default_factory=list)
    focus_clusters: list[dict[str, Any]] = field(default_factory=list)
    activity_summary: str = ""
    teammate_queries_early: list[str] = field(default_factory=list)
    teammate_queries_later: list[str] = field(default_factory=list)
    handoff_note: str = ""
    capability_matches: list[CapabilityMatch] = field(default_factory=list)
    # Traceable teammate records (people / units / projects) with source_url
    bern_matches: list[dict[str, Any]] = field(default_factory=list)
    suggested_queries: list[str] = field(default_factory=list)
    bern_units: list[str] = field(default_factory=list)
    economic_hooks: list[str] = field(default_factory=list)
    input_summary: dict[str, Any] = field(default_factory=dict)
    # Structured breakdown for backend / teammate matching (not just prose)
    score_breakdown: dict[str, Any] = field(default_factory=dict)
    reasoning: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload

    def priority_sort_key(self) -> tuple:
        rating_order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}.get(self.priority_rating, 4)
        return (
            0 if self.in_scope else 1,
            STAGE_RANK.get(self.priority_stage, 3),
            rating_order,
            -self.priority_score,
            -self.match_rate,
        )


def normalize_text(*parts: str | None) -> str:
    return " ".join(p.strip().lower() for p in parts if p and p.strip())


def tokenize(text: str) -> set[str]:
    return {m.group(0).lower() for m in TOKEN_RE.finditer(text)}


def phrase_present(phrase: str, haystack: str) -> bool:
    p = phrase.lower().strip()
    if not p:
        return False
    if " " in p or "-" in p or "/" in p:
        return p in haystack
    # whole-word-ish match for single tokens
    return re.search(rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])", haystack) is not None


def tier_for_rate(rate: float) -> str:
    if rate >= 70:
        return "Strong collaboration potential"
    if rate >= 50:
        return "Promising — explore with Bern units"
    if rate >= 30:
        return "Possible — need more signal"
    return "Weak — low priority"


def _company_blob(company: dict[str, Any]) -> str:
    bits = [
        company.get("name"),
        company.get("sector"),
        company.get("subsector"),
        company.get("description"),
        company.get("what_they_do"),
        company.get("meta_description"),
        company.get("meta_title"),
        # Web-enrich / page corpus — needed so gateway sites still score
        (company.get("source_text") or "")[:8000],
        " ".join(company.get("keywords") or []),
        " ".join(company.get("needs") or []),
        " ".join(
            f"{fc.get('label', '')} {fc.get('canonical', '')} {fc.get('top_term', '')}"
            for fc in (company.get("semantic_profile") or {}).get("focus_clusters") or []
        ),
    ]
    return normalize_text(*bits)


def _score_capability(company_text: str, company: dict[str, Any], cap: dict[str, Any]) -> CapabilityMatch | None:
    terms = list(dict.fromkeys([*(cap.get("keywords") or []), *(cap.get("synonyms") or [])]))
    overlap: list[str] = []
    raw = 0.0

    for term in terms:
        if phrase_present(term, company_text):
            overlap.append(term)
            # multi-word phrases are more specific → higher credit
            raw += 2.2 if (" " in term or "-" in term) else 1.0

    if not overlap:
        return None

    # Cap contribution and apply capability weight
    weighted = min(raw, 12.0) * float(cap.get("weight", 1.0))

    # Needs alignment bonus
    needs = " ".join(company.get("needs") or []).lower()
    need_hits = [t for t in overlap if phrase_present(t, needs)]
    if need_hits:
        weighted += 1.5

    reason = (
        f"Aligns with Bern capability '{cap['name']}' via terms: "
        f"{', '.join(overlap[:6])}"
        + (f" (linked to stated needs: {', '.join(need_hits[:3])})" if need_hits else "")
        + f". Source ecosystem: {cap.get('source')}."
    )

    return CapabilityMatch(
        capability_id=cap["id"],
        capability_name=cap["name"],
        source=cap.get("source") or "",
        score=round(weighted, 2),
        overlap_terms=overlap[:10],
        units=list(cap.get("units") or []),
        reason=reason,
    )


def _economic_hooks(company: dict[str, Any], caps: list[CapabilityMatch]) -> list[str]:
    hooks: list[str] = []
    if company.get("canton_bern_presence"):
        hooks.append("Already present in Canton of Bern — deepen academia / talent links.")
    needs = [n.lower() for n in (company.get("needs") or [])]
    if any("clinical" in n or "trial" in n or "kol" in n for n in needs):
        hooks.append("Clinical / KOL need → Inselspital + UniBE investigator matching.")
    if any("talent" in n or "university" in n for n in needs):
        hooks.append("Talent / university need → UniBE graduate & partnership pipeline.")
    if any(c.capability_id in {"diabetes_cgm", "metabolic_nutrition"} for c in caps):
        hooks.append("Diabetes / metabolic fit → Diabetes Center Berne + device/drug collaboration.")
    if any(c.capability_id in {"biomed_eng", "surgical_robotics", "medical_imaging_ai"} for c in caps):
        hooks.append("Medtech / AI fit → ARTORG co-development and validation pathway.")
    if company.get("sector") in {"pharma", "biopharma", "cdmo"}:
        hooks.append("Pharma/biotech profile → soft-landing / Swiss hub narrative for WFB.")
    # unique preserve order
    seen: set[str] = set()
    out: list[str] = []
    for h in hooks:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def _suggested_queries(company: dict[str, Any], caps: list[CapabilityMatch]) -> list[str]:
    """Navigator queries with early (front) keywords first, later ones after."""
    from .priority import EARLY_KEYWORDS, LATE_KEYWORDS, MID_KEYWORDS

    early_set = {k.lower() for k in EARLY_KEYWORDS}
    mid_set = {k.lower() for k in MID_KEYWORDS}
    late_set = {k.lower() for k in LATE_KEYWORDS}

    raw: list[str] = []
    blob = _company_blob(company)
    if phrase_present("glucose", blob) or phrase_present("cgm", blob) or phrase_present("diabetes", blob):
        raw.extend(["glucose sensors", "continuous glucose monitoring", "biosensing", "cgm", "diabetes"])
    for cap in caps[:4]:
        raw.extend(cap.overlap_terms[:3])
    for kw in company.get("keywords") or []:
        raw.append(kw)

    def bucket(q: str) -> int:
        ql = q.lower().strip()
        if ql in early_set or any(e in ql or ql in e for e in early_set):
            return 0
        if ql in mid_set or any(m in ql or ql in m for m in mid_set):
            return 1
        if ql in late_set or any(l in ql or ql in l for l in late_set):
            return 2
        return 3

    seen: set[str] = set()
    ranked = sorted(raw, key=bucket)
    out: list[str] = []
    for q in ranked:
        key = q.lower().strip()
        if key and key not in seen:
            seen.add(key)
            out.append(q)
    return out[:10]


def match_company(
    company: dict[str, Any],
    capabilities: Iterable[dict[str, Any]],
) -> CompanyMatchResult:
    """Score one company against Bern life-science capabilities only."""
    in_scope, scope_reason, scope_confidence = is_life_science_company(company)
    summary = {
        "sector": company.get("sector"),
        "subsector": company.get("subsector"),
        "keywords": company.get("keywords") or [],
        "needs": company.get("needs") or [],
        "canton_bern_presence": bool(company.get("canton_bern_presence")),
        "domain": DOMAIN,
        "scope_confidence": scope_confidence,
    }

    if not in_scope:
        prio = compute_priority(company, match_rate=0.0, in_scope=False)
        return CompanyMatchResult(
            company_id=company.get("id"),
            company_name=company.get("name") or "Unknown company",
            match_rate=0.0,
            tier="Out of scope — not life science",
            reasons=[
                scope_note(),
                scope_reason,
                "No Bern life-science match computed for out-of-domain companies.",
            ],
            domain=DOMAIN,
            domain_label=DOMAIN_LABEL,
            in_scope=False,
            scope_reason=scope_reason,
            priority_score=prio.priority_score,
            priority_rating=prio.priority_rating,
            priority_stage=prio.priority_stage,
            handoff_note=prio.handoff_note,
            capability_matches=[],
            suggested_queries=[],
            bern_units=[],
            economic_hooks=[],
            input_summary=summary,
            score_breakdown={"match_rate": 0.0, "why_not_higher": ["Out of life-science scope."]},
            reasoning={
                "summary": "Out of life-science scope — match rate 0.",
                "reasons": [scope_note(), scope_reason],
                "score_breakdown": {"match_rate": 0.0},
                "backend_hints": {"priority_rating": "P4", "priority_stage": "none"},
            },
        )

    company_text = _company_blob(company)
    caps = list(capabilities)

    scored: list[CapabilityMatch] = []
    for cap in caps:
        hit = _score_capability(company_text, company, cap)
        if hit:
            scored.append(hit)
    scored.sort(key=lambda c: c.score, reverse=True)

    top = scored[:5]
    cap_by_id = {c["id"]: c for c in caps}

    # Teammate Bern records (people / units / projects with source URLs)
    record_set = get_records()
    record_terms = list(
        dict.fromkeys(
            [
                *(company.get("keywords") or []),
                *[t for c in top for t in c.overlap_terms],
            ]
        )
    )
    bern_matches = match_records(record_terms, record_set.records) if record_set.loaded else []

    score = score_company(
        company,
        [
            {
                "id": c.capability_id,
                "name": c.capability_name,
                "weight": float(cap_by_id.get(c.capability_id, {}).get("weight", 1.0)),
                "overlap_terms": c.overlap_terms,
            }
            for c in top
        ],
        record_matches=bern_matches,
        records_loaded=record_set.loaded,
    )
    match_rate = score.match_rate
    legacy = (score.details or {}).get("capability_components") or {}
    focus_notes: list[str] = []
    if float(legacy.get("focus_synergy") or 0) > 0:
        focus_notes.append(
            f"Main theme '{score.details.get('focus_cluster')}' maps to Bern capability "
            f"'{score.details.get('best_capability')}' (+{legacy.get('focus_synergy')})."
        )

    score_breakdown = {
        "model": "collaboration-v1",
        "meaning": "Collaboration potential for Bern life-science outreach (0–100).",
        "verdict": score.verdict,
        "verdict_label": score.verdict_label,
        "components": score.components,
        "component_max": score.maxima,
        "details": score.details,
        "match_rate": match_rate,
        "formula": formula_text(),
        "capability_hits": [
            {
                "id": c.capability_id,
                "name": c.capability_name,
                "score": c.score,
                "overlap_terms": c.overlap_terms,
                "source": c.source,
            }
            for c in top
        ],
        "bern_records_loaded": len(record_set.records),
        "why_not_higher": score.why_not_higher,
    }

    reasons: list[str] = [scope_note(), scope_reason]
    reasons.append(score.verdict_label + f" ({match_rate}%).")
    reasons.append(
        f"Collaboration potential {match_rate}% = "
        + " + ".join(
            f"{k.replace('_', ' ')} {v}/{score.maxima[k]:.0f}" for k, v in score.components.items()
        )
        + "."
    )
    if company.get("canton_bern_presence"):
        reasons.append(
            f"{company.get('name')} already has presence in Canton of Bern "
            f"({company.get('hq_city') or 'local site'}), raising strategic priority."
        )
    else:
        reasons.append(
            "No Canton of Bern presence detected — partnership readiness would rise with a local site."
        )
    if company.get("sector"):
        reasons.append(
            f"Sector '{company.get('sector')}'"
            + (f" / {company.get('subsector')}" if company.get("subsector") else "")
            + " maps to Bern's life-science value proposition."
        )
    for note in focus_notes[:3]:
        reasons.append(note)
    for cap in top[:4]:
        reasons.append(cap.reason)
    for rec in bern_matches[:3]:
        reasons.append(f"Verified Bern match: {rec['reason']} Source: {rec['source_url']}")
    if not scored:
        reasons.append(
            "In life-science domain, but no reliable overlap with indexed Bern capabilities yet — "
            "collect more keywords/needs or mark as insufficient source signal."
        )
    for tip in score_breakdown["why_not_higher"][:2]:
        reasons.append(tip)

    units: list[str] = []
    for cap in top:
        for u in cap.units:
            if u not in units:
                units.append(u)

    for rec in bern_matches:
        label = rec.get("unit") or (rec.get("name") if rec.get("type") in {"unit", "group"} else None)
        if label and label not in units:
            units.append(label)

    queries = _suggested_queries(company, top)
    overlap = [t for c in top for t in c.overlap_terms]
    prio = compute_priority(
        company,
        match_rate=match_rate,
        in_scope=True,
        suggested_queries=queries,
        overlap_terms=overlap,
    )
    reasons.insert(
        2 if len(reasons) > 2 else len(reasons),
        prio.handoff_note,
    )

    return CompanyMatchResult(
        company_id=company.get("id"),
        company_name=company.get("name") or "Unknown company",
        match_rate=match_rate,
        tier=tier_for_rate(match_rate),
        reasons=reasons,
        domain=DOMAIN,
        domain_label=DOMAIN_LABEL,
        in_scope=True,
        scope_reason=scope_reason,
        priority_score=prio.priority_score,
        priority_rating=prio.priority_rating,
        priority_stage=prio.priority_stage,
        early_keywords=prio.early_keywords,
        mid_keywords=prio.mid_keywords,
        late_keywords=prio.late_keywords,
        early_relevance=prio.early_relevance,
        mid_relevance=prio.mid_relevance,
        late_relevance=prio.late_relevance,
        focus_clusters=prio.focus_clusters,
        activity_summary=prio.activity_summary or str(company.get("what_they_do") or ""),
        teammate_queries_early=prio.teammate_queries_early,
        teammate_queries_later=prio.teammate_queries_later,
        handoff_note=prio.handoff_note,
        capability_matches=top,
        bern_matches=bern_matches,
        suggested_queries=queries,
        bern_units=units[:8],
        economic_hooks=_economic_hooks(company, top),
        input_summary=summary,
        score_breakdown=score_breakdown,
        reasoning={
            "summary": (
                f"{match_rate}% collaboration potential — {score.verdict_label}. "
                f"Top capability: "
                + (
                    f"{top[0].capability_name} via {', '.join(top[0].overlap_terms[:4])}."
                    if top
                    else "none yet (domain/Swiss proximity still score)."
                )
            ),
            "reasons": reasons,
            "score_breakdown": score_breakdown,
            "focus_synergy": focus_notes,
            "economic_hooks": _economic_hooks(company, top),
            "bern_units": units[:8],
            "bern_matches": bern_matches,
            "backend_hints": {
                "priority_rating": prio.priority_rating,
                "priority_stage": prio.priority_stage,
                "run_first": prio.teammate_queries_early,
                "run_later": prio.teammate_queries_later,
                "capability_ids": [c.capability_id for c in top],
            },
        },
    )


def company_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize free-form company information into the engine schema."""
    name = payload.get("name") or payload.get("company_name") or "Unnamed company"
    cid = payload.get("id") or re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")

    keywords = payload.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [k.strip() for k in re.split(r"[,;|]", keywords) if k.strip()]

    needs = payload.get("needs") or []
    if isinstance(needs, str):
        needs = [n.strip() for n in re.split(r"[,;|]", needs) if n.strip()]

    # Allow a single free-text "about" / "information" field
    description = payload.get("description") or payload.get("about") or payload.get("information") or ""
    extra = payload.get("text") or payload.get("company_info") or ""
    if extra and extra not in description:
        description = f"{description} {extra}".strip()

    return {
        "id": cid,
        "name": name,
        "hq_country": payload.get("hq_country") or payload.get("country"),
        "hq_city": payload.get("hq_city") or payload.get("city"),
        "canton_bern_presence": bool(payload.get("canton_bern_presence")),
        "sector": payload.get("sector"),
        "subsector": payload.get("subsector"),
        "description": description,
        "what_they_do": payload.get("what_they_do"),
        "keywords": keywords,
        "needs": needs,
        "size": payload.get("size"),
        "website": payload.get("website"),
        "source_text": payload.get("source_text"),
        "meta_title": payload.get("meta_title"),
        "meta_description": payload.get("meta_description"),
        "semantic_profile": payload.get("semantic_profile"),
        "source_ref": payload.get("source_ref"),
        "source_type": payload.get("source_type"),
        "source_language": payload.get("source_language"),
        "translated_to_english": payload.get("translated_to_english"),
        "translation_method": payload.get("translation_method"),
        "original_excerpt": payload.get("original_excerpt"),
    }


class CompanyMatchEngine:
    """High-level engine used by CLI / API / navigator company layer."""

    def __init__(self, db_path: str | None = None, persist_runs: bool = True):
        self.conn = init_db(db_path, seed=True)
        self.persist_runs = persist_runs
        self.capabilities = list_capabilities(self.conn)

    def reload(self) -> None:
        self.capabilities = list_capabilities(self.conn)

    def match_payload(self, payload: dict[str, Any], persist_company: bool = False) -> CompanyMatchResult:
        company = company_from_payload(payload)
        # Merge with DB record if id/name known
        existing = get_company(self.conn, company["id"]) or get_company(self.conn, company["name"])
        if existing:
            merged = {**existing}
            for key, value in company.items():
                if value not in (None, "", [], False) or key in {"canton_bern_presence"}:
                    if key in {"keywords", "needs"} and not value and existing.get(key):
                        continue
                    if key in {"keywords", "needs"} and value:
                        merged[key] = list(dict.fromkeys([*(existing.get(key) or []), *value]))
                    elif value not in (None, ""):
                        merged[key] = value
            # preserve presence if either says true
            merged["canton_bern_presence"] = bool(
                existing.get("canton_bern_presence") or company.get("canton_bern_presence")
            )
            if not merged.get("description"):
                merged["description"] = existing.get("description")
            company = merged

        result = match_company(company, self.capabilities)

        # Persist only life-science companies into the working DB
        if persist_company and result.in_scope:
            upsert_company(self.conn, company)
            self.conn.commit()

        if self.persist_runs:
            save_match_run(
                self.conn,
                company_id=result.company_id,
                company_name=result.company_name,
                match_rate=result.match_rate,
                top_capability_ids=[c.capability_id for c in result.capability_matches],
                reasons=result.reasons,
                input_payload=payload,
            )
        return result

    def match_by_id(self, company_id: str) -> CompanyMatchResult | None:
        company = get_company(self.conn, company_id)
        if not company:
            return None
        return self.match_payload(company)

    def search_companies(
        self,
        query: str = "",
        *,
        min_match_rate: float = 0.0,
        sector: str | None = None,
        limit: int = 20,
        life_science_only: bool = True,
    ) -> list[CompanyMatchResult]:
        """Automatic search: rank life-science companies by Bern fit."""
        q = (query or "").lower().strip()
        results: list[CompanyMatchResult] = []

        for company in list_companies(self.conn):
            if sector and (company.get("sector") or "").lower() != sector.lower():
                continue
            blob = _company_blob(company)
            if q and q not in blob and q not in (company.get("name") or "").lower():
                # also allow token overlap
                q_tokens = tokenize(q)
                if not q_tokens.intersection(tokenize(blob)):
                    continue

            result = match_company(company, self.capabilities)
            if life_science_only and not result.in_scope:
                continue
            if result.match_rate >= min_match_rate:
                results.append(result)

        # Early-keyword / P1 companies first, then match rate
        def sort_key(r: CompanyMatchResult) -> tuple:
            name_boost = -5.0 if q and q in r.company_name.lower() else 0.0
            base = r.priority_sort_key()
            return (*base[:-1], base[-1] + name_boost)

        results.sort(key=sort_key)
        return results[:limit]

    def list_companies(self) -> list[dict[str, Any]]:
        return list_companies(self.conn)

    def close(self) -> None:
        self.conn.close()
