"""Bounded, explainable collaboration-potential score (0-100).

``match_rate`` answers: *should Bern pursue collaboration with this company?*
It is **not** only diabetes/CGM keyword overlap. Capability overlap is one
component; domain fit and Swiss proximity matter for the judge.

    component                 max   what earns it
    ------------------------  ----  --------------------------------------------
    capability_overlap         40   specific overlap with Bern capabilities + evidence
    partnership_readiness      20   stated needs Bern can serve (trials, hospital…)
    domain_fit                 15   in-scope life-science sector (pharma, medtech…)
    swiss_proximity            15   Canton of Bern site / Swiss HQ / nearby country
    signal_depth               10   usable description, keywords, website

Capability overlap carries the most weight on purpose: sector and country are
shared by many companies, so they must not decide the ranking on their own.
Every component counts a fact only once (Bern presence lives in swiss_proximity).

Legacy capability-only components are kept under ``details.capability_components``
for teammates. Weights: ``data/scoring_weights.json``.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data"
WEIGHTS_PATH = DATA_DIR / "scoring_weights.json"

DEFAULT_WEIGHTS: dict[str, float] = {
    # Judge-facing collaboration potential (sums to 100)
    "capability_overlap": 40.0,
    "partnership_readiness": 20.0,
    "domain_fit": 15.0,
    "swiss_proximity": 15.0,
    "signal_depth": 10.0,
    # Legacy / detail (used inside capability_overlap)
    "capability_fit": 35.0,
    "breadth": 10.0,
    "needs_alignment": 15.0,
    "bern_presence": 10.0,
    "focus_synergy": 10.0,
    "evidence": 20.0,
    "evidence_without_records": 8.0,
}

SECTOR_DOMAIN_SCORE: dict[str, float] = {
    "pharma": 1.0,
    "biopharma": 1.0,
    "biotech": 0.95,
    "medtech": 0.95,
    "digital_health": 0.85,
    "cdmo": 0.85,
    "labtech": 0.8,
    "nutrition": 0.7,
}

SWISS_CITIES_NEAR_BERN = {
    "bern", "basel", "basel-stadt", "basel-land", "zurich", "zürich",
    "geneva", "lausanne", "fribourg", "neuchatel", "neuchâtel", "solothurn",
    "biel", "thun", "aarau",
}

# Saturation constant: fit = 1 - exp(-raw / K). raw≈K → 63 %, 2K → 86 %, 3K → 95 %.
FIT_K = 3.0

# Very generic terms carry little signal on their own ("diagnostic", "sensor"…)
GENERIC_TERMS = {
    "diagnostic", "diagnostics", "sensor", "wearable", "phase", "pump", "aid",
    "ct", "navigation", "pathology", "device development", "investigator",
    "inpatient", "outpatient", "deep learning", "computer vision", "reagent",
    "in vitro", "ivd", "medtech", "medical device", "insulin", "type 1", "type 2",
}

# Need → points (fraction of needs_alignment max) — what Bern can concretely offer
NEED_VALUE: dict[str, float] = {
    "clinical validation": 1.0,
    "clinical trial": 1.0,
    "hospital partnership": 0.9,
    "university collaboration": 0.9,
    "device r&d": 0.8,
    "kol access": 0.7,
    "talent": 0.7,
    "swiss hub": 0.5,
    "eu partners": 0.3,
}
NEEDS_SATURATION = 2.5  # ~2-3 strong needs reach the component max

# Semantic focus cluster → Bern capability id
FOCUS_TO_CAPABILITY = {
    "glucose_sensing": "diabetes_cgm",
    "diabetes_care": "diabetes_cgm",
    "metabolic": "metabolic_nutrition",
    "surgical_robotics": "surgical_robotics",
    "medtech_devices": "biomed_eng",
    "imaging_ai": "medical_imaging_ai",
    "clinical_translation": "translational_medicine",
}

MAX_CAPABILITY_WEIGHT = 1.15


def load_weights() -> dict[str, float]:
    weights = dict(DEFAULT_WEIGHTS)
    if WEIGHTS_PATH.is_file():
        try:
            data = json.loads(WEIGHTS_PATH.read_text(encoding="utf-8"))
            for k, v in data.items():
                if k in weights and isinstance(v, (int, float)):
                    weights[k] = float(v)
        except (OSError, json.JSONDecodeError):
            pass
    return weights


def term_credit(term: str) -> float:
    t = term.lower().strip()
    if t in GENERIC_TERMS:
        return 0.3
    if " " in t or "-" in t:
        return 1.0  # specific phrase
    return 0.6 if len(t) > 3 else 0.5


def saturate(raw: float, k: float = FIT_K) -> float:
    return 1.0 - math.exp(-max(raw, 0.0) / k)


@dataclass
class ScoreResult:
    match_rate: float
    components: dict[str, float]
    maxima: dict[str, float]
    details: dict[str, Any] = field(default_factory=dict)
    why_not_higher: list[str] = field(default_factory=list)
    verdict: str = "weak"
    verdict_label: str = "Weak collaboration potential"


def collaboration_verdict(rate: float) -> tuple[str, str]:
    if rate >= 70:
        return "strong", "Strong potential — prioritize outreach"
    if rate >= 50:
        return "promising", "Promising — worth exploring with Bern units"
    if rate >= 30:
        return "possible", "Possible — gather more needs / capability detail"
    return "weak", "Weak — low collaboration priority for now"


def score_company(
    company: dict[str, Any],
    capability_hits: list[dict[str, Any]],
    *,
    record_matches: list[dict[str, Any]] | None = None,
    records_loaded: bool = False,
) -> ScoreResult:
    """Compute collaboration potential (0–100) for Bern life-science matching.

    ``capability_hits``: dicts with ``id``, ``name``, ``weight``, ``overlap_terms``.
    ``record_matches``: output of ``bern_records.match_records`` (may be empty).
    """
    w = load_weights()
    details: dict[str, Any] = {}
    tips: list[str] = []

    # --- legacy capability internals (feeds capability_overlap) -------------
    fits: list[tuple[float, dict[str, Any]]] = []
    for hit in capability_hits:
        raw = sum(term_credit(t) for t in hit.get("overlap_terms") or [])
        weight = float(hit.get("weight") or 1.0) / MAX_CAPABILITY_WEIGHT
        fits.append((saturate(raw) * min(weight, 1.0), hit))
    fits.sort(key=lambda x: x[0], reverse=True)

    best_fit = fits[0][0] if fits else 0.0
    best_cap = fits[0][1] if fits else None
    capability_fit = w["capability_fit"] * best_fit
    secondary = sum(f for f, _ in fits[1:3])
    breadth = w["breadth"] * min(1.0, secondary / 1.2)
    details["capability_fit_ratio"] = round(best_fit, 3)
    details["best_capability"] = best_cap.get("id") if best_cap else None

    needs = [str(n).lower().strip() for n in company.get("needs") or []]
    need_raw = sum(NEED_VALUE.get(n, 0.2) for n in dict.fromkeys(needs))
    needs_alignment = w["needs_alignment"] * min(1.0, need_raw / NEEDS_SATURATION)
    details["needs_scored"] = needs

    bern_presence = w["bern_presence"] if company.get("canton_bern_presence") else 0.0

    focus_synergy = 0.0
    best_id = details["best_capability"]
    matched_ids = {h.get("id") for h in capability_hits}
    for fc in (company.get("semantic_profile") or {}).get("focus_clusters") or []:
        cap_id = FOCUS_TO_CAPABILITY.get(str(fc.get("id") or ""))
        if not cap_id or cap_id not in matched_ids:
            continue
        rel = float(fc.get("relevance") or 0.0) / 100.0
        factor = 1.0 if cap_id == best_id else 0.5
        focus_synergy = max(focus_synergy, w["focus_synergy"] * min(1.0, rel) * factor)
        details.setdefault("focus_cluster", fc.get("id"))

    record_matches = record_matches or []
    if records_loaded and record_matches:
        top = [float(r.get("score") or 0.0) for r in record_matches[:3]]
        ev_ratio = min(1.0, top[0] + 0.25 * sum(top[1:]))
        evidence = w["evidence"] * ev_ratio
        details["evidence_source"] = "bern_records"
    else:
        distinct = {t.lower() for h in capability_hits for t in h.get("overlap_terms") or []}
        evidence = w["evidence_without_records"] * min(1.0, len(distinct) / 10.0)
        details["evidence_source"] = "term_proxy"

    legacy = {
        "capability_fit": round(capability_fit, 1),
        "breadth": round(breadth, 1),
        "needs_alignment": round(needs_alignment, 1),
        "bern_presence": round(bern_presence, 1),
        "focus_synergy": round(focus_synergy, 1),
        "evidence": round(evidence, 1),
    }
    details["capability_components"] = legacy

    # --- judge-facing collaboration potential -------------------------------
    sector = str(company.get("sector") or "").lower().strip()
    sector_ratio = SECTOR_DOMAIN_SCORE.get(sector, 0.55 if company.get("in_scope") else 0.0)
    if company.get("in_scope") and not sector:
        sector_ratio = max(sector_ratio, 0.55)
    domain_fit = w["domain_fit"] * sector_ratio

    country = str(company.get("hq_country") or "").lower()
    city = str(company.get("hq_city") or "").lower()
    swiss = "switzerland" in country or country in {"ch", "swiss", "schweiz", "suisse"}
    near = any(c in city for c in SWISS_CITIES_NEAR_BERN)
    if company.get("canton_bern_presence"):
        swiss_proximity = w["swiss_proximity"]
    elif swiss and near:
        swiss_proximity = w["swiss_proximity"] * 0.9
    elif swiss:
        swiss_proximity = w["swiss_proximity"] * 0.7
    elif country and any(x in country for x in ("germany", "france", "austria", "italy", "eu")):
        swiss_proximity = w["swiss_proximity"] * 0.35
    else:
        swiss_proximity = 0.0

    desc = str(company.get("description") or company.get("what_they_do") or "")
    kws = company.get("keywords") or []
    has_web = bool(company.get("website"))
    depth_ratio = 0.0
    if len(desc) >= 80:
        depth_ratio += 0.45
    elif len(desc) >= 40:
        depth_ratio += 0.25
    if len(kws) >= 4:
        depth_ratio += 0.35
    elif len(kws) >= 1:
        depth_ratio += 0.2
    if has_web:
        depth_ratio += 0.2
    signal_depth = w["signal_depth"] * min(1.0, depth_ratio)

    # Capability internals only (needs and Bern presence are scored elsewhere).
    # Linear, no early saturation, so stronger overlap always earns more.
    # Evidence max is the with-records value: verified Bern records are needed
    # to reach the top of this component.
    cap_points = capability_fit + breadth + focus_synergy + evidence
    cap_max = w["capability_fit"] + w["breadth"] + w["focus_synergy"] + w["evidence"]
    capability_overlap = w["capability_overlap"] * min(1.0, cap_points / max(cap_max, 1.0))
    details["capability_points"] = round(cap_points, 1)
    details["capability_points_max"] = round(cap_max, 1)

    partnership_readiness = w["partnership_readiness"] * min(1.0, need_raw / NEEDS_SATURATION)

    components = {
        "domain_fit": round(domain_fit, 1),
        "swiss_proximity": round(swiss_proximity, 1),
        "signal_depth": round(signal_depth, 1),
        "capability_overlap": round(capability_overlap, 1),
        "partnership_readiness": round(partnership_readiness, 1),
    }
    maxima = {k: w[k] for k in components}
    match_rate = round(min(100.0, sum(components.values())), 1)
    verdict, verdict_label = collaboration_verdict(match_rate)

    if sector_ratio < 0.8:
        tips.append("Sector is life-science but not a top Bern priority vertical.")
    if not swiss:
        tips.append("HQ outside Switzerland — lower proximity score.")
    elif not company.get("canton_bern_presence"):
        tips.append("Swiss company but no Canton of Bern site yet.")
    if not needs:
        tips.append("No stated partnership needs (clinical validation, university, talent…).")
    if best_fit < 0.4:
        tips.append("Few specific overlaps with indexed Bern capabilities — add product/tech detail.")
    if details["evidence_source"] != "bern_records":
        tips.append(
            "No verified Bern expert/unit records matched yet — capability overlap "
            f"capped at {w['capability_overlap'] * (cap_max - w['evidence'] + w['evidence_without_records']) / cap_max:.0f}/"
            f"{w['capability_overlap']:.0f} until teammate records are loaded."
        )
    if not has_web:
        tips.append("No company website on file.")

    details["verdict"] = verdict
    details["verdict_label"] = verdict_label
    details["score_meaning"] = (
        "Collaboration potential for Canton of Bern life-science outreach (0–100)."
    )

    return ScoreResult(
        match_rate=match_rate,
        components=components,
        maxima=maxima,
        details=details,
        why_not_higher=tips,
        verdict=verdict,
        verdict_label=verdict_label,
    )


def formula_text() -> str:
    w = load_weights()
    return (
        f"collaboration_potential = capability_overlap(≤{w['capability_overlap']:.0f}) "
        f"+ partnership_readiness(≤{w['partnership_readiness']:.0f}) "
        f"+ domain_fit(≤{w['domain_fit']:.0f}) "
        f"+ swiss_proximity(≤{w['swiss_proximity']:.0f}) "
        f"+ signal_depth(≤{w['signal_depth']:.0f})."
    )


_WORD_RE = re.compile(r"[a-z0-9]+")
