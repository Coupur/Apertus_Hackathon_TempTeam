"""Step 1 -> 3: company request in, structured and source-backed matches out.

1. understand  — Apertus rewrites the company need into search terms + EN/DE synonyms
2. retrieve    — BM25 over crawled + enriched pages
3. group       — pages are grouped into units (institute / group), people & infra merged
4. judge       — Apertus keeps only relevant units and writes a reason per match;
                 it can only cite candidate ids we gave it, so it cannot invent results
"""
from collections import defaultdict
from functools import lru_cache

from . import config, llm
from .index import Index, tokenize
from .models import CompanyRequest, Match, Person, SearchResponse

MIN_SCORE = 3.0  # below this, BM25 evidence is too weak to call it a match

UNDERSTAND_SYSTEM = """You help a regional economic development agency match a company's need to
research expertise at the University of Bern, ARTORG and Diabetes Center Berne.
Given the company's request, return JSON:
{"interpreted_need": one English sentence,
 "core_terms": the 3-6 most important technical terms,
 "related_terms": up to 20 synonyms, scientific terms, abbreviations and German translations
                  that researchers would use on their websites for the same topic}"""

JUDGE_SYSTEM = """You assess which research units can help a company. You get the company need and
numbered candidates extracted from public web pages. Use ONLY the candidate information.
Return JSON: {"matches": [{"id": candidate id, "relevance": 0-10, "reason": one or two sentences
explaining concretely why this unit fits the need, citing what the page says}]}
Omit candidates that are not relevant (relevance < 4). Do not invent people or facts."""


@lru_cache(maxsize=1)
def get_index() -> Index:
    return Index()


def _understand(req: CompanyRequest) -> tuple[str, dict[str, float]]:
    base = " ".join([req.need, *req.keywords])
    terms = {base: 1.0}
    interpreted = req.need
    if config.LLM_ENABLED:
        try:
            ctx = f"Company: {req.company_name or '-'}\nSector: {req.sector or '-'}\nKeywords: {', '.join(req.keywords)}\n" \
                  f"Looking for: {', '.join(req.looking_for) or 'any'}\nNeed: {req.need}"
            out = llm.chat_json(UNDERSTAND_SYSTEM, ctx, max_tokens=600)
            interpreted = out.get("interpreted_need") or interpreted
            for t in out.get("core_terms", []):
                terms[t] = 1.2
            for t in out.get("related_terms", []):
                terms.setdefault(t, 0.6)
        except Exception as e:
            print(f"  ! understand: {e}")
    return interpreted, terms


def _group(hits) -> list[dict]:
    groups: dict[tuple, dict] = {}
    for score, d, matched in hits:
        p, e = d["page"], d["entity"]
        key = (p["source_id"], (e.get("unit") or p["source_name"]).strip().lower())
        g = groups.setdefault(key, {"unit": e.get("unit") or p["source_name"], "institution": p["institution"],
                                    "score": 0.0, "pages": [], "people": {}, "expertise": [], "projects": [],
                                    "infrastructure": [], "summaries": [], "matched": set()})
        g["score"] = max(g["score"], score) + 0.1 * min(g["score"], score)  # extra pages add a little
        g["pages"].append(p["url"])
        g["matched"] |= matched
        g["summaries"].append(e.get("summary") or p["text"][:300])
        for person in e.get("people", []):
            g["people"].setdefault(person["name"], Person(source_url=p["url"], **{
                k: person.get(k) or ("" if k != "expertise" else []) for k in ("name", "role", "email", "expertise")}))
        for k in ("expertise", "projects", "infrastructure"):
            g[k] += [x for x in e.get(k, []) if x not in g[k]]
    return sorted(groups.values(), key=lambda g: -g["score"])


def _judge(interpreted: str, req: CompanyRequest, groups: list[dict]) -> dict[int, str] | None:
    if not config.LLM_ENABLED:
        return None
    lines = []
    for i, g in enumerate(groups):
        lines.append(f"[{i}] {g['unit']} ({g['institution']})\n  summary: {' | '.join(g['summaries'][:2])[:500]}\n"
                     f"  expertise: {', '.join(g['expertise'][:15])}\n  infrastructure: {', '.join(g['infrastructure'][:8])}\n"
                     f"  people: {', '.join(list(g['people'])[:8])}")
    try:
        out = llm.chat_json(JUDGE_SYSTEM, f"Company need: {interpreted}\n(original: {req.need})\n\nCandidates:\n"
                            + "\n".join(lines), max_tokens=1500)
        return {int(m["id"]): m.get("reason", "") for m in out.get("matches", [])
                if str(m.get("id", "")).isdigit() and int(m["id"]) < len(groups) and m.get("relevance", 10) >= 4}
    except Exception as e:
        print(f"  ! judge: {e}")
        return None


def search(req: CompanyRequest) -> SearchResponse:
    interpreted, terms = _understand(req)
    hits = get_index().search(terms, top_k=60)
    groups = [g for g in _group(hits) if g["score"] >= MIN_SCORE][: max(req.max_results * 2, 15)]

    reasons = _judge(interpreted, req, groups)
    if reasons is not None:
        selected = [(groups[i], r) for i, r in reasons.items()]
        selected.sort(key=lambda x: -x[0]["score"])
    else:
        query_toks = {t for k in terms for t in tokenize(k)}
        selected = [(g, "Keyword match on: " + ", ".join(sorted(g["matched"] & query_toks)[:10])) for g in groups]

    results = [Match(unit=g["unit"], institution=g["institution"], people=list(g["people"].values())[:10],
                     expertise=g["expertise"][:15], projects=g["projects"][:10],
                     infrastructure=g["infrastructure"][:10], reason=reason,
                     sources=list(dict.fromkeys(g["pages"]))[:5], score=round(g["score"], 2))
               for g, reason in selected[: req.max_results]]

    note = "" if config.LLM_ENABLED else "LLM not configured: keyword search only, no query expansion or reasons."
    return SearchResponse(request=req, interpreted_need=interpreted, search_terms=list(terms),
                          results=results, no_reliable_match=not results,
                          note=note or ("No verifiable source found for this need." if not results else ""))
