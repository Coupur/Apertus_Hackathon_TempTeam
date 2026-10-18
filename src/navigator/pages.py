"""Stage: raw HTML (data/raw/<source>/) -> data/pages.jsonl, one cleaned page per line.

Incremental: pages already in pages.jsonl are kept and only new raw files are parsed, so this
can run while the crawler is still going. Pages with identical text (language variants, print
views) are stored once.
"""
import hashlib
import json

from . import config
from .extract import extract
from .sources import load_sources

MIN_CHARS = 200  # shorter pages are menus or redirects, not content


def build_pages() -> tuple[int, int]:
    """Returns (pages added, total pages)."""
    sources = {s.id: s for s in load_sources()}
    existing = {}
    if config.PAGES_FILE.exists():
        existing = {p["page_id"]: p for p in map(json.loads, open(config.PAGES_FILE, encoding="utf-8"))}
    seen_text = {hashlib.sha1(p["text"].encode()).hexdigest() for p in existing.values()}

    added = 0
    with open(config.PAGES_FILE, "a", encoding="utf-8") as out:
        for manifest in sorted(config.RAW_DIR.glob("*/manifest.jsonl")):
            sid = manifest.parent.name
            src = sources.get(sid)
            for line in open(manifest, encoding="utf-8"):
                row = json.loads(line)
                if row.get("status") != 200 or not row.get("file") or "html" not in row.get("content_type", ""):
                    continue
                url = row.get("final_url") or row["url"]
                page_id = hashlib.sha1(url.encode()).hexdigest()[:16]
                if page_id in existing:
                    continue
                path = manifest.parent / row["file"]
                if not path.exists():
                    continue
                page = extract(path.read_text(encoding="utf-8", errors="replace"), url)
                text_hash = hashlib.sha1(page["text"].encode()).hexdigest()
                existing[page_id] = None  # mark seen even if skipped below
                if len(page["text"]) < MIN_CHARS or text_hash in seen_text:
                    continue
                seen_text.add(text_hash)
                rec = {"page_id": page_id, "url": url, "title": page["title"], "text": page["text"],
                       "emails": page["emails"], "source_id": sid,
                       "source_name": src.name if src else sid,
                       "institution": src.institution if src else "University of Bern",
                       "fetched_at": row.get("fetched_at", "")}
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                added += 1
    total = sum(1 for _ in open(config.PAGES_FILE, encoding="utf-8"))
    return added, total
