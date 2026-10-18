"""Stage: queries -> matches.json. Every chunk whose cosine similarity to a query is above the
threshold, best first. No LLM involved.

Accepts, in order of preference:
  queries.json  {"company_id", "queries": [{"qid", "text"}, ...]}
  company.json  {"company_id", "need", "goals"?, "keywords"?}  -> one query per field (no-LLM fallback)
  plain strings from the command line
"""
import json
from pathlib import Path

import numpy as np

from . import embed

DEFAULT_THRESHOLD = 0.85  # e5 scores sit in a narrow band: on-topic ~0.86-0.89, off-topic ~0.83; tune on the test bench
DEFAULT_TOP_K = 30


def queries_from_company(company: dict) -> list[dict]:
    qs = [{"text": company["need"], "from": "need"}]
    qs += [{"text": g, "from": f"goals[{i}]"} for i, g in enumerate(company.get("goals", []))]
    if company.get("keywords"):
        qs.append({"text": ", ".join(company["keywords"]), "from": "keywords"})
    return [{"qid": f"q{i + 1}", **q} for i, q in enumerate(qs)]


def load_queries(arg: str | list[str]) -> dict:
    """Turn a file path or plain strings into the queries.json shape."""
    if isinstance(arg, str):
        arg = [arg]
    if len(arg) == 1 and arg[0].endswith(".json") and Path(arg[0]).exists():
        data = json.loads(Path(arg[0]).read_text(encoding="utf-8"))
        if "queries" in data:
            return data
        return {"company_id": data.get("company_id", Path(arg[0]).stem), "queries": queries_from_company(data)}
    return {"company_id": "cli", "queries": [{"qid": f"q{i + 1}", "text": t, "from": "cli"} for i, t in enumerate(arg)]}


class Retriever:
    def __init__(self):
        self.chunks, self.vectors = embed.load_index()
        if not self.chunks:
            raise RuntimeError("Index is empty: run `python -m navigator embed` first")
        self.meta = json.loads(embed.META_FILE.read_text(encoding="utf-8"))
        if self.meta["model"] != embed.MODEL_NAME:
            raise RuntimeError(f"Index built with {self.meta['model']}, but EMBED_MODEL is {embed.MODEL_NAME}")

    def scores(self, texts: list[str]) -> np.ndarray:
        """(n_queries, n_chunks) cosine similarities."""
        return embed.encode(texts, embed.QUERY_PREFIX) @ self.vectors.T

    def retrieve(self, queries: dict, threshold: float = DEFAULT_THRESHOLD, top_k: int = DEFAULT_TOP_K) -> dict:
        qs = queries["queries"]
        sims = self.scores([q["text"] for q in qs])
        matches = []
        for q, row in zip(qs, sims):
            top = np.argsort(-row)[:top_k]
            for i in top:
                if row[i] < threshold:
                    break
                c = self.chunks[i]
                matches.append({"qid": q["qid"], "chunk_id": c["chunk_id"], "score": round(float(row[i]), 4),
                                "url": c["url"], "title": c["title"], "institution": c["institution"],
                                "source_id": c["source_id"], "text": c["text"]})
        matches.sort(key=lambda m: -m["score"])
        return {"company_id": queries.get("company_id", ""), "index_version": self.meta["index_version"],
                "threshold": threshold, "queries": qs, "matches": matches}
