"""Step 0: where does the company already show up in our Bern data?

A plain name search over data/pages.jsonl, no embeddings: awards it sponsors, funds its people sit
in, alumni who work there, partner lists. This is the clearest sign of what Bern means to the
company, and every hit is a page that names it. Only for name and URL inputs; an idea has no name.
"""
import json
import re

from .. import config
from ..retrieve import is_listing

LEGAL = re.compile(r"\b(holding|ag|sa|gmbh|ltd|inc|llc|plc|group|gruppe|international|corp|co)\b\.?", re.I)
# first words too common to stand for the company on their own ("Beyond Gravity" is not "Beyond")
COMMON = {"beyond", "swiss", "new", "the", "global", "smart", "digital", "bern", "berner", "health", "medical",
          "first", "open", "future", "green", "united", "general", "national", "life", "data", "bio", "tech",
          "energy", "best", "blue", "one", "next", "big", "star", "nova", "alpha", "prime"}
MAX_PAGES = 30


def name_terms(profile: dict) -> list[str]:
    """'Ypsomed Holding' -> ['Ypsomed Holding', 'Ypsomed']; 'Lindt & Sprüngli' -> [..., 'Lindt']."""
    name = profile["name"].strip()
    core = re.sub(r"\s+", " ", LEGAL.sub(" ", name)).strip(" &,-")
    terms = [name, core]
    first = core.split()[0] if core else ""
    if len(first) >= 4 and first.lower() not in COMMON:
        terms.append(first)
    return [t for t in dict.fromkeys(terms) if len(t) >= 3]


def _snippet(text: str, m: re.Match, width: int = 160) -> str:
    start, end = max(0, m.start() - width), min(len(text), m.end() + width)
    s = " ".join(text[start:end].split())
    return ("…" if start else "") + s + ("…" if end < len(text) else "")


def find_ties(profile: dict) -> dict:
    out = {"terms": [], "searched": str(config.PAGES_FILE), "pages_searched": 0, "count": 0, "pages": []}
    if profile.get("kind") == "idea":
        out["note"] = "an idea has no company name to search for"
        return out
    if not config.PAGES_FILE.exists():
        out["note"] = "no pages.jsonl yet: run `navigator pages`"
        return out
    terms = name_terms(profile)
    rx = re.compile(r"\b(" + "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True)) + r")\b", re.I)
    out["terms"] = terms
    lowered = [t.lower() for t in terms]
    hits = []
    with open(config.PAGES_FILE, encoding="utf-8") as f:
        for line in f:
            out["pages_searched"] += 1
            # cheap substring test before parsing; not the regex: in raw JSON a newline is the two
            # characters "\n", so "\nYpsomed" has no word boundary before the name
            low = line.lower()
            if not any(t in low for t in lowered):
                continue
            p = json.loads(line)
            text = p.get("text", "")
            found = list(rx.finditer(text)) or list(rx.finditer(p.get("title", "")))
            if not found:
                continue
            hits.append({"url": p["url"], "title": p.get("title", ""), "source_id": p.get("source_id", ""),
                         "institution": p.get("institution", ""), "mentions": len(found),
                         "term": found[0].group(1), "listing": is_listing(p["url"]),
                         "snippet": _snippet(text, found[0]) if text else p.get("title", "")})
    # pages about the company first, listing pages last
    hits.sort(key=lambda h: (h["listing"], -h["mentions"]))
    out["count"] = len(hits)
    out["pages"] = hits[:MAX_PAGES]
    return out


def format_ties(ties: dict) -> str:
    if ties.get("note"):
        return f"  existing ties: skipped ({ties['note']})"
    head = (f"  existing ties: {ties['count']} of {ties['pages_searched']} Bern pages name "
            f"{' / '.join(ties['terms'])}")
    lines = [head]
    for h in ties["pages"][:10]:
        lines += [f"    {h['source_id'][:16]:16} {h['url']}" + ("  (listing page)" if h["listing"] else ""),
                  f"      {h['snippet'][:220]}"]
    if ties["count"] > 10:
        lines.append(f"    … {ties['count'] - 10} more in queries.json")
    return "\n".join(lines)
