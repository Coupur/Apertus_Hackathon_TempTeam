"""Stage: queries -> matches.json. Every chunk whose cosine similarity to a query is above the
threshold, best first. No LLM involved.

Accepts, in order of preference:
  queries.json  {"company_id", "queries": [{"qid", "text"}, ...]}
  company.json  {"company_id", "need", "goals"?, "keywords"?}  -> one query per field (no-LLM fallback)
  plain strings from the command line
"""
import json
import re
from pathlib import Path

import numpy as np

from . import config, embed

DEFAULT_THRESHOLD = 0.85  # e5 scores sit in a narrow band: on-topic ~0.86-0.89, off-topic ~0.83; tune on the test bench
DEFAULT_TOP_K = 30
# Listing pages (news categories, tag and date archives, paged indexes) repeat excerpts of real pages and
# outscore them on broad queries. They lose this much before the top-k cut and the threshold; the e5 band
# is ~0.035 wide, so they only show when nothing specific matches.
LISTING_RE = re.compile(r"/(category|tag|author|project_category|archive|archiv)/|/page/\d+/?(\?|$)"
                        r"|/\d{4}/\d{2}/?(\?|$)", re.I)
LISTING_PENALTY = 0.03


def is_listing(url: str) -> bool:
    return bool(LISTING_RE.search(url or ""))


def queries_from_company(company: dict) -> list[dict]:
    qs = [{"text": company["need"], "from": "need"}]
    qs += [{"text": g, "from": f"goals[{i}]"} for i, g in enumerate(company.get("goals", []))]
    if company.get("keywords"):
        qs.append({"text": ", ".join(company["keywords"]), "from": "keywords"})
    return [{"qid": f"q{i + 1}", **q} for i, q in enumerate(qs)]


def load_queries(arg: str | list[str]) -> dict:
    """Turn a file path or plain strings into the queries.json shape. A .json path is looked up from
    the current folder, then from the repo root; a missing file is an error, not a query."""
    if isinstance(arg, str):
        arg = [arg]
    if len(arg) == 1 and arg[0].endswith(".json"):
        path = next((p for p in (Path(arg[0]), config.ROOT / arg[0]) if p.exists()), None)
        if path is None:
            known = sorted(p.as_posix() for p in (config.DATA_DIR / "companies").glob("*/queries.json"))
            raise SystemExit(f"{arg[0]} not found (looked in {Path.cwd()} and {config.ROOT}).\n"
                             "Company query files:\n  " + "\n  ".join(known or ["none yet: run `navigator company`"]))
        data = json.loads(path.read_text(encoding="utf-8"))
        if "queries" in data:
            return data
        return {"company_id": data.get("company_id", path.stem), "queries": queries_from_company(data)}
    return {"company_id": "cli", "queries": [{"qid": f"q{i + 1}", "text": t, "from": "cli"} for i, t in enumerate(arg)]}


class Retriever:
    def __init__(self):
        self.chunks, self.vectors = embed.load_index()
        if not self.chunks:
            raise RuntimeError("Index is empty: run `python -m navigator embed` first")
        self.meta = json.loads(embed.META_FILE.read_text(encoding="utf-8"))
        if self.meta["model"] != embed.MODEL_NAME:
            raise RuntimeError(f"Index built with {self.meta['model']}, but EMBED_MODEL is {embed.MODEL_NAME}")
        self.listing = np.array([is_listing(c["url"]) for c in self.chunks])

    def scores(self, texts: list[str]) -> np.ndarray:
        """(n_queries, n_chunks) cosine similarities."""
        return embed.encode(texts, embed.QUERY_PREFIX) @ self.vectors.T

    def retrieve(self, queries: dict, threshold: float = DEFAULT_THRESHOLD, top_k: int = DEFAULT_TOP_K,
                 listing_penalty: float = LISTING_PENALTY) -> dict:
        """`score` has listing pages down-weighted (see LISTING_RE); `score_raw` is the plain cosine.
        `z` is `score` in standard deviations above this query's mean over the whole index: raw e5
        cosines differ in level from query to query, z can be compared across queries."""
        qs = [dict(q) for q in queries["queries"]]
        raw = self.scores([q["text"] for q in qs])
        sims = raw - listing_penalty * self.listing
        matches = []
        for q, row, raw_row in zip(qs, sims, raw):
            mu, sd = float(raw_row.mean()), float(raw_row.std()) or 1.0
            q["index_mean"], q["index_std"] = round(mu, 4), round(sd, 5)
            top = np.argsort(-row)[:top_k]
            for i in top:
                if row[i] < threshold:
                    break
                c = self.chunks[i]
                matches.append({"qid": q["qid"], "chunk_id": c["chunk_id"], "score": round(float(row[i]), 4),
                                "z": round((float(row[i]) - mu) / sd, 3),
                                "score_raw": round(float(raw_row[i]), 4), "listing": bool(self.listing[i]),
                                "kind": c.get("kind", "page"), "url": c["url"], "title": c["title"], "institution": c["institution"],
                                "source_id": c["source_id"], "text": c["text"]})
        matches.sort(key=lambda m: -m["score"])
        return {"company_id": queries.get("company_id", ""), "index_version": self.meta["index_version"],
                "threshold": threshold, "listing_penalty": listing_penalty, "queries": qs, "matches": matches}
