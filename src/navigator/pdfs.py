"""Download the PDFs the crawler listed in data/raw/<source>/pdf_links.jsonl.

Saves them untouched to data/raw/<source>/pdfs/<sha1>.pdf with one line per request in
pdf_manifest.jsonl. Resumable like the crawler: already attempted URLs are skipped,
network errors are retried on the next run. One request at a time per site, sites in parallel.
"""
import asyncio
import hashlib
import json
import time
from datetime import datetime, timezone

import httpx

from . import config
from .robots import Robots

MAX_PDF_BYTES = 20_000_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def _site(client, site_dir, max_per_site, delay, stats, log):
    links = []
    for line in open(site_dir / "pdf_links.jsonl", encoding="utf-8"):
        try:
            links.append(json.loads(line)["url"])
        except json.JSONDecodeError:
            pass  # the crawler may be appending to this file right now
    links = list(dict.fromkeys(links))
    manifest = site_dir / "pdf_manifest.jsonl"
    tried = set()
    if manifest.exists():
        for line in open(manifest, encoding="utf-8"):
            m = json.loads(line)
            if not str(m["status"]).startswith("error"):
                tried.add(m["url"])
    out_dir = site_dir / "pdfs"
    out_dir.mkdir(exist_ok=True)
    saved = sum(1 for _ in out_dir.glob("*.pdf"))
    todo = [u for u in links if u not in tried][:max(0, max_per_site - saved)]
    stats["total"] += len(todo)
    robots_cache: dict[str, Robots] = {}

    with open(manifest, "a", encoding="utf-8") as mf:
        for url in todo:
            host = httpx.URL(url).host
            if host not in robots_cache:
                try:
                    r = await client.get(f"https://{host}/robots.txt")
                    robots_cache[host] = Robots(r.text if r.status_code == 200 else "", config.USER_AGENT)
                except httpx.HTTPError:
                    robots_cache[host] = Robots("", config.USER_AGENT)
            rec = {"url": url, "status": None, "file": None, "bytes": 0, "fetched_at": _now()}
            if not robots_cache[host].can_fetch(url):
                rec["status"] = "robots"
            else:
                try:
                    async with client.stream("GET", url) as r:
                        rec["status"] = r.status_code
                        size = int(r.headers.get("content-length") or 0)
                        ctype = r.headers.get("content-type", "")
                        if r.status_code == 200 and size <= MAX_PDF_BYTES and "pdf" in ctype:
                            body = await r.aread()
                            if body[:5] == b"%PDF-" and len(body) <= MAX_PDF_BYTES:
                                name = hashlib.sha1(url.encode()).hexdigest()[:20] + ".pdf"
                                (out_dir / name).write_bytes(body)
                                rec.update(file=f"pdfs/{name}", bytes=len(body))
                                stats["saved"] += 1
                                stats["mb"] += len(body) / 1e6
                        elif size > MAX_PDF_BYTES:
                            rec["status"] = "too_large"
                except httpx.HTTPError as e:
                    rec["status"] = f"error:{type(e).__name__}"
                    stats["errors"] += 1
            stats["done"] += 1
            mf.write(json.dumps(rec, ensure_ascii=False) + "\n")
            mf.flush()
            log(f"{rec['fetched_at']}\t{site_dir.name}\tpdf\t{rec['status']}\t{url}")
            await asyncio.sleep(delay)


async def download_all(only: list[str] | None, max_per_site: int, concurrency: int, delay: float) -> dict:
    sites = sorted(p.parent for p in config.RAW_DIR.glob("*/pdf_links.jsonl")
                   if not only or p.parent.name in only)
    stats = {"sites": len(sites), "total": 0, "done": 0, "saved": 0, "errors": 0, "mb": 0.0}
    log_file = open(config.RAW_DIR / "crawl.log", "a", encoding="utf-8")
    log = lambda msg: (log_file.write(msg + "\n"), log_file.flush())
    sem = asyncio.Semaphore(concurrency)
    t0 = time.time()

    async def report():
        while True:
            await asyncio.sleep(10)
            el = int(time.time() - t0)
            print(f"[{el // 60:02d}:{el % 60:02d}] pdfs {stats['done']}/{stats['total']} tried | "
                  f"{stats['saved']} saved ({stats['mb']:.0f} MB) | errors {stats['errors']}", flush=True)

    async def one(site_dir):
        async with sem:
            before = stats["saved"]
            try:
                await _site(client, site_dir, max_per_site, delay, stats, log)
            except Exception as e:  # one broken site must not stop the others
                print(f"  [fail] {site_dir.name}: {type(e).__name__}: {e}", flush=True)
            print(f"  [done] {site_dir.name:<16} {stats['saved'] - before} pdfs saved", flush=True)

    headers = {"User-Agent": config.USER_AGENT}
    async with httpx.AsyncClient(headers=headers, timeout=60, follow_redirects=True) as client:
        ticker = asyncio.create_task(report())
        try:
            await asyncio.gather(*(one(s) for s in sites))
        finally:
            ticker.cancel()
            log_file.close()
    return stats
