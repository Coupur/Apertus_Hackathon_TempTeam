"""Evidence-derived tags from the project's fixed, versioned EN/DE vocabulary.

These describe mentions, not proven expertise, efficacy, availability or outcomes.
No keyword is inferred from an institution, source host or selection rule.
Collection never adds labels or aliases to the checked-in vocabulary.
"""
import json
import re
from pathlib import Path
from types import MappingProxyType
import unicodedata

MAX_KEYWORDS = 24

# This checked-in vocabulary is the sole source of allowed focused keywords.
# Changes are explicit repository edits accompanied by a version increment.
VOCABULARY_PATH = Path(__file__).with_name("keyword_vocabulary.json")
_vocabulary = json.loads(VOCABULARY_PATH.read_text(encoding="utf-8"))
KEYWORD_VOCABULARY_VERSION = _vocabulary["version"]
MEDICAL = MappingProxyType(_vocabulary["medical"])
GENERAL = MappingProxyType(_vocabulary["general"])
if MEDICAL.keys() & GENERAL.keys():
    raise ValueError("A keyword must belong to exactly one vocabulary category")
del _vocabulary


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold().replace("\u00ad", "")
    return " ".join(re.sub(r"[_\-‐‑–—/]", " ", text).split())


PATTERNS = MappingProxyType({
    label: re.compile(r"(?<!\w)(?:" + re.escape(normalize(label)) + "|" + aliases + r")(?!\w)")
    for label, aliases in {**MEDICAL, **GENERAL}.items()
})
INSTITUTIONS = re.compile(r"diabetes cent(?:er|re) bern(?:e)?\b|university of bern\b|universität bern\b|artorg\b")


def keyword_vocabulary() -> dict:
    """Return a fresh catalog for CLI/UI consumers without exposing regex internals."""
    return {"version": KEYWORD_VOCABULARY_VERSION, "count": len(PATTERNS),
            "groups": {"medical": sorted(MEDICAL), "general": sorted(GENERAL)}}


def extract_keywords(text: str, title: str = "") -> list[str]:
    """Prefer title matches, then medical terms and specificity; cap output size."""
    title = INSTITUTIONS.sub(" ", normalize(title))
    text = title + "\n" + INSTITUTIONS.sub(" ", normalize(text))
    matched = [label for label, pattern in PATTERNS.items() if pattern.search(text)]
    return sorted(matched, key=lambda label: (
        not bool(PATTERNS[label].search(title)), label not in MEDICAL,
        -len(label.split()), label.casefold(),
    ))[:MAX_KEYWORDS]


def record_keywords(record: dict) -> list[str]:
    # Template summaries/rationale/topics describe selection rules, not subjects.
    return extract_keywords("\n".join(e["quote"] for e in record.get("evidence", [])),
                            record.get("original_name", ""))


def matches_keyword(record: dict, query: str) -> bool:
    """Match canonical labels or EN/DE aliases; multiple concepts require all."""
    available = record.get("keywords", [])
    if normalize(query) in {normalize(label) for label in PATTERNS}:
        return normalize(query) in {normalize(keyword) for keyword in available}
    wanted = extract_keywords(query)
    if wanted:
        return set(wanted) <= set(available)
    return normalize(query) in {normalize(keyword) for keyword in available}


def keyword_priority(text: str) -> int:
    """A bounded link bonus, with a stronger signal for medical subject matter."""
    keywords = extract_keywords(text)
    return min(8, sum(4 if keyword in MEDICAL else 1 for keyword in keywords))
