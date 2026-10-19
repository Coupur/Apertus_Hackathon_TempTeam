"""Company queries.json + retrieval matches -> for each question, the pages that answer it.

How many results a question gets depends on the shape of its scores, not on a fixed top-N:

  1 score   Each match's z: how many standard deviations it lies above its query's mean over the
            whole index (retrieve.py). Raw e5 cosines sit in a narrow band whose level differs from
            query to query; z makes queries comparable.
  2 merge   Per question, a page's score is its best z over the question's EN and DE queries, plus
            AGREEMENT for each further query that found it. English and German twins of a page and
            listing pages that repeat its text count once.
  3 diverse Greedy pick: each page already taken from the same site lowers the next one by
            SITE_PENALTY. A site that really holds the best answers still shows several, but it
            cannot push out a close alternative from another unit.
  4 cut     The background is the typical score of an ordinary candidate (median of ranks 10-30).
            A page is kept if it stands at least KEEP_RATIO as far above the background as the best
            page does. One clear winner -> one result; a tight group of strong pages -> all of them.
  5 label   How far the best page stands above the background says how clear the answer is:
            clear >= CLEAR, moderate >= MODERATE, else weak (shown as "no clear answer in our data").

The constants were set on the Ypsomed run (7 questions, 37 queries, 54k chunks); tune them on the bench.
"""
import re
import statistics

AGREEMENT = 0.1      # z added per extra query of the same question that found the page (max 3 extra)
SITE_PENALTY = 0.15  # z subtracted per page already picked from the same site
KEEP_RATIO = 0.5     # keep pages at least half as far above the background as the best one
BACKGROUND_RANKS = (10, 30)
CLEAR, MODERATE = 0.6, 0.3  # best page's margin above the background, in z
CANDIDATES_PER_QUERY = 40  # retrieval returns this many per query, no raw threshold; the cut happens here
MAX_RESULTS = 8      # clear answer: at most this many, however many pass the cut
MODERATE_RESULTS = 5  # a weak lead gets fewer results: many pages that each stand out "a little" is noise
WEAK_RESULTS = 3     # with no clear answer, show only this many, marked as weak


def twin_key(url: str) -> str:
    """One key for a page and its translation: index_eng/index_ger, /en/ and /de/ folders."""
    u = re.sub(r"^https?://(www\.)?", "", url.lower()).split("#")[0].split("?")[0]
    u = re.sub(r"/(en|de|fr)(/|$)", "/", u)
    u = re.sub(r"(index)?_(eng|ger|fra)\.html?$", "", u)
    return u.rstrip("/")


def _candidates(need_qids: set, matches: list[dict]) -> list[dict]:
    pages: dict[str, dict] = {}
    texts: dict[str, str] = {}
    for m in matches:
        if m["qid"] not in need_qids:
            continue
        body = " ".join(m["text"].split("\n", 1)[-1].split())[:300]
        key = texts.setdefault(body, twin_key(m["url"]))  # same text under another URL -> same page
        p = pages.get(key)
        if p is None:
            pages[key] = p = {**{k: v for k, v in m.items() if k != "qid"}, "via": [], "best_z": m["z"]}
        if m["qid"] not in p["via"]:
            p["via"].append(m["qid"])
        if m["z"] > p["best_z"]:
            p.update({k: v for k, v in m.items() if k != "qid"}, best_z=m["z"])
    for p in pages.values():
        p["need_score"] = round(p["best_z"] + AGREEMENT * min(3, len(p["via"]) - 1), 3)
    return sorted(pages.values(), key=lambda p: -p["need_score"])


def _diversify(cands: list[dict]) -> list[dict]:
    left, picked, per_site = list(cands), [], {}
    while left:
        best = max(left, key=lambda p: p["need_score"] - SITE_PENALTY * per_site.get(p["source_id"], 0))
        left.remove(best)
        best["final"] = round(best["need_score"] - SITE_PENALTY * per_site.get(best["source_id"], 0), 3)
        per_site[best["source_id"]] = per_site.get(best["source_id"], 0) + 1
        picked.append(best)
    return picked


def select(need_qids: set, matches: list[dict]) -> dict:
    ranked = _diversify(_candidates(need_qids, matches))
    if not ranked:
        return {"confidence": "none", "background": None, "margin": 0.0, "candidates": 0, "hits": []}
    scores = [p["final"] for p in ranked]
    lo, hi = BACKGROUND_RANKS
    crowd = scores[lo:hi] or scores[len(scores) // 2:] or scores
    background = statistics.median(crowd)
    margin = scores[0] - background
    confidence = "clear" if margin >= CLEAR else "moderate" if margin >= MODERATE else "weak"
    if confidence == "weak":
        hits = ranked[:WEAK_RESULTS]
    else:
        cap = MAX_RESULTS if confidence == "clear" else MODERATE_RESULTS
        hits = [p for p in ranked[:cap] if p["final"] - background >= KEEP_RATIO * margin]
    for p in hits:
        p["margin"] = round(p["final"] - background, 3)
    return {"confidence": confidence, "background": round(background, 3), "margin": round(margin, 3),
            "candidates": len(ranked), "hits": hits}


def group_by_need(queries: dict, res: dict) -> list[dict]:
    """For a company queries.json: the selected pages per need (question), see the module docstring."""
    out = []
    for n in queries.get("needs", []):
        qids = {q["qid"] for q in res["queries"] if q.get("need_id") == n["id"]}
        out.append({**{k: n.get(k) for k in ("id", "section", "section_name", "question", "coverage")},
                    **select(qids, res["matches"])})
    return out


def format_by_need(groups: list[dict]) -> str:
    lines = []
    for g in groups:
        lines += [f"\n[{g['id']} {g['section']} {g['section_name']} | Bern data coverage: {g['coverage']}]",
                  f"Q: {g['question']}"]
        if not g["hits"]:
            lines.append("   no candidates")
            continue
        verdict = {"clear": f"clear answer: {len(g['hits'])} result(s) stand out",
                   "moderate": f"moderate: {len(g['hits'])} result(s) stand out a little",
                   "weak": "no clear answer in our data: nothing stands out; closest pages below"}[g["confidence"]]
        lines.append(f"   {verdict} (best {g['margin']:+.2f} z above the {g['candidates']} candidates' background)")
        for h in g["hits"]:
            snippet = h["text"].split("\n", 1)[-1][:150].replace("\n", " ")
            mark = "  (listing page)" if h.get("listing") else ""
            lines += [f"  {h['margin']:+.2f}  {h.get('kind', 'page'):6} {h['source_id'][:16]:16} {h['url']}{mark}",
                      f"         {snippet}", f"         found by {', '.join(h['via'])}"]
    return "\n".join(lines)
