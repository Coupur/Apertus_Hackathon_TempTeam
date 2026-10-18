"""Life-science domain scope for the Bern company-matching layer.

This layer is intentionally limited to life sciences for the current challenge
(UniBE / ARTORG / Diabetes Center Berne). Non-life-science companies are
detected and returned as out-of-scope instead of fake high match scores.
"""

from __future__ import annotations

import re
from typing import Any

DOMAIN = "life_science"
DOMAIN_LABEL = "Life Science"

# Allowed sectors for this layer
LIFE_SCIENCE_SECTORS = frozenset(
    {
        "medtech",
        "pharma",
        "biopharma",
        "biotech",
        "digital_health",
        "nutrition",  # medical / metabolic nutrition only
        "labtech",
        "cdmo",
    }
)

# Strong positive signals (company is in life science even if sector missing)
LIFE_SCIENCE_SIGNALS = [
    "life science",
    "life sciences",
    "medtech",
    "medical device",
    "pharma",
    "pharmaceutical",
    "biotech",
    "biopharma",
    "biologics",
    "biomedical",
    "clinical trial",
    "diabetes",
    "cgm",
    "glucose",
    "biosensor",
    "biosensing",
    "insulin",
    "oncology",
    "immunology",
    "therapeutic",
    "diagnostic",
    "medical imaging",
    "surgical robotics",
    "digital health",
    "digital pathology",
    "hospital",
    "patient",
    "vaccine",
    "antibody",
    "cdmo",
    "biomanufacturing",
    "endocrinology",
    "metabolic",
    "veterinary",
    "one health",
    "medical nutrition",
    "wearable sensing",
    "closed loop",
    "implantable",
]

# Clear negatives — general industry outside the challenge scope
OUT_OF_SCOPE_SIGNALS = [
    "fintech",
    "cryptocurrency",
    "blockchain trading",
    "e-commerce fashion",
    "retail clothing",
    "automotive oem",
    "real estate brokerage",
    "construction materials",
    "oil and gas",
    "gaming studio",
    "social media advertising",
    "hotel chain",
    "airline",
]


def _blob(company: dict[str, Any]) -> str:
    parts = [
        company.get("sector"),
        company.get("subsector"),
        company.get("description"),
        " ".join(company.get("keywords") or []),
        " ".join(company.get("needs") or []),
        company.get("name"),
    ]
    return " ".join(p for p in parts if p).lower()


def is_life_science_company(company: dict[str, Any]) -> tuple[bool, str, float]:
    """Return (in_scope, reason, confidence 0-1)."""
    sector = (company.get("sector") or "").lower().strip()
    text = _blob(company)

    if sector in LIFE_SCIENCE_SECTORS:
        return True, f"Sector '{sector}' is within the life-science domain.", 0.95

    neg_hits = [s for s in OUT_OF_SCOPE_SIGNALS if s in text]
    pos_hits = [s for s in LIFE_SCIENCE_SIGNALS if s in text]

    if neg_hits and not pos_hits:
        return (
            False,
            f"Out of scope for this life-science layer (signals: {', '.join(neg_hits[:3])}).",
            0.9,
        )

    if pos_hits:
        return (
            True,
            f"Life-science signals detected: {', '.join(pos_hits[:5])}.",
            min(0.9, 0.45 + 0.1 * len(pos_hits)),
        )

    if sector and sector not in LIFE_SCIENCE_SECTORS:
        return (
            False,
            f"Sector '{sector}' is outside the life-science domain of this layer.",
            0.85,
        )

    return (
        False,
        "Insufficient life-science evidence in the source — not matched in this domain layer.",
        0.4,
    )


def scope_note() -> str:
    return (
        f"Domain scope: {DOMAIN_LABEL} only "
        f"(sectors: {', '.join(sorted(LIFE_SCIENCE_SECTORS))}). "
        "Sources: University of Bern, ARTORG, Diabetes Center Berne."
    )
