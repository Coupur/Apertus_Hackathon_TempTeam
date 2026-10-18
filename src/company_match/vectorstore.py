"""Qdrant vector store for later-stage company matching.

Early stage = keyword / semantic-frequency prioritization (in-memory rules).
Later stage = dense vectors in Qdrant so teammates can retrieve similar companies
or match Bern expertise text against indexed company profiles.

Uses local Qdrant path by default (no Docker required). Embeddings:
1) fastembed if installed
2) otherwise a deterministic hash embedding (offline, demo-safe)
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import uuid
from pathlib import Path
from typing import Any, Iterable

DEFAULT_COLLECTION = os.getenv("QDRANT_COLLECTION", "bern_life_science_companies")
DEFAULT_PATH = os.getenv(
    "QDRANT_PATH",
    str(Path(__file__).resolve().parent / "data" / "qdrant_local"),
)
DEFAULT_URL = os.getenv("QDRANT_URL")  # e.g. http://localhost:6333
VECTOR_SIZE = int(os.getenv("QDRANT_VECTOR_SIZE", "384"))


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9\u3040-\u30ff\u4e00-\u9fff]{2,}", (text or "").lower())


def hash_embed(text: str, dim: int = VECTOR_SIZE) -> list[float]:
    """Deterministic bag-of-tokens embedding (no model download)."""
    vec = [0.0] * dim
    tokens = _tokenize(text)
    if not tokens:
        return vec
    for tok in tokens:
        digest = hashlib.sha256(tok.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "little") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[idx] += sign
    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class Embedder:
    def __init__(self) -> None:
        self.backend = "hash"
        self._model = None
        self.dim = VECTOR_SIZE
        try:
            from fastembed import TextEmbedding  # type: ignore

            self._model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
            # probe dim
            probe = list(self._model.embed(["probe"]))[0]
            self.dim = len(probe)
            self.backend = "fastembed"
        except Exception:
            self._model = None
            self.backend = "hash"
            self.dim = VECTOR_SIZE

    def embed(self, text: str) -> list[float]:
        text = (text or "").strip() or "empty"
        if self._model is not None:
            return list(list(self._model.embed([text]))[0])
        return hash_embed(text, self.dim)


def company_document_text(company: dict[str, Any], match: dict[str, Any] | None = None) -> str:
    match = match or {}
    parts = [
        company.get("name"),
        company.get("sector"),
        company.get("subsector"),
        company.get("description"),
        company.get("what_they_do"),
        " ".join(company.get("keywords") or []),
        " ".join(company.get("needs") or []),
        " ".join(match.get("early_keywords") or []),
        " ".join(match.get("teammate_queries_early") or []),
        " ".join(match.get("teammate_queries_later") or []),
        " ".join(match.get("bern_units") or []),
        match.get("activity_summary"),
    ]
    return "\n".join(str(p) for p in parts if p)


class QdrantCompanyStore:
    """Later-stage vector index for life-science companies."""

    def __init__(
        self,
        *,
        collection: str = DEFAULT_COLLECTION,
        path: str | None = DEFAULT_PATH,
        url: str | None = DEFAULT_URL,
    ):
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http import models as qm
        except ImportError as exc:
            raise ImportError(
                "qdrant-client is required. pip install qdrant-client fastembed"
            ) from exc

        self.qm = qm
        self.collection = collection
        self.embedder = Embedder()
        if url:
            self.client = QdrantClient(url=url)
            self.mode = f"url:{url}"
        else:
            Path(path or DEFAULT_PATH).mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=path or DEFAULT_PATH)
            self.mode = f"path:{path or DEFAULT_PATH}"
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        names = [c.name for c in self.client.get_collections().collections]
        if self.collection in names:
            return
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=self.qm.VectorParams(
                size=self.embedder.dim,
                distance=self.qm.Distance.COSINE,
            ),
        )

    def upsert_company(
        self,
        company: dict[str, Any],
        match: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        match = match or {}
        doc = company_document_text(company, match)
        vector = self.embedder.embed(doc)
        cid = str(company.get("id") or company.get("name") or uuid.uuid4())
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, cid))
        payload = {
            "company_id": cid,
            "company_name": company.get("name"),
            "sector": company.get("sector"),
            "subsector": company.get("subsector"),
            "source_language": company.get("source_language"),
            "website": company.get("website"),
            "source_ref": company.get("source_ref"),
            "match_rate": match.get("match_rate"),
            "priority_rating": match.get("priority_rating"),
            "priority_stage": match.get("priority_stage"),
            "early_keywords": match.get("early_keywords") or company.get("keywords") or [],
            "run_first": match.get("teammate_queries_early") or [],
            "run_later": match.get("teammate_queries_later") or [],
            "bern_units": match.get("bern_units") or [],
            "document": doc[:4000],
            "stage": "later_vector",
        }
        self.client.upsert(
            collection_name=self.collection,
            points=[
                self.qm.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                )
            ],
        )
        return {"point_id": point_id, "company_id": cid, "embedder": self.embedder.backend}

    def upsert_batch(
        self,
        items: Iterable[tuple[dict[str, Any], dict[str, Any] | None]],
    ) -> list[dict[str, Any]]:
        return [self.upsert_company(c, m) for c, m in items]

    def search(
        self,
        query: str,
        *,
        limit: int = 8,
        life_science_only: bool = True,
    ) -> list[dict[str, Any]]:
        """Later-stage semantic search over indexed companies."""
        vector = self.embedder.embed(query)
        # qdrant-client >= 1.12 uses query_points (search removed)
        response = self.client.query_points(
            collection_name=self.collection,
            query=vector,
            limit=limit,
        )
        points = getattr(response, "points", None) or response
        out = []
        for h in points:
            payload = h.payload or {}
            out.append(
                {
                    "score": round(float(h.score), 4),
                    "company_name": payload.get("company_name"),
                    "company_id": payload.get("company_id"),
                    "match_rate": payload.get("match_rate"),
                    "priority_rating": payload.get("priority_rating"),
                    "early_keywords": payload.get("early_keywords") or [],
                    "run_first": payload.get("run_first") or [],
                    "run_later": payload.get("run_later") or [],
                    "bern_units": payload.get("bern_units") or [],
                    "source_language": payload.get("source_language"),
                    "website": payload.get("website"),
                    "source_ref": payload.get("source_ref"),
                    "stage": "later_vector",
                }
            )
        return out

    def info(self) -> dict[str, Any]:
        count = self.client.count(self.collection, exact=True).count
        return {
            "collection": self.collection,
            "mode": self.mode,
            "points": count,
            "vector_size": self.embedder.dim,
            "embedder": self.embedder.backend,
        }


_store: QdrantCompanyStore | None = None


def get_qdrant_store(force_new: bool = False) -> QdrantCompanyStore:
    global _store
    if _store is None or force_new:
        _store = QdrantCompanyStore()
    return _store


def index_ingest_batch(batch_items: Iterable[Any]) -> dict[str, Any]:
    """Index matched ingest items into Qdrant for later-stage retrieval."""
    store = get_qdrant_store()
    indexed = []
    for item in batch_items:
        company = item.extraction.company if hasattr(item, "extraction") else item.get("extraction", {}).get("company", {})
        match = item.match.to_dict() if getattr(item, "match", None) else (item.get("match") or {})
        if hasattr(item, "match") and item.match and not item.match.in_scope:
            continue
        if isinstance(match, dict) and match.get("in_scope") is False:
            continue
        indexed.append(store.upsert_company(company, match if isinstance(match, dict) else {}))
    info = store.info()
    info["indexed"] = len(indexed)
    info["details"] = indexed
    return info
