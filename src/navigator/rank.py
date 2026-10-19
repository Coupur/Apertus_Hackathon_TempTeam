"""Query -> ranked resources: people, units and pages, each with the evidence that put it there.

One embedding search over every line in the index (person cards, unit cards, page chunks), then a
roll-up so the answer is resources, not text snippets:
  person  best of: its own card, or a page that lists or names it (only pages with <= max_people_per_page people)
  unit    best of: its own card, or any page of its site
  page    best chunk per URL
  head    a team member's group label often names the head ("Space Weather (Head Prof. Dr. L. Kleint)");
          the head gets the member's score too, so the leader of a matching team surfaces
A small boost for people whose own role or group says they lead something ("Head", "Leitung", "Prof.").
If the best score is under the floor, the result says no_reliable_match instead of guessing.
"""
import re
import time
from collections import defaultdict
from dataclasses import asdict, dataclass

import numpy as np

from .retrieve import Retriever

LEAD_RE = re.compile(r"\b(head|leiter|leiterin|leitung|director|direktor|direktorin|chair|präsident|president"
                     r"|group leader|gruppenleiter|principal investigator|co-direktor)", re.I)
PROF_RE = re.compile(r"\bprof\b", re.I)


@dataclass
class RankConfig:
    kinds: tuple = ("person", "unit", "page")  # which index lines to search
    rollup: bool = True              # credit page hits to the people and units on them
    max_people_per_page: int = 8     # a team list of 40 people says little about each of them
    page_penalty: float = 0.01       # a page hit counts a little less than a person's own card
    lead_boost: float = 0.01         # added for leads; 0 turns it off
    head_credit: bool = True         # pass a member's score up to the head its group label names
    head_penalty: float = 0.005
    floor: float = 0.85              # best score under this -> no_reliable_match; tuned on 3 no-answer questions
    window: float = 0.04             # results within this of the best are marked confident
    candidates: int = 400            # index lines considered per query


def norm_url(u: str) -> str:
    u = (u or "").strip().lower().split("#")[0].split("?")[0]
    u = re.sub(r"^https?://", "", u).removeprefix("www.")
    u = re.sub(r"/(index(_eng|_ger)?\.html?)?$", "", u)
    return u.rstrip("/")


def _is_lead(meta: dict) -> bool:
    if "lead" in meta:  # computed by `cards` from all of the record's role/group quotes
        return bool(meta["lead"])
    text = " ".join(str(meta.get(k) or "") for k in ("role", "group", "affiliation"))
    return bool(LEAD_RE.search(text)) or bool(PROF_RE.search(meta.get("name") or ""))


class Ranker:
    def __init__(self, cfg: RankConfig | None = None):
        self.cfg = cfg or RankConfig()
        self.r = Retriever()
        self.chunks = self.r.chunks
        self.kind = np.array([c.get("kind", "page") for c in self.chunks])
        self.people_on_url = defaultdict(set)   # normalised page URL -> person chunk indexes
        self.unit_of_source = {}                # source_id -> unit chunk index
        self.person_of_ref = {}                 # person record id -> chunk index
        for i, c in enumerate(self.chunks):
            k = c.get("kind", "page")
            if k == "person":
                self.person_of_ref[c.get("ref")] = i
                m = c.get("meta", {})
                for u in (m.get("seen_on") or []) + [m.get("profile_url") or ""]:
                    if u:
                        self.people_on_url[norm_url(u)].add(i)
            elif k == "unit":
                self.unit_of_source.setdefault(c["source_id"], i)
        self.mask = np.isin(self.kind, list(self.cfg.kinds))

    # ---- result entries -------------------------------------------------------------------
    def _person(self, i: int, score: float, via: dict) -> dict:
        c = self.chunks[i]
        m = c.get("meta", {})
        slug = (m.get("name_clean") or "").lower().split()[-1:] or [""]
        profile_urls = [u for u in (m.get("seen_on") or []) if slug[0] and slug[0] in u.lower()]
        keys = {f"person:{c.get('ref', '')}"}  # always present, even without email or profile URL
        if m.get("email"):
            keys.add(f"email:{m['email'].lower()}")
        keys |= {f"url:{norm_url(u)}" for u in [m.get("profile_url")] + profile_urls if u}
        return {"kind": "person", "name": m.get("name_clean") or c["title"], "title": m.get("name"),
                "role": m.get("role"), "group": m.get("group"), "affiliation": m.get("affiliation"),
                "email": m.get("email"), "url": c["url"], "source_id": c["source_id"],
                "score": round(score, 4), "lead": _is_lead(m), "via": via,
                "evidence": c.get("evidence", []), "keys": sorted(keys)}

    def _unit(self, i: int, score: float, via: dict) -> dict:
        c = self.chunks[i]
        return {"kind": "unit", "name": c["title"], "url": c["url"], "source_id": c["source_id"],
                "score": round(score, 4), "via": via, "evidence": c.get("evidence", []),
                "keys": sorted({f"unit:{c['source_id']}", f"url:{norm_url(c['url'])}"})}

    def _page(self, i: int, score: float) -> dict:
        c = self.chunks[i]
        snippet = c["text"].split("\n", 1)[-1][:300]
        return {"kind": "page", "name": c["title"], "url": c["url"], "source_id": c["source_id"],
                "page_type": c.get("page_type"), "score": round(score, 4), "snippet": snippet,
                "keys": sorted({f"url:{norm_url(c['url'])}", f"unit:{c['source_id']}"})}

    # ---- the search -----------------------------------------------------------------------
    def ask(self, query: str, k: int = 10) -> dict:
        cfg = self.cfg
        t0 = time.perf_counter()
        s = self.r.scores([query])[0]
        s = np.where(self.mask, s, -1.0)
        order = np.argsort(-s)[:cfg.candidates]
        best = float(s[order[0]])

        people, units, pages = {}, {}, {}   # index -> (score, via)

        def offer(d, i, score, via):
            if i not in d or score > d[i][0]:
                d[i] = (score, via)

        for i in order:
            sc, c = float(s[i]), self.chunks[i]
            kind = self.kind[i]
            if kind == "person":
                offer(people, i, sc, {"how": "own card"})
            elif kind == "unit":
                offer(units, i, sc, {"how": "own card"})
            else:
                url = c["url"]
                if url not in pages or sc > pages[url][0]:
                    pages[url] = (sc, i)
                if not cfg.rollup:
                    continue
                on_page = set(self.people_on_url.get(norm_url(url), ()))
                on_page |= {self.person_of_ref[r] for r in c.get("mentions") or [] if r in self.person_of_ref}
                if 0 < len(on_page) <= cfg.max_people_per_page:
                    credit = sc - cfg.page_penalty - 0.002 * (len(on_page) - 1)
                    for p in on_page:
                        offer(people, p, credit, {"how": "listed on matching page", "url": url,
                                                  "page_score": round(sc, 4)})
                u = self.unit_of_source.get(c["source_id"])
                if u is not None:
                    offer(units, u, sc - cfg.page_penalty / 2, {"how": "page of this unit", "url": url,
                                                                 "page_score": round(sc, 4)})

        if cfg.head_credit:
            for i, (sc, via) in list(people.items()):
                for ref in self.chunks[i].get("meta", {}).get("led_by") or []:
                    h = self.person_of_ref.get(ref)
                    if h is not None:
                        offer(people, h, sc - cfg.head_penalty,
                              {"how": f"heads the group of {self.chunks[i]['title']}", "url": self.chunks[i]["url"],
                               "member_score": round(sc, 4)})

        ppl = [self._person(i, sc, via) for i, (sc, via) in people.items()]
        for p in ppl:
            if p["lead"] and cfg.lead_boost:
                p["score"] = round(p["score"] + cfg.lead_boost, 4)
        ppl.sort(key=lambda r: -r["score"])
        uts = sorted((self._unit(i, sc, via) for i, (sc, via) in units.items()), key=lambda r: -r["score"])
        pgs = sorted((self._page(i, sc) for url, (sc, i) in pages.items()), key=lambda r: -r["score"])
        for lst in (ppl, uts, pgs):
            for r in lst:
                r["confident"] = r["score"] >= best - cfg.window
        return {"query": query, "best_score": round(best, 4), "no_reliable_match": best < cfg.floor,
                "config": asdict(cfg), "latency_s": round(time.perf_counter() - t0, 3),
                "people": ppl[:k], "units": uts[:k], "pages": pgs[:k]}
