"""Stage: data/index/to_embed.jsonl (written by `cards`) -> data/index/{chunks.jsonl, vectors.npy, meta.json}.

Every line to embed (a person card, a unit card or a 200-word page chunk) gets one unit-length
vector, so cosine similarity is a plain dot product. Similar texts point in similar directions
(score near 1), unrelated texts score lower.

Incremental: each line carries chunk_id = hash(model + text). Lines already in the index keep their
vector, only new ones are embedded, and lines that disappeared are dropped. Changing the model
changes every chunk_id, which forces a full rebuild. Without to_embed.jsonl it falls back to
chunking pages.jsonl directly, as before.
"""
import hashlib
import json
import os

import numpy as np

from . import config

MODEL_NAME = os.getenv("EMBED_MODEL", "intfloat/multilingual-e5-small")
CHUNK_WORDS = int(os.getenv("CHUNK_WORDS", "200"))      # ~300 tokens, under e5's 512 limit
OVERLAP_WORDS = int(os.getenv("OVERLAP_WORDS", "40"))
INDEX_DIR = config.DATA_DIR / "index"
CHUNKS_FILE = INDEX_DIR / "chunks.jsonl"
VECTORS_FILE = INDEX_DIR / "vectors.npy"
META_FILE = INDEX_DIR / "meta.json"

# e5 models expect these prefixes; other models get none
PASSAGE_PREFIX = "passage: " if "e5" in MODEL_NAME else ""
QUERY_PREFIX = "query: " if "e5" in MODEL_NAME else ""

_model = None


def pick_device() -> str:
    """EMBED_DEVICE=cuda|mps|cpu overrides; otherwise the best one available."""
    import torch
    if os.getenv("EMBED_DEVICE"):
        return os.environ["EMBED_DEVICE"]
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        device = pick_device()
        _model = SentenceTransformer(MODEL_NAME, device=device)
        if device == "cuda":
            _model.half()  # fp16: ~2x faster, same rankings
        print(f"Embedding model {MODEL_NAME} on {device}")
    return _model


def encode(texts: list[str], prefix: str, batch_size: int = 64, progress: bool = False) -> np.ndarray:
    vecs = get_model().encode([prefix + t for t in texts], batch_size=batch_size,
                              normalize_embeddings=True, show_progress_bar=progress)
    return np.asarray(vecs, dtype=np.float32)


def split_words(text: str, size: int = CHUNK_WORDS, overlap: int = OVERLAP_WORDS) -> list[str]:
    words = text.split()
    if len(words) <= size:
        return [" ".join(words)]
    step = size - overlap
    return [" ".join(words[i:i + size]) for i in range(0, len(words) - overlap, step)]


def _hash(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:16]


def make_chunks(page: dict) -> list[dict]:
    out = []
    for n, body in enumerate(split_words(page["text"])):
        # Title + institution in front gives every chunk its context ("whose page is this?")
        text = f"{page['title']} | {page['institution']}\n{body}"
        cid = hashlib.sha1(f"{MODEL_NAME}\n{text}".encode()).hexdigest()[:16]
        out.append({"chunk_id": cid, "page_id": page["page_id"], "n": n, "url": page["url"],
                    "title": page["title"], "institution": page["institution"],
                    "source_id": page["source_id"], "text": text})
    return out


def load_index() -> tuple[list[dict], np.ndarray]:
    if not (CHUNKS_FILE.exists() and VECTORS_FILE.exists()):
        return [], np.zeros((0, 0), dtype=np.float32)
    chunks = [json.loads(l) for l in open(CHUNKS_FILE, encoding="utf-8")]
    vectors = np.load(VECTORS_FILE)
    if len(chunks) != len(vectors):
        raise RuntimeError(f"{CHUNKS_FILE} and {VECTORS_FILE} are out of sync; delete {INDEX_DIR} and rerun embed")
    return chunks, vectors


KIND_ORDER = {"person": 0, "unit": 1, "page": 2}  # embed the most useful lines first


def build_index(batch_size: int = 64) -> dict:
    to_embed = INDEX_DIR / "to_embed.jsonl"
    if to_embed.exists():
        wanted = [json.loads(l) for l in open(to_embed, encoding="utf-8")]
    else:
        wanted = [c for p in map(json.loads, open(config.PAGES_FILE, encoding="utf-8")) for c in make_chunks(p)]
    wanted = list({c["chunk_id"]: c for c in wanted}.values())  # same text twice -> one chunk
    wanted.sort(key=lambda c: KIND_ORDER.get(c.get("kind", "page"), 9))
    pages = {c.get("ref") or c.get("page_id") for c in wanted if c.get("kind", "page") == "page"}

    old_chunks, old_vecs = load_index()
    old_pos = {c["chunk_id"]: i for i, c in enumerate(old_chunks)}
    new = [c for c in wanted if c["chunk_id"] not in old_pos]
    print(f"{len(pages)} pages -> {len(wanted)} chunks: {len(wanted) - len(new)} already embedded, "
          f"{len(new)} new, {len(old_chunks) - (len(wanted) - len(new))} dropped")

    new_vecs = encode([c["text"] for c in new], PASSAGE_PREFIX, batch_size, progress=True) if new else None
    dim = new_vecs.shape[1] if new_vecs is not None else (old_vecs.shape[1] if len(old_chunks) else 0)
    new_pos = {c["chunk_id"]: i for i, c in enumerate(new)}

    vectors = np.zeros((len(wanted), dim), dtype=np.float32)
    for i, c in enumerate(wanted):
        cid = c["chunk_id"]
        vectors[i] = old_vecs[old_pos[cid]] if cid in old_pos else new_vecs[new_pos[cid]]

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CHUNKS_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for c in wanted:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    np.save(VECTORS_FILE.with_suffix(".tmp.npy"), vectors)
    tmp.replace(CHUNKS_FILE)
    VECTORS_FILE.with_suffix(".tmp.npy").replace(VECTORS_FILE)
    meta = {"model": MODEL_NAME, "chunk_words": CHUNK_WORDS, "overlap_words": OVERLAP_WORDS,
            "chunks": len(wanted), "dim": dim, "pages": len(pages),
            "index_version": f"{MODEL_NAME.split('/')[-1]}@{len(wanted)}"}
    META_FILE.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta
