"""Step 3 — merge the per-page records into one profile per person and one per unit, then embed them.

entities.jsonl -> profiles.jsonl + vectors.npy. Search runs over these profiles, so every hit is
already a structured result that carries the source URLs it came from.
"""
import json
import re
from collections import Counter

import numpy as np

from . import config, enrich
from .crawl import keep

TITLES = {"prof", "dr", "pd", "med", "phil", "ing", "em", "habil", "rer", "nat", "dent", "vet", "sc",
          "phd", "ph.d", "msc", "bsc", "md", "dipl", "associate", "assistant", "apl"}
UNIT_FILLER = re.compile(r"\b(the|group|lab|laboratory|labor|research|forschungsgruppe|gruppe)\b")
# e5 models expect these prefixes
PASSAGE, QUERY = ("passage: ", "query: ") if "e5" in config.EMBED_MODEL else ("", "")

_model = None
_index = None


def encode(texts: list[str], prefix: str) -> np.ndarray:
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer  # slow import, only when needed
        _model = SentenceTransformer(config.EMBED_MODEL)
    return np.asarray(_model.encode([prefix + t for t in texts], batch_size=64, normalize_embeddings=True),
                      dtype=np.float32)


def name_key(name: str) -> str:
    """'Prof. Dr. med. Jane Doe' and 'Jane Doe' are the same person."""
    return " ".join(t for t in re.split(r"[\s,]+", name.lower()) if t and t.strip(".") not in TITLES)


def acronym(name: str) -> str:
    """'Acoustic Robotics Systems Lab (ARSL)', 'ARSL', 'HRL (Hearing Research Lab)', 'CODE - ...' -> the acronym."""
    s = name.strip()
    m = (re.search(r"\(([A-Za-z]{2,8})\)\s*(group|lab|laboratory)?$", s, re.I) or re.fullmatch(r"([A-Z]{2,8})", s)
         or re.match(r"([A-Z]{2,8})(?:\s*\(|\s+[-–]\s)", s))
    return m.group(1).lower() if m else ""


def words(name: str) -> str:
    """'Section Paleoecology', 'Paleoecology Section' -> 'paleoecology section' (filler words and brackets dropped)."""
    w = UNIT_FILLER.sub(" ", re.sub(r"\(.*?\)", " ", name.lower().replace("&", " and "))).split()
    return " ".join(sorted(w)) or name.lower().strip()


def _add(lst: list, items) -> None:
    lst += [x for x in items or [] if x and x not in lst]


def build_profiles() -> list[dict]:
    pages = {p["page_id"]: p for p in config.read_jsonl(config.PAGES_FILE)}
    urls = {p["url"] for p in pages.values()}
    records = [(enrich.validate(r, pages[pid]), pages[pid]) for pid, r in enrich.load(include_heuristic=True).items()
               if pid in pages and keep(pages[pid], urls)]

    def unit_name(rec, page):
        return (rec.get("unit") or rec.get("institute") or page["source_name"]).strip()

    # Apertus spells a unit differently on different pages; units meet on their acronym when one
    # spelling has it ('Cardiovascular Engineering' + 'Cardiovascular Engineering (CVE)'), else on their words
    alias = {(page["source_id"], words(n)): a for rec, page in records
             if (a := acronym(n := unit_name(rec, page)))}

    def unit_id(rec, page):
        n = unit_name(rec, page)
        return f"{page['source_id']}|{acronym(n) or alias.get((page['source_id'], words(n)), words(n))}"

    units, people, names = {}, {}, Counter()
    for rec, page in records:
        institute = (rec.get("institute") or page["source_name"]).strip()
        uid = unit_id(rec, page)
        names[(uid, unit_name(rec, page))] += 1
        u = units.setdefault(uid, {"kind": "unit", "unit_id": uid, "institute": institute,
                                   "institution": page["institution"], "source_id": page["source_id"],
                                   "summary": rec.get("summary", ""), "expertise": [], "keywords": [],
                                   "projects": [], "infrastructure": [], "people": [], "urls": []})
        _add(u["expertise"], rec["expertise"])
        _add(u["keywords"], rec["keywords_de_en"])
        _add(u["projects"], rec["projects"])
        _add(u["infrastructure"], rec["infrastructure"])
        _add(u["urls"], [page["url"]])

        own_page = rec.get("page_type") == "person" and len(rec["people"]) == 1
        for person in rec["people"]:
            pid = f"{page['source_id']}|{name_key(person['name'])}"
            p = people.setdefault(pid, {"kind": "person", "name": person["name"], "role": "", "email": "",
                                        "unit_id": uid, "institute": institute, "institution": page["institution"],
                                        "source_id": page["source_id"], "expertise": [], "keywords": [],
                                        "projects": [], "urls": []})
            if own_page:  # the person's own page is the best source for unit and expertise
                p.update(unit_id=uid, role=person["role"] or p["role"])
                _add(p["expertise"], rec["expertise"])
                _add(p["keywords"], rec["keywords_de_en"])
                _add(p["projects"], rec["projects"])
            p["role"] = p["role"] or person["role"]
            p["email"] = p["email"] or person["email"]
            _add(p["expertise"], person["expertise"])
            _add(p["urls"], [page["url"]])
            if person["name"] not in [x["name"] for x in u["people"]]:
                u["people"].append({"name": person["name"], "role": person["role"], "url": page["url"]})

    # display name of a unit: the spelling most of its pages use
    for (uid, name), _ in reversed(names.most_common()):
        units[uid]["name"] = name
    for prof in list(units.values()) + list(people.values()):
        prof["unit"] = units[prof["unit_id"]]["name"]
        prof["text"] = profile_text(prof)
    return list(units.values()) + list(people.values())


def profile_text(p: dict) -> str:
    """What gets embedded: name, affiliation and expertise, kept short so the topic dominates."""
    where = p["unit"] if p["unit"] == p["institute"] else f"{p['unit']}, {p['institute']}"
    parts = [p["name"] + (f" ({p['role']})" if p.get("role") else ""), where, p.get("summary", "")]
    for label, k, n in (("Expertise", "expertise", 25), ("Related", "keywords", 25), ("Infrastructure", "infrastructure", 15)):
        if p.get(k):
            parts.append(f"{label}: " + ", ".join(p[k][:n]))
    return "\n".join(x for x in parts if x)


def build() -> dict:
    profiles = build_profiles()
    vectors = encode([p["text"] for p in profiles], PASSAGE)
    with open(config.PROFILES_FILE, "w", encoding="utf-8") as f:
        for p in profiles:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    np.save(config.VECTORS_FILE, vectors)
    n_people = sum(p["kind"] == "person" for p in profiles)
    return {"profiles": len(profiles), "people": n_people, "units": len(profiles) - n_people,
            "sources": len({p["source_id"] for p in profiles})}


def load() -> tuple[list[dict], np.ndarray]:
    global _index
    if _index is None:
        if not config.VECTORS_FILE.exists():
            raise RuntimeError("No index yet: run `python -m navigator index` first")
        _index = config.read_jsonl(config.PROFILES_FILE), np.load(config.VECTORS_FILE)
    return _index
