"""Semantic frequency / relevance scoring for company keywords.

Understands what a company does by counting term + synonym hits in source text,
with higher weight for title / lead paragraphs. Used to rank EARLY (front)
keywords by how central they are to the company narrative.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable

# Semantic clusters: synonyms collapse into one relevance theme
SEMANTIC_CLUSTERS: list[dict[str, Any]] = [
    {
        "id": "glucose_sensing",
        "label": "Glucose sensing / CGM",
        "stage": "early",
        "canonical": "continuous glucose monitoring",
        "terms": [
            "continuous glucose monitoring",
            "glucose sensors",
            "glucose sensor",
            "flash glucose",
            "freestyle libre",
            "biosensing",
            "biosensor",
            "cgm",
            "glucose",
            "glycemic",
            "glycaemic",
            # multilingual bridges (count even before full translation)
            "blutzucker",
            "blutzuckersensor",
            "glukose",
            "glukosesensor",
            "glycémie",
            "glicemia",
            "glucosa",
            "血糖",
            "葡萄糖",
            "biosensorik",
        ],
    },
    {
        "id": "diabetes_care",
        "label": "Diabetes care & insulin delivery",
        "stage": "early",
        "canonical": "diabetes",
        "terms": [
            "artificial pancreas",
            "insulin pump",
            "closed loop",
            "diabetes",
            "insulin",
            "type 1",
            "type 2",
            "aid system",
            "\baid\b",
            "diabetiker",
            "diabète",
            "diabete",
            "insulinpumpe",
            "pompe à insuline",
            "糖尿病",
            "胰岛素",
            "インスリン",
        ],
    },
    {
        "id": "metabolic",
        "label": "Metabolic monitoring",
        "stage": "early",
        "canonical": "metabolic monitoring",
        "terms": [
            "metabolic monitoring",
            "wearable sensing",
            "metabolic",
            "endocrinology",
            "obesity",
            "glp-1",
        ],
    },
    {
        "id": "surgical_robotics",
        "label": "Surgical robotics & navigation",
        "stage": "mid",
        "canonical": "surgical robotics",
        "terms": [
            "surgical robotics",
            "robotic surgery",
            "surgical navigation",
            "computer-assisted surgery",
            "image-guided",
        ],
    },
    {
        "id": "medtech_devices",
        "label": "Medical devices / medtech",
        "stage": "mid",
        "canonical": "medical device",
        "terms": [
            "biomedical engineering",
            "medical devices",
            "medical device",
            "medtech",
            "implantable",
            "implant",
            "wearable",
            "dialysis",
            "catheter",
            "infusion",
            "injection",
            "diagnostic device",
            "regenerative medicine",
            "pharma packaging",
            "医療機器",
            "医薬品",
            "透析",
            "カテーテル",
            "再生医療",
        ],
    },
    {
        "id": "imaging_ai",
        "label": "Medical imaging & clinical AI",
        "stage": "mid",
        "canonical": "medical imaging",
        "terms": [
            "digital pathology",
            "ai diagnostics",
            "medical imaging",
            "clinical ai",
            "radiology",
            "radiomics",
        ],
    },
    {
        "id": "clinical_translation",
        "label": "Clinical / translational",
        "stage": "mid",
        "canonical": "clinical trial",
        "terms": [
            "clinical validation",
            "clinical trial",
            "translational",
            "hospital partnership",
            "investigator",
        ],
    },
    {
        "id": "digital_health",
        "label": "Digital health",
        "stage": "mid",
        "canonical": "digital health",
        "terms": [
            "remote monitoring",
            "digital health",
            "telemedicine",
            "connected care",
            "mhealth",
        ],
    },
    {
        "id": "biologics",
        "label": "Biologics / biomanufacturing",
        "stage": "late",
        "canonical": "biologics",
        "terms": [
            "biomanufacturing",
            "immunology",
            "biologics",
            "antibody",
            "cdmo",
            "plasma",
        ],
    },
    {
        "id": "partnering",
        "label": "Partnering / talent",
        "stage": "late",
        "canonical": "university collaboration",
        "terms": [
            "university collaboration",
            "academic partner",
            "kol access",
            "swiss hub",
            "eu partners",
            "talent",
            "recruiting",
        ],
    },
]


@dataclass
class TermRelevance:
    term: str
    stage: str
    cluster_id: str
    cluster_label: str
    count: int
    lead_count: int  # hits in title / first ~800 chars
    relevance: float  # 0–100
    semantic_boost: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _count_phrase(text: str, phrase: str) -> int:
    """Count occurrences; support regex-ish markers with \\b."""
    p = phrase.lower().strip()
    if not p:
        return 0
    if p.startswith(r"\b") or "\\b" in p:
        try:
            return len(re.findall(p, text, flags=re.I))
        except re.error:
            p = p.replace(r"\b", "")
    # word-boundary-ish for short tokens
    if " " not in p and "-" not in p:
        return len(re.findall(rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])", text, flags=re.I))
    return text.count(p)


def score_source_semantics(
    text: str,
    *,
    title: str = "",
    meta_description: str = "",
) -> dict[str, Any]:
    """Compute semantic frequency relevance across clusters and terms."""
    full = f"{title}\n{meta_description}\n{text}".lower()
    lead = f"{title}\n{meta_description}\n{text[:800]}".lower()

    term_scores: list[TermRelevance] = []
    cluster_scores: list[dict[str, Any]] = []

    for cluster in SEMANTIC_CLUSTERS:
        cluster_count = 0
        cluster_lead = 0
        best_term = cluster["canonical"]
        best_term_count = 0
        for term in cluster["terms"]:
            display = term.replace(r"\b", "").strip()
            c = _count_phrase(full, term)
            lc = _count_phrase(lead, term)
            if c <= 0:
                continue
            cluster_count += c
            cluster_lead += lc
            if c > best_term_count:
                best_term_count = c
                best_term = display

            # Frequency (log) + lead emphasis + multi-word specificity.
            # No diabetes/theme bias — "early" later means top relevance rank.
            freq = math.log1p(c) * 18.0
            lead_boost = min(25.0, lc * 8.0)
            specificity = 8.0 if (" " in display or "-" in display) else 0.0
            relevance = min(100.0, freq + lead_boost + specificity + 8.0)
            term_scores.append(
                TermRelevance(
                    term=display,
                    stage=cluster["stage"],
                    cluster_id=cluster["id"],
                    cluster_label=cluster["label"],
                    count=c,
                    lead_count=lc,
                    relevance=round(relevance, 1),
                    semantic_boost=8.0,
                )
            )

        if cluster_count > 0:
            # Cluster relevance: aggregate frequency + lead concentration (theme-neutral)
            crel = min(
                100.0,
                math.log1p(cluster_count) * 22.0
                + min(30.0, cluster_lead * 6.0)
                + 10.0,
            )
            cluster_scores.append(
                {
                    "id": cluster["id"],
                    "label": cluster["label"],
                    "stage": cluster["stage"],  # thematic tag only; not display bucket
                    "canonical": cluster["canonical"],
                    "count": cluster_count,
                    "lead_count": cluster_lead,
                    "relevance": round(crel, 1),
                    "top_term": best_term,
                }
            )

    # Dedupe terms keeping highest relevance
    by_term: dict[str, TermRelevance] = {}
    for ts in term_scores:
        prev = by_term.get(ts.term)
        if not prev or ts.relevance > prev.relevance:
            by_term[ts.term] = ts
    ranked_terms = sorted(by_term.values(), key=lambda t: (-t.relevance, -t.count, t.term))
    cluster_scores.sort(key=lambda c: (-c["relevance"], -c["count"]))

    # Early / mid / late = relevance tiers (front = strongest signals), NOT diabetes-only.
    n = len(ranked_terms)
    if n == 0:
        early, mid, late = [], [], []
    else:
        front_n = max(3, min(8, (n + 2) // 3))
        mid_n = max(2, min(8, (n + 2) // 3))
        early = ranked_terms[:front_n]
        mid = ranked_terms[front_n : front_n + mid_n]
        late = ranked_terms[front_n + mid_n :]
        # Re-tag display stage by rank tier
        for t in early:
            t.stage = "early"
        for t in mid:
            t.stage = "mid"
        for t in late:
            t.stage = "late"

    # What the company appears to do — top clusters by relevance
    focus = cluster_scores[:3]
    if focus:
        activity = (
            "Primary focus signals: "
            + "; ".join(f"{c['label']} ({c['relevance']}% relevance, n={c['count']})" for c in focus)
            + "."
        )
    else:
        activity = "No strong life-science semantic focus detected in source text."

    return {
        "activity_summary": activity,
        "focus_clusters": focus,
        "terms": [t.to_dict() for t in ranked_terms],
        "early_ranked": [t.to_dict() for t in early],
        "mid_ranked": [t.to_dict() for t in mid],
        "late_ranked": [t.to_dict() for t in late],
        "early_keywords": [t.term for t in early],
        "mid_keywords": [t.term for t in mid],
        "late_keywords": [t.term for t in late],
    }


def merge_keyword_lists(*lists: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for lst in lists:
        for item in lst or []:
            key = str(item).lower().strip()
            if key and key not in seen:
                seen.add(key)
                out.append(str(item))
    return out
