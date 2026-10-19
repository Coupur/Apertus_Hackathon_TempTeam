"""Step 4 — company request in, structured and source-backed matches out.

1. understand  Apertus rewrites the need into one English sentence + search terms (EN/DE synonyms)
2. retrieve    embedding search over the person and unit profiles
3. group       person hits are attached to their unit; at most MAX_PER_SOURCE units per site, so
               large institutions cannot crowd out small ones
4. judge       Apertus keeps only units that fit and writes the reason; it can only pick candidate
               ids it was given, so it cannot invent results. If none fits, the answer says so.
"""
import re

import numpy as np

from . import config, index, llm
from .models import CompanyRequest, Match, Person, SearchResponse

TOP_PROFILES = 80
MAX_CANDIDATES = 15
MAX_PER_SOURCE = 4
MIN_SCORE = 0.80  # e5 similarity below this is unrelated
ADMIN = re.compile(r"secretar|sekretariat|administra|housekeeping|reception|empfang|kanzlei|finance|finanz|hr\b", re.I)

UNDERSTAND_SYSTEM = """You help a regional economic development agency match a company's need to
research expertise at the University of Bern, ARTORG and Diabetes Center Berne.
Given the company's request, return JSON:
{"interpreted_need": one English sentence describing the expertise, service or infrastructure needed,
 "terms": up to 20 technical terms, synonyms, abbreviations and German translations that researchers
          would use on their websites for this topic}"""

JUDGE_SYSTEM = """You assess which research units can help a company. You get the company need and
numbered candidates extracted from public web pages. Use ONLY the candidate information.
Return JSON: {"matches": [{"id": candidate id, "relevance": 0-10, "reason": one or two sentences
explaining concretely why this unit fits the need, citing what the candidate information says}]}
Omit candidates that are not relevant (relevance < 5). Return {"matches": []} if none fits.
Do not invent people or facts."""


def _understand(req: CompanyRequest) -> tuple[str, list[str]]:
    interpreted, terms = req.need, list(req.keywords)
    if config.LLM_ENABLED:
        try:
            out = llm.chat_json(UNDERSTAND_SYSTEM, f"Sector: {req.sector or '-'}\nKeywords: {', '.join(req.keywords)}\n"
                                f"Looking for: {', '.join(req.looking_for) or 'any'}\nNeed: {req.need}", max_tokens=600)
            interpreted = out.get("interpreted_need") or interpreted
            terms += [t for t in out.get("terms", []) if isinstance(t, str)]
        except Exception as e:
            print(f"  ! understand: {e}")
    return interpreted, list(dict.fromkeys(terms))


def _candidates(interpreted: str, req: CompanyRequest, terms: list[str]) -> list[dict]:
    profiles, vectors = index.load()
    queries = list(dict.fromkeys([interpreted, req.need] + ([", ".join(terms)] if terms else [])))
    sims = (index.encode(queries, index.QUERY) @ vectors.T).max(axis=0)  # best of the phrasings
    units = {p["unit_id"]: p for p in profiles if p["kind"] == "unit"}

    groups, per_source = {}, {}
    for i in np.argsort(-sims)[:TOP_PROFILES]:
        if sims[i] < MIN_SCORE:
            break
        p = profiles[i]
        if p["unit_id"] not in groups:
            if per_source.get(p["source_id"], 0) >= MAX_PER_SOURCE:
                continue
            per_source[p["source_id"]] = per_source.get(p["source_id"], 0) + 1
            groups[p["unit_id"]] = {"unit": units[p["unit_id"]], "score": float(sims[i]), "people": {}}
        if p["kind"] == "person":
            groups[p["unit_id"]]["people"].setdefault(p["name"], p)
    return list(groups.values())[:MAX_CANDIDATES]


def _judge(interpreted: str, req: CompanyRequest, groups: list[dict]) -> dict[int, str] | None:
    if not config.LLM_ENABLED:
        return None
    lines = []
    for i, g in enumerate(groups):
        u = g["unit"]
        people = [f"{p['name']} ({p['role']}; {', '.join(p['expertise'][:4])})" for p in g["people"].values()][:6]
        lines.append(f"[{i}] {u['name']} ({u['institute']})\n  summary: {u['summary'][:400]}\n"
                     f"  expertise: {', '.join(u['expertise'][:15])}\n  infrastructure: {', '.join(u['infrastructure'][:8])}\n"
                     f"  matching people: {'; '.join(people) or '-'}")
    try:
        out = llm.chat_json(JUDGE_SYSTEM, f"Company need: {interpreted}\n(original: {req.need})\n\nCandidates:\n"
                            + "\n".join(lines), max_tokens=1500)
        return {int(m["id"]): m.get("reason", "") for m in out.get("matches", [])
                if str(m.get("id", "")).isdigit() and int(m["id"]) < len(groups) and m.get("relevance", 10) >= 5}
    except Exception as e:
        print(f"  ! judge: {e}")
        return None


def _people(g: dict) -> list[Person]:
    """People who matched the query first, then the unit's other listed people; admin staff last."""
    found = [Person(name=p["name"], role=p["role"], email=p["email"], expertise=p["expertise"][:8],
                    source_url=p["urls"][0]) for p in g["people"].values()]
    found += [Person(name=p["name"], role=p["role"], source_url=p["url"])
              for p in g["unit"]["people"] if p["name"] not in g["people"]]
    return sorted(found, key=lambda p: bool(ADMIN.search(p.role)))[:10]


def search(req: CompanyRequest) -> SearchResponse:
    interpreted, terms = _understand(req)
    groups = _candidates(interpreted, req, terms)
    reasons = _judge(interpreted, req, groups)
    if reasons is None:  # no LLM: similarity ranking only
        selected = [(g, f"Profile similar to the request (similarity {g['score']:.2f}); not verified by the LLM.")
                    for g in groups]
    else:
        selected = [(groups[i], reasons[i]) for i in sorted(reasons)]

    results = []
    for g, reason in selected[: req.max_results]:
        u = g["unit"]
        institution = u["institute"] if u["institution"] in u["institute"] else f"{u['institute']}, {u['institution']}"
        results.append(Match(unit=u["name"], institution=institution, people=_people(g), expertise=u["expertise"][:15],
                             projects=u["projects"][:10], infrastructure=u["infrastructure"][:10], reason=reason,
                             sources=u["urls"][:5], score=round(g["score"], 3)))
    note = "" if config.LLM_ENABLED else "LLM not configured: similarity search only, no query rewriting or reasons."
    if not results:
        note = note or "No verifiable source found for this need."
    return SearchResponse(request=req, interpreted_need=interpreted, search_terms=terms,
                          results=results, no_reliable_match=not results, note=note)
