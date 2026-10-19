"""Stage: raw HTML (data/raw/<source>/) -> data/pages.jsonl, one cleaned page per line.

Incremental: pages already in pages.jsonl (or already rejected, listed in pages.skipped) are not
parsed again, so this can run while the crawler is still going. Pages with identical text
(language variants, print views) are stored once. Parsing runs in a process pool; the main process
alone de-duplicates and writes, in manifest order.
"""
import hashlib
import json
import os
from concurrent.futures import ProcessPoolExecutor

from . import config
from .extract import extract
from .net.page import decode
from .sources import load_sources

MIN_CHARS = 200  # shorter pages are menus or redirects, not content
SKIPPED_FILE = config.DATA_DIR / "pages.skipped"  # page_ids parsed once and rejected (too short or duplicate)


def _read_jsonl(path) -> list[dict]:
    out = []
    if path.exists():
        for line in open(path, encoding="utf-8"):
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:  # a half-written last line from an interrupted run
                pass
    return out


def _parse(task: tuple) -> tuple:
    page_id, path, url = task
    try:
        page = extract(decode(open(path, "rb").read()), url)
    except Exception as e:  # one broken file must not stop the whole run
        return page_id, None, repr(e)
    return page_id, page, None


def build_pages(workers: int | None = None) -> tuple[int, int]:
    """Returns (pages added, total pages)."""
    sources = {s.id: s for s in load_sources()}
    existing = {p["page_id"]: p for p in _read_jsonl(config.PAGES_FILE)}
    seen_text = {hashlib.sha1(p["text"].encode()).hexdigest() for p in existing.values()}
    skipped = set(SKIPPED_FILE.read_text(encoding="utf-8").split()) if SKIPPED_FILE.exists() else set()

    tasks, rows = [], {}
    for manifest in sorted(config.RAW_DIR.glob("*/manifest.jsonl")):
        sid = manifest.parent.name
        for line in open(manifest, encoding="utf-8"):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:  # the crawler may be writing this line right now
                continue
            if row.get("status") != 200 or not row.get("file") or "html" not in row.get("content_type", ""):
                continue
            url = row.get("final_url") or row["url"]
            page_id = hashlib.sha1(url.encode()).hexdigest()[:16]
            if page_id in existing or page_id in skipped or page_id in rows:
                continue
            path = manifest.parent / row["file"]
            if path.exists():
                rows[page_id] = (sid, row, url)
                tasks.append((page_id, str(path), url))
    print(f"{len(existing)} pages already done, {len(skipped)} skipped before, {len(tasks)} to parse")

    added = 0
    workers = workers or max(1, (os.cpu_count() or 2) // 2)  # leave CPU for the crawler
    with open(config.PAGES_FILE, "a", encoding="utf-8") as out, \
            open(SKIPPED_FILE, "a", encoding="utf-8") as skip_out, \
            ProcessPoolExecutor(workers) as pool:
        for n, (page_id, page, err) in enumerate(pool.map(_parse, tasks, chunksize=16), 1):
            sid, row, url = rows[page_id]
            text_hash = hashlib.sha1(page["text"].encode()).hexdigest() if page else ""
            if page is None or len(page["text"]) < MIN_CHARS or text_hash in seen_text:
                skip_out.write(page_id + "\n")
            else:
                seen_text.add(text_hash)
                src = sources.get(sid)
                rec = {"page_id": page_id, "url": url, "title": page["title"], "text": page["text"],
                       "emails": page["emails"], "source_id": sid,
                       "source_name": src.name if src else sid,
                       "institution": src.institution if src else "University of Bern",
                       "fetched_at": row.get("fetched_at", ""),
                       # set by the collection net; absent for pages from the old crawler
                       "page_type": row.get("page_type"), "relevance": row.get("relevance")}
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                added += 1
            if n % 2000 == 0:
                print(f"  {n}/{len(tasks)} parsed, {added} added", flush=True)
    return added, len(existing) + added
