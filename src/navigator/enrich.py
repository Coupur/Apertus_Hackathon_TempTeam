"""Step 2 — Apertus turns each crawled page into a structured record: unit, people, expertise,
projects, infrastructure, plus EN/DE synonyms for lay-term search.

Anti-hallucination: people, their roles and emails, projects and infrastructure must appear verbatim
in the page text, otherwise they are dropped (validate() runs again when the index is built).
Resumable: pages that already have an Apertus record are skipped; new records are appended.
"""
import json
from concurrent.futures import ThreadPoolExecutor

from . import config, llm
from .crawl import keep

SYSTEM = """You extract structured facts from a university / research-centre web page.
Only use information explicitly written in the page. Never guess or invent names, roles or projects.
Return JSON with exactly these keys:
{
  "page_type": one of "person", "team_list", "research_group", "project", "infrastructure_service", "institute_overview", "other",
  "unit": the most specific research group, lab, division or service the page belongs to
          (e.g. "Artificial Intelligence in Medical Imaging"), or "" if the page is about the whole institute,
  "institute": the institute, centre, department or clinic that unit belongs to (e.g. "ARTORG Center for Biomedical Engineering Research"),
  "summary": 1-2 sentence English summary of what this page offers (expertise, services),
  "expertise": list of research topics / methods / technologies (English, short terms),
  "keywords_de_en": list of synonyms and related terms in English and German that a non-expert might search for,
  "people": list of {"name": str, "role": str exactly as written on the page, "email": str, "expertise": [str]},
  "projects": list of project names,
  "infrastructure": list of instruments, facilities, platforms or services offered
}"""


def _on_page(item, text_low: str) -> bool:
    return isinstance(item, str) and bool(item.strip()) and item.lower().strip() in text_low


def validate(rec: dict, page: dict) -> dict:
    """Keep only what the page itself says about people, projects and infrastructure."""
    text_low = (page["title"] + "\n" + page["text"]).lower()
    people = []
    for p in rec.get("people", []):
        if isinstance(p, dict) and _on_page(p.get("name"), text_low):
            people.append({"name": p["name"].strip(),
                           "role": p["role"].strip() if _on_page(p.get("role"), text_low) else "",
                           "email": p["email"] if _on_page(p.get("email"), text_low) else "",
                           "expertise": [x for x in p.get("expertise", []) if isinstance(x, str)][:10]})
    rec["people"] = people
    for k in ("projects", "infrastructure"):
        rec[k] = [x for x in rec.get(k, []) if _on_page(x, text_low)]
    for k in ("expertise", "keywords_de_en"):
        rec[k] = [x for x in rec.get(k, []) if isinstance(x, str)][:30]
    return rec


def enrich_page(page: dict) -> dict:
    rec = {"page_id": page["page_id"], "url": page["url"], "enriched_by": "failed"}
    try:
        # team lists produce long JSON; a short limit cuts it off mid-object
        out = llm.chat_json(SYSTEM, f"URL: {page['url']}\nTITLE: {page['title']}\n\n{page['text'][:6000]}",
                            max_tokens=4000)
        rec.update(validate(out, page), enriched_by=config.LLM_NAME)
    except Exception as e:  # recorded as failed and retried on the next run
        print(f"  ! enrich {page['url']}: {str(e)[:120]}")
    return rec


def load() -> dict[str, dict]:
    """page_id -> latest successful record."""
    return {r["page_id"]: r for r in config.read_jsonl(config.ENTITIES_FILE) if r.get("enriched_by") not in ("failed", "heuristic")}


def enrich_all(workers: int = 8, limit: int | None = None, only: list[str] | None = None) -> int:
    done = load()
    pages = config.read_jsonl(config.PAGES_FILE)
    urls = {p["url"] for p in pages}
    todo = [p for p in pages if p["page_id"] not in done and keep(p, urls) and (not only or p["source_id"] in only)]
    todo = todo[:limit] if limit else todo
    print(f"{len(done)} pages already enriched, {len(todo)} to go")
    with ThreadPoolExecutor(workers) as ex, open(config.ENTITIES_FILE, "a", encoding="utf-8") as f:
        for i, rec in enumerate(ex.map(enrich_page, todo), 1):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            if i % 50 == 0:
                print(f"  {i}/{len(todo)}", flush=True)
    return len(todo)
