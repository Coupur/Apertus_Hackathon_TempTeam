"""Prioritization for teammate handoff.

Early-stage (front) keywords are ranked by semantic frequency / relevance —
how central a theme is to what the company does — not just binary presence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from .semantics import score_source_semantics

# Kept for engine suggested-query bucketing / imports
EARLY_KEYWORDS: list[str] = [
    "cgm",
    "continuous glucose monitoring",
    "glucose sensor",
    "glucose sensors",
    "glucose",
    "biosensing",
    "biosensor",
    "diabetes",
    "insulin",
    "insulin pump",
    "closed loop",
    "aid",
    "metabolic monitoring",
    "wearable sensing",
    "artificial pancreas",
    "type 1",
    "type 2",
]

MID_KEYWORDS: list[str] = [
    "biomedical engineering",
    "medical device",
    "medtech",
    "surgical robotics",
    "robotic surgery",
    "surgical navigation",
    "medical imaging",
    "ai diagnostics",
    "digital pathology",
    "clinical trial",
    "clinical validation",
    "translational",
    "digital health",
    "remote monitoring",
    "implant",
    "wearable",
]

LATE_KEYWORDS: list[str] = [
    "university collaboration",
    "talent",
    "kol access",
    "hospital partnership",
    "swiss hub",
    "eu partners",
    "lab automation",
    "biologics",
    "immunology",
    "nutrition",
    "obesity",
    "cdmo",
    "biomanufacturing",
]

STAGE_RANK = {"early": 0, "mid": 1, "late": 2, "none": 3}


@dataclass
class PriorityBreakdown:
    priority_score: float  # 0–100 ranking score for sorting
    priority_rating: str  # P1 / P2 / P3 / P4
    priority_stage: str  # early | mid | late | none
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _profile_for_company(company: dict[str, Any]) -> dict[str, Any]:
    profile = company.get("semantic_profile")
    if profile and (profile.get("early_ranked") or profile.get("focus_clusters")):
        return profile

    text = " ".join(
        [
            str(company.get("source_text") or ""),
            str(company.get("description") or ""),
            str(company.get("meta_description") or ""),
            " ".join(company.get("keywords") or []),
            " ".join(company.get("needs") or []),
        ]
    )
    return score_source_semantics(
        text,
        title=str(company.get("meta_title") or company.get("name") or ""),
        meta_description=str(company.get("meta_description") or ""),
    )


def compute_priority(
    company: dict[str, Any],
    *,
    match_rate: float = 0.0,
    in_scope: bool = True,
    suggested_queries: Iterable[str] | None = None,
    overlap_terms: Iterable[str] | None = None,
) -> PriorityBreakdown:
    """Build prioritization rating with semantic-frequency early ranking."""
    if not in_scope:
        return PriorityBreakdown(
            priority_score=0.0,
            priority_rating="P4",
            priority_stage="none",
            handoff_note="Out of life-science scope — do not queue for navigator matching.",
        )

    profile = _profile_for_company(company)
    early_rel = list(profile.get("early_ranked") or [])
    mid_rel = list(profile.get("mid_ranked") or [])
    late_rel = list(profile.get("late_ranked") or [])
    focus = list(profile.get("focus_clusters") or [])
    activity = profile.get("activity_summary") or company.get("what_they_do") or ""

    # Merge overlap terms into the front tier by relevance (theme-neutral)
    if overlap_terms:
        known = {t["term"].lower() for t in early_rel + mid_rel + late_rel}
        for t in overlap_terms:
            tl = str(t).lower().strip()
            if not tl or tl in known:
                continue
            early_rel.append(
                {
                    "term": t,
                    "stage": "early",
                    "count": 1,
                    "relevance": 42.0,
                    "cluster_label": "capability overlap",
                }
            )

    # Re-bucket purely by relevance rank (front / supporting / peripheral)
    all_rel = sorted(
        early_rel + mid_rel + late_rel,
        key=lambda x: (-float(x.get("relevance") or 0), -int(x.get("count") or 0)),
    )
    n = len(all_rel)
    if n == 0:
        early_rel, mid_rel, late_rel = [], [], []
    else:
        front_n = max(3, min(8, (n + 2) // 3))
        mid_n = max(2, min(8, (n + 2) // 3))
        early_rel = all_rel[:front_n]
        mid_rel = all_rel[front_n : front_n + mid_n]
        late_rel = all_rel[front_n + mid_n :]
        for row in early_rel:
            row["stage"] = "early"
        for row in mid_rel:
            row["stage"] = "mid"
        for row in late_rel:
            row["stage"] = "late"

    early = [x["term"] for x in early_rel]
    mid = [x["term"] for x in mid_rel]
    late = [x["term"] for x in late_rel]

    top_early_rel = float(early_rel[0]["relevance"]) if early_rel else 0.0
    top_cluster_rel = float(focus[0]["relevance"]) if focus else 0.0

    # Score: collaboration % is primary; keywords refine queue order
    score = (
        min(55.0, float(match_rate) * 0.55)
        + min(25.0, top_early_rel * 0.25)
        + min(10.0, top_cluster_rel * 0.1)
        + min(10.0, len(early_rel) * 2.0)
    )
    if company.get("canton_bern_presence"):
        score = min(100.0, score + 8.0)
    if str(company.get("hq_country") or "").lower().find("switzerland") >= 0:
        score = min(100.0, score + 5.0)

    if match_rate >= 70 or (early_rel and top_early_rel >= 55):
        stage = "early"
    elif match_rate >= 50 or mid_rel or early_rel:
        stage = "mid"
    elif late_rel or match_rate >= 30:
        stage = "late"
    else:
        stage = "none"

    if score >= 70 or match_rate >= 70:
        rating = "P1"
    elif score >= 50 or match_rate >= 50:
        rating = "P2"
    elif score >= 30 or match_rate >= 30:
        rating = "P3"
    else:
        rating = "P4"

    # Teammate queries: highest-relevance front terms first (any theme)
    early_q = list(dict.fromkeys([*[x["term"] for x in early_rel], *(suggested_queries or [])]))[:8]
    later_q = list(
        dict.fromkeys(
            [
                *[x["term"] for x in mid_rel],
                *[x["term"] for x in late_rel],
                *[q for q in (suggested_queries or []) if q not in early_q],
            ]
        )
    )

    if match_rate >= 50:
        note = (
            f"{rating} — collaboration potential {match_rate:.0f}%. "
            f"Queue for navigator"
            + (f"; lead with '{early_rel[0]['term']}'." if early_rel else ".")
        )
    elif early_rel:
        top = early_rel[0]
        note = (
            f"{rating} / front relevance — strongest keyword '{top['term']}' "
            f"({top.get('relevance')}% relevance). "
            f"Collaboration potential {match_rate:.0f}%."
        )
    elif mid_rel:
        note = (
            f"{rating} / supporting signals — collaboration potential {match_rate:.0f}%. "
            f"Match next: {', '.join(mid[:5]) or 'n/a'}."
        )
    else:
        note = (
            f"{rating} — collaboration potential {match_rate:.0f}% "
            f"(add needs / product detail to raise score)."
        )

    return PriorityBreakdown(
        priority_score=round(min(100.0, score), 1),
        priority_rating=rating,
        priority_stage=stage,
        early_keywords=early[:12],
        mid_keywords=mid[:12],
        late_keywords=late[:12],
        early_relevance=early_rel[:12],
        mid_relevance=mid_rel[:12],
        late_relevance=late_rel[:10],
        focus_clusters=focus[:5],
        activity_summary=str(activity),
        teammate_queries_early=early_q[:8],
        teammate_queries_later=later_q[:10],
        handoff_note=note,
    )


def sort_key_for_priority(item: dict[str, Any]) -> tuple:
    """Sort key: early stage first, then rating, then scores."""
    stage = item.get("priority_stage") or "none"
    rating = item.get("priority_rating") or "P4"
    rating_order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}.get(rating, 4)
    return (
        0 if item.get("in_scope", True) else 1,
        STAGE_RANK.get(stage, 3),
        rating_order,
        -float(item.get("priority_score") or 0),
        -float(item.get("match_rate") or 0),
    )
