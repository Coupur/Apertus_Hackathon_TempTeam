"""Keyword index (BM25) over pages + their LLM-enriched expertise terms. Pure Python, no services.

The enriched synonyms (keywords_de_en) are indexed together with the page text, so a lay
query like "glucose sensors" can hit a page that only says "CGM" on the site.
"""
import json
import math
import re
import unicodedata
from collections import Counter

from . import config

STOP = set("""a an and are as at be by for from has have in into is it of on or that the this to with we our
der die das und oder ein eine einer eines im in ist sind mit von zu zur zum fur auf als auch an bei des den dem
le la les et ou un une des du de en est pour avec sur au aux""".split())


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    toks = []
    for t in re.findall(r"[a-z0-9]{2,}", text):
        if t in STOP:
            continue
        if len(t) > 4 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        toks.append(t)
    return toks


class Index:
    def __init__(self, k1: float = 1.4, b: float = 0.75):
        self.k1, self.b = k1, b
        pages = {p["page_id"]: p for p in map(json.loads, open(config.PAGES_FILE, encoding="utf-8"))}
        ents = {}
        if config.ENTITIES_FILE.exists():
            ents = {e["page_id"]: e for e in map(json.loads, open(config.ENTITIES_FILE, encoding="utf-8"))}
        self.docs = []
        for pid, p in pages.items():
            e = ents.get(pid, {})
            people = " ".join(f"{x.get('name','')} {x.get('role','')} {' '.join(x.get('expertise', []))}"
                              for x in e.get("people", []))
            enriched = " ".join([e.get("unit", ""), e.get("summary", ""), " ".join(e.get("expertise", [])),
                                 " ".join(e.get("keywords_de_en", [])), " ".join(e.get("infrastructure", [])),
                                 " ".join(e.get("projects", [])), people])
            # title and enriched fields are repeated to weight them above body text
            toks = tokenize(f"{p['title']} {p['title']} {enriched} {enriched} {p['text']}")
            self.docs.append({"page": p, "entity": e, "tf": Counter(toks), "len": len(toks)})
        self.avgdl = sum(d["len"] for d in self.docs) / max(len(self.docs), 1)
        df = Counter(t for d in self.docs for t in d["tf"])
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def search(self, weighted_terms: dict[str, float], top_k: int = 40) -> list[tuple[float, dict, set]]:
        q = Counter()
        for phrase, w in weighted_terms.items():
            for t in tokenize(phrase):
                q[t] = max(q[t], w)
        hits = []
        for d in self.docs:
            score, matched = 0.0, set()
            for t, w in q.items():
                f = d["tf"].get(t)
                if not f:
                    continue
                norm = f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * d["len"] / self.avgdl))
                score += w * self.idf[t] * norm
                matched.add(t)
            if score > 0:
                hits.append((score, d, matched))
        hits.sort(key=lambda h: -h[0])
        return hits[:top_k]
