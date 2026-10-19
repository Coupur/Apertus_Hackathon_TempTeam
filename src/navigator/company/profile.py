"""Step 2: what the company does and what it wants, from the collected pages.

With Apertus every list item carries a quote. An item whose quote is not on the page it names (or
on any collected page) moves to `dropped`, so the lists hold only what the company says itself.
Without an LLM, rules fill the same fields: the meta description, lexicon topics and the sentences
that state a mission, goal, want or challenge.
"""
import re

from .. import config, llm
from .lexicon import find_topics
from .prompts import PROFILE_SYSTEM

LIST_FIELDS = ("products", "technologies", "markets", "aspirations", "goals", "wants", "challenges")
CONTEXT_CHARS = 24000
PAGE_WEIGHT = {"sustainability": 0.3, "careers": 0.3, "news": 0.3, "wikidata": 2.0}

BERN_PLACES = re.compile(r"\b(Bern|Berne|Biel|Bienne|Thun|Burgdorf|Langenthal|Köniz|Ittigen|Ostermundigen|Worb"
                         r"|Münsingen|Lyss|Interlaken|Zollikofen|Muri bei Bern|Liebefeld)\b")
SENTENCE_RULES = {
    "aspirations": r"\b(mission|vision|purpose|ambition|we believe|we strive|our aim|unsere mission|unsere vision"
                   r"|wir glauben|leitbild|we want to)\b",
    "goals": r"\b(aims? to|goals?|targets?|by 20[2-5]\d|plans? to|planning to|expand|expansion|launch|scale up"
             r"|net[- ]zero|reduce|increase|strategy 20\d\d|ziel|bis 20[2-5]\d|ausbau|wachsen|erweitern|reduzieren)\b",
    "wants": r"\b(hiring|join (our|the) team|open positions|vacanc\w+|we are looking for|looking for|seeking|partner"
             r"(s|ship)? with|investors?|pilot (customers?|partners?|projects?)|collaborat\w+|wir suchen"
             r"|offene stellen|bewirb|zusammenarbeit)\b",
    "challenges": r"\b(challenges?|problems?|difficult\w*|unmet need|shortage|lack of|bottleneck|herausforderung\w*"
                  r"|mangel)\b",
}
NOISE = re.compile(r"cookie|privacy|datenschutz|newsletter|javascript|browser|copyright|all rights reserved", re.I)
HIRING = re.compile(r"hiring|open positions|vacanc|join (our|the) team|offene stellen|bewirb|karriere|career", re.I)
STARTUP = re.compile(r"start-?up|spin-?off|founded in 20(1[5-9]|2\d)|gegründet 20(1[5-9]|2\d)|seed (round|funding)"
                     r"|series a", re.I)
CORPORATE = re.compile(r"\b(SIX Swiss Exchange|SIX: ?[A-Z]{3,5}|listed on|subsidiaries|worldwide|weltweit|global leader"
                       r"|world leader|in over \d+ countries|\d[\d,']* employees)\b", re.I)


def _norm(s: str) -> str:
    return re.sub(r"\W+", " ", s.casefold()).strip()


def _on_page(quote: str, text: str) -> bool:
    """Verbatim (ignoring case, punctuation and spacing), or 60% of its word triples appear on the page."""
    q, t = _norm(quote), _norm(text)
    if len(q) < 8:
        return False
    if q in t:
        return True
    words = q.split()
    grams = [" ".join(words[i:i + 3]) for i in range(len(words) - 2)]
    return bool(grams) and sum(g in t for g in grams) / len(grams) >= 0.6


def _sentences(text: str) -> list[str]:
    out = []
    for line in text.split("\n"):
        for s in re.split(r"(?<=[.!?])\s+", line):
            s = s.strip()
            if 40 <= len(s) <= 300 and len(s.split()) >= 6 and not NOISE.search(s):
                out.append(s)
    return out


def _base(col: dict) -> dict:
    fx = col.get("facts") or {}
    locations = list(dict.fromkeys(fx.get("headquarters", []) + fx.get("country", [])))
    return {"name": col["name"], "website": col.get("website"), "input": col["input"], "kind": col["kind"],
            "summary": "", "sector": ", ".join(fx.get("industry", [])), "stage": "unknown", "locations": locations,
            "in_bern": None, **{f: [] for f in LIST_FIELDS}, "topics": [], "dropped": []}


def _in_bern(p: dict, col: dict) -> bool | None:
    """From the headquarters or a postal address on the site, not from any mention of Bern:
    a Zurich company may well write about its Bern shop."""
    if any(BERN_PLACES.search(loc) for loc in p["locations"]):
        return True
    if col["kind"] == "idea":
        return True if BERN_PLACES.search(col["input"]) else None
    addresses = (col.get("meta") or {}).get("addresses", [])
    if any(a["bern"] for a in addresses):
        return True
    return False if p["locations"] or addresses else None


def _strong_text(col: dict) -> str:
    meta = col.get("meta") or {}
    fx = col.get("facts") or {}
    return " ".join([meta.get("title", ""), meta.get("description", ""), " ".join(meta.get("headings", [])),
                     fx.get("description", ""), " ".join(fx.get("industry", []))]
                    + [p["title"] for p in col["pages"]])


def _weighted(col: dict) -> list[tuple[str, float]]:
    """Page texts with weights: what a company sells counts more than its news, jobs or ESG pages."""
    return [(p["text"], PAGE_WEIGHT.get(p["kind"], 1.0)) for p in col["pages"]]


def _find(col: dict):
    # a one-line idea names each topic once; a website repeats what matters
    return find_topics(_weighted(col), _strong_text(col), min_hits=1 if col["kind"] == "idea" else 3)


def _topics(col: dict) -> list[dict]:
    return [{"key": t.key, "label": t.label, "hits": n} for t, n in _find(col)]


# ---------- Apertus ----------

def _context(col: dict) -> str:
    per_page = max(1500, CONTEXT_CHARS // max(1, len(col["pages"])))
    parts = [f"[{p['id']}] {p['title']} ({p['url'] or 'given by user'})\n{p['text'][:per_page]}" for p in col["pages"]]
    meta = col.get("meta") or {}
    if meta.get("description"):
        parts.insert(0, f"Site description: {meta['description']}")
    return "\n\n".join(parts)


def _llm_profile(col: dict) -> dict:
    p = _base(col)
    out = llm.chat_json(PROFILE_SYSTEM, _context(col), max_tokens=2000)
    pages = {pg["id"]: pg for pg in col["pages"]}
    for k in ("summary", "sector", "stage"):
        if isinstance(out.get(k), str) and out[k].strip():
            p[k] = out[k].strip()
    if isinstance(out.get("name"), str) and out["name"].strip() and col["kind"] != "name":
        p["name"] = out["name"].strip()
    p["locations"] = list(dict.fromkeys(p["locations"] + [str(x) for x in out.get("locations", []) if x]))
    for field in LIST_FIELDS:
        for item in out.get(field) or []:
            if not isinstance(item, dict) or not str(item.get("value", "")).strip():
                continue
            value, quote = str(item["value"]).strip(), str(item.get("quote", "")).strip()
            page = pages.get(str(item.get("page", "")).strip())
            hit = page if page and _on_page(quote, page["text"]) else \
                next((pg for pg in col["pages"] if _on_page(quote, pg["text"])), None)
            if hit:
                p[field].append({"value": value, "quote": quote, "url": hit["url"], "page": hit["id"]})
            else:
                p["dropped"].append({"field": field, "value": value, "quote": quote, "why": "quote not on page"})
    return p


# ---------- rules ----------

def _rules_profile(col: dict) -> dict:
    p = _base(col)
    meta = col.get("meta") or {}
    fx = col.get("facts") or {}
    wiki = next((pg["text"] for pg in col["pages"] if pg["kind"] == "wikipedia"), "")
    first_wiki = re.split(r"(?<=[.!?])\s", wiki, maxsplit=1)[0] if wiki else ""
    given = next((pg["text"] for pg in col["pages"] if pg["kind"] == "input"), "")
    p["summary"] = meta.get("description") or first_wiki or fx.get("description") or given[:300]

    seen = set()
    for pg in col["pages"]:
        if pg["kind"] == "wikidata":
            continue
        for s in _sentences(pg["text"]):
            key = _norm(s)
            if key in seen:
                continue
            for field, rx in SENTENCE_RULES.items():
                if len(p[field]) < 5 and re.search(rx, s, re.I):
                    p[field].append({"value": s, "quote": s, "url": pg["url"], "page": pg["id"]})
                    seen.add(key)
                    break

    all_text = "\n".join(pg["text"] for pg in col["pages"])
    for t, _ in _find(col):
        pg, s = next(((pg, s) for pg in col["pages"] for s in _sentences(pg["text"]) if t.rx.search(s)), (None, ""))
        p["technologies"].append({"value": t.label, "quote": s, "url": pg["url"] if pg else "",
                                  "page": pg["id"] if pg else ""})
    if not p["sector"] and p["technologies"]:
        p["sector"] = p["technologies"][0]["value"]

    if fx.get("employees"):
        p["stage"] = "corporate" if fx["employees"] >= 250 else "sme"
    elif CORPORATE.search(all_text):  # before startup: corporates also write about "start-ups" they work with
        p["stage"] = "corporate"
    elif STARTUP.search(all_text):
        p["stage"] = "startup"
    return p


def build_profile(col: dict) -> dict:
    p = None
    if config.LLM_ENABLED:
        try:
            p = _llm_profile(col)
            p["generated_by"] = f"apertus:{config.LLM_NAME}"
        except Exception as e:  # endpoint down or JSON broken: fall back, do not stop the pipeline
            col["trace"].append(f"profile LLM failed ({e}); using rules")
    if p is None:
        p = _rules_profile(col)
        p["generated_by"] = "rules"
    p["topics"] = _topics(col)
    p["in_bern"] = _in_bern(p, col)
    p["hiring"] = any(pg["kind"] == "careers" for pg in col["pages"]) or \
        any(HIRING.search(w["value"]) for w in p["wants"])
    return p
