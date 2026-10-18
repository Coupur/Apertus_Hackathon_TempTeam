"""Step 2b — semantic enrichment: Apertus turns each crawled page into a structured record.

Anti-hallucination guard: every person / project / infrastructure item the model returns
must appear verbatim (case-insensitive) in the page text, otherwise it is dropped.
Without an LLM, a heuristic record (title + emails) is produced so the pipeline still runs.
"""
import json
from concurrent.futures import ThreadPoolExecutor

from . import config, llm

SYSTEM = """You extract structured facts from a university / research-centre web page.
Only use information explicitly written in the page. Never guess or invent names, roles or projects.
Return JSON with exactly these keys:
{
  "page_type": one of "person", "team_list", "research_group", "project", "infrastructure_service", "institute_overview", "other",
  "unit": name of the institute / department / group the page belongs to, or "",
  "summary": 1-2 sentence English summary of what this page offers (expertise, services),
  "expertise": list of research topics / methods / technologies (English, short terms),
  "keywords_de_en": list of synonyms and related terms in English and German that a non-expert might search for,
  "people": list of {"name": str, "role": str, "email": str, "expertise": [str]},
  "projects": list of project names,
  "infrastructure": list of instruments, facilities, platforms or services offered
}"""


def _in_text(item: str, text_low: str) -> bool:
    return bool(item) and item.lower().strip() in text_low


def _validate(rec: dict, page: dict) -> dict:
    text_low = (page["title"] + "\n" + page["text"]).lower()
    rec["people"] = [p for p in rec.get("people", []) if isinstance(p, dict) and _in_text(p.get("name", ""), text_low)]
    for p in rec["people"]:
        if p.get("email") and p["email"] not in page["emails"] and p["email"].lower() not in text_low:
            p["email"] = ""
    rec["projects"] = [x for x in rec.get("projects", []) if isinstance(x, str) and _in_text(x, text_low)]
    rec["infrastructure"] = [x for x in rec.get("infrastructure", []) if isinstance(x, str) and _in_text(x, text_low)]
    for k in ("expertise", "keywords_de_en"):
        rec[k] = [x for x in rec.get(k, []) if isinstance(x, str)][:30]
    return rec


def _heuristic(page: dict) -> dict:
    return {"page_type": "other", "unit": page["source_name"], "summary": page["text"][:300],
            "expertise": [], "keywords_de_en": [], "people": [], "projects": [], "infrastructure": [],
            "enriched_by": "heuristic"}


def enrich_page(page: dict) -> dict:
    rec = _heuristic(page)
    if config.LLM_ENABLED:
        try:
            out = llm.chat_json(SYSTEM, f"URL: {page['url']}\nTITLE: {page['title']}\n\n{page['text'][:6000]}")
            rec = _validate({**rec, **out}, page)
            rec["enriched_by"] = config.LLM_NAME
        except Exception as e:  # keep going; the heuristic record is still useful for search
            print(f"  ! enrich {page['url']}: {e}")
    return {"page_id": page["page_id"], "url": page["url"], "title": page["title"],
            "source_id": page["source_id"], "institution": page["institution"],
            "emails": page["emails"], **rec}


def enrich_all(workers: int = 4) -> int:
    pages = [json.loads(l) for l in open(config.PAGES_FILE, encoding="utf-8")]
    with ThreadPoolExecutor(workers) as ex, open(config.ENTITIES_FILE, "w", encoding="utf-8") as f:
        for i, rec in enumerate(ex.map(enrich_page, pages), 1):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if i % 25 == 0:
                print(f"  enriched {i}/{len(pages)}")
    return len(pages)
