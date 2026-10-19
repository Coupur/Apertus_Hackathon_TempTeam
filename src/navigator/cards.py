"""Stage: collection-net records + pages.jsonl -> data/index/to_embed.jsonl (what `embed` embeds).

One line per thing we can return:
  kind=person  one card per person record: name, role, group, unit, expertise, research text
  kind=unit    one card per unit record: its name plus the titles of its research/infra/project pages
  kind=page    200-word chunks of pages the net judged worth keeping (people pages are skipped,
               their content is already in the person cards)

Records are read from data/net/net.sqlite read-only, so this can run while the net is crawling.
"""
import json
import re
import sqlite3
from collections import defaultdict

from . import config
from .embed import INDEX_DIR, MODEL_NAME, _hash, make_chunks

NET_DB = config.DATA_DIR / "net" / "net.sqlite"
TO_EMBED = INDEX_DIR / "to_embed.jsonl"
SKIP_PAGE_TYPES = {"person_profile", "people_list"}  # covered by person cards
MIN_PAGE_RELEVANCE = 0.3
TOPIC_PAGE_TYPES = {"research", "infra", "project", "about"}
MAX_CARD_WORDS = 220


def _words(text: str, n: int) -> str:
    w = str(text).split()
    return " ".join(w[:n]) + (" …" if len(w) > n else "")


def _join(xs) -> str:
    if isinstance(xs, str):
        return xs
    return "; ".join(str(x) for x in xs if x)


def load_records(types=("person", "unit")) -> dict[str, list[dict]]:
    if not NET_DB.exists():
        return {t: [] for t in types}
    con = sqlite3.connect(f"file:{NET_DB.as_posix()}?mode=ro", uri=True, timeout=30)
    out = {}
    for t in types:
        rows = con.execute("SELECT id, source_id, url, quality, data FROM record WHERE type = ?", (t,)).fetchall()
        out[t] = [{"id": rid, "source_id": sid, "url": url, "quality": q, **json.loads(d)}
                  for rid, sid, url, q, d in rows]
    con.close()
    return out


# ---- who leads what, read from the sites' own group labels -------------------------------------
LEAD_RE = re.compile(r"\b(head|heads|leiter|leiterin|leitung|director|direktor|direktorin|chair|präsident"
                     r"|president|group leader|gruppenleiter|principal investigator|co-direktor)", re.I)
NAMES_PERSON_RE = re.compile(r"\b(prof|dr)\b\.?", re.I)
HEADED_BY_RE = re.compile(r"\((?:head|heads|leitung|leiter|leiterin)\s*:?\s*([^)]+)\)", re.I)
TITLE_TOKENS = {"prof", "dr", "pd", "med", "vet", "phil", "rer", "nat", "em", "dent", "habil"}


def _surname(name: str) -> str:
    tokens = [t for t in re.split(r"[\s.]+", name or "") if t and t.lower() not in TITLE_TOKENS]
    return tokens[-1].lower() if tokens else ""


def _role_texts(p: dict) -> list[str]:
    quoted = [e.get("quote") or "" for e in p.get("evidence", []) if e.get("field") in ("role", "group")]
    return [t for t in [p.get("role"), p.get("group"), *quoted] if t]


def is_lead(p: dict) -> bool:
    """A role/group label says this person leads something. A label that names someone else
    ("Space Weather (Head Prof. Dr. Lucia Kleint)" on a team member) doesn't count for them."""
    surname = _surname(p.get("name_clean") or p.get("name"))
    for t in _role_texts(p):
        if LEAD_RE.search(t) and (not NAMES_PERSON_RE.search(t) or (surname and surname in t.lower())):
            return True
    return bool(re.search(r"\bprof\b", p.get("name") or "", re.I))


def led_by(people: list[dict]) -> dict[str, list[str]]:
    """member person id -> ids of the heads its group label names, matched by surname on the same site."""
    by_surname = defaultdict(list)
    for p in people:
        by_surname[(p["source_id"], _surname(p.get("name_clean") or p.get("name")))].append(p)
    out = {}
    for p in people:
        heads = set()
        for t in _role_texts(p):
            for m in HEADED_BY_RE.finditer(t):
                for name in re.split(r",|\bund\b|\band\b|&", m.group(1)):
                    cands = by_surname.get((p["source_id"], _surname(name)), [])
                    cands = [c for c in cands if c["id"] != p["id"]]
                    if len(cands) > 1:  # same surname twice on one site: prefer the professor
                        cands = [c for c in cands if re.search(r"\bprof\b", c.get("name") or "", re.I)] or cands[:0]
                    heads.update(c["id"] for c in cands[:1])
        if heads:
            out[p["id"]] = sorted(heads)
    return out


def person_card(p: dict, unit_name: str) -> str:
    # a person listed on several team pages has several role/group quotes, e.g. "Co-DirektorInnen"
    # and "Space Geodesy (Leitung: Prof. Dr. A. Jäggi, ...)"; the second one says what they lead
    quoted = [e.get("quote") for e in p.get("evidence", []) if e.get("field") in ("role", "group")]
    head, seen = [], set()
    for x in [p.get("name_clean") or p.get("name"), p.get("role"), p.get("group"), *quoted,
              p.get("affiliation"), unit_name]:
        if x and x.lower() not in seen:
            seen.add(x.lower())
            head.append(x)
    parts = [". ".join(head[:8]) + "."]
    if p.get("expertise"):
        parts.append("Expertise: " + _join(p["expertise"]) + ".")
    if p.get("research_text"):
        parts.append("Research: " + _words(p["research_text"], 120))
    if p.get("projects"):
        parts.append("Projects: " + _join(p["projects"]) + ".")
    if not p.get("expertise") and not p.get("research_text") and p.get("summary"):
        parts.append(_words(_join(p["summary"]), 60))  # CV text, only when nothing better exists
    return _words("\n".join(parts), MAX_CARD_WORDS)


def unit_card(u: dict, topics: list[str]) -> str:
    text = f"{u['name']}. {u.get('institution', '')}. {u.get('host', '')}."
    if topics:
        text += "\nTopics: " + "; ".join(topics[:12]) + "."
    return text


def _evidence(rec: dict, n: int = 6) -> list[dict]:
    seen, out = set(), []
    for e in rec.get("evidence", []):
        k = (e.get("field"), e.get("quote"))
        if k in seen:
            continue
        seen.add(k)
        out.append({"field": e.get("field"), "quote": e.get("quote"), "url": e.get("url")})
        if len(out) == n:
            break
    return out


def build_cards() -> dict:
    pages = []
    if config.PAGES_FILE.exists():
        for line in open(config.PAGES_FILE, encoding="utf-8"):
            try:
                pages.append(json.loads(line))
            except json.JSONDecodeError:  # `pages` may be appending right now
                pass
    recs = load_records()

    # unit names per source (the first unit record of a site names it) and topic titles per source
    unit_name = {}
    for u in recs["unit"]:
        unit_name.setdefault(u["source_id"], u["name"])
    topics = defaultdict(list)
    for p in pages:
        if p.get("page_type") in TOPIC_PAGE_TYPES or p.get("page_type") is None:  # None: old crawl, untyped
            t = re.sub(r"\s+[-|–]\s+[^-|–]+$", "", p["title"]).strip()  # drop " - <site name>"
            if t and t not in topics[p["source_id"]] and t != unit_name.get(p["source_id"]):
                topics[p["source_id"]].append(t)

    # sites without a unit record (non-UniBE sites such as dcberne.com) get one from their pages,
    # otherwise they could never be returned as a unit
    site_pages = defaultdict(list)
    for p in pages:
        site_pages[p["source_id"]].append(p)
    for sid, ps in site_pages.items():
        if sid in unit_name or len(ps) < 3:
            continue
        root = "https://" + ps[0]["url"].split("/")[2] + "/"
        name = ps[0].get("source_name") or sid
        recs["unit"].append({"id": f"unit:site:{sid}", "source_id": sid, "url": root, "name": name,
                             "host": root.split("/")[2], "institution": ps[0].get("institution", ""),
                             "evidence": [{"field": "name (source registry)", "quote": name, "url": root}]})
        unit_name[sid] = name

    heads = led_by(recs["person"])
    items = []
    for p in recs["person"]:
        text = person_card(p, unit_name.get(p["source_id"], ""))
        meta = {k: p.get(k) for k in ("name", "name_clean", "role", "group", "affiliation", "email",
                                      "phone", "profile_url", "seen_on")}
        meta["lead"] = is_lead(p)
        meta["led_by"] = heads.get(p["id"], [])
        items.append({"chunk_id": _hash(f"{MODEL_NAME}\n{p['id']}\n{text}"), "kind": "person", "ref": p["id"],
                      "url": p.get("profile_url") or p["url"], "title": p.get("name_clean") or p["name"],
                      "institution": p.get("institution", ""), "source_id": p["source_id"], "text": text,
                      "meta": meta, "evidence": _evidence(p)})
    for u in recs["unit"]:
        text = unit_card(u, topics.get(u["source_id"], []))
        items.append({"chunk_id": _hash(f"{MODEL_NAME}\n{u['id']}\n{text}"), "kind": "unit", "ref": u["id"],
                      "url": u.get("url") or f"https://{u.get('host', '')}/", "title": u["name"],
                      "institution": u.get("institution", ""), "source_id": u["source_id"], "text": text,
                      "meta": {"name": u["name"], "host": u.get("host")}, "evidence": _evidence(u, 2)})
    # people of the same site whose full name appears in a page's text ("Contact Prof. Dr. Philippe Zysset")
    names_by_source = defaultdict(list)
    for p in recs["person"]:
        full = (p.get("name_clean") or "").strip()
        if len(full.split()) >= 2:
            first_last = full.lower()
            last_first = " ".join(full.split()[1:] + full.split()[:1]).lower()
            names_by_source[p["source_id"]].append((p["id"], first_last, last_first))

    n_pages = 0
    for p in pages:
        if p.get("page_type") in SKIP_PAGE_TYPES:
            continue
        if p.get("relevance") is not None and p["relevance"] < MIN_PAGE_RELEVANCE:
            continue
        n_pages += 1
        low = re.sub(r"\s+", " ", p["text"].lower())
        mentions = sorted({pid for pid, a, b in names_by_source.get(p["source_id"], []) if a in low or b in low})
        for c in make_chunks(p):
            items.append({**c, "kind": "page", "ref": p["page_id"], "page_type": p.get("page_type"),
                          "mentions": mentions})

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    with open(TO_EMBED, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    counts = defaultdict(int)
    for it in items:
        counts[it["kind"]] += 1
    return {"people": counts["person"], "units": counts["unit"], "page_chunks": counts["page"],
            "pages_used": n_pages, "pages_total": len(pages), "file": str(TO_EMBED)}
