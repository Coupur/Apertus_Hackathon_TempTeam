"""Raw HTML crawler for every website in the source registry.

Every fetched page is saved untouched under data/raw/<source_id>/ so later steps
(cleaning, LLM extraction) run offline and can be repeated. Per source:

    pages/<sha1>.html     the raw HTML
    manifest.jsonl        one line per request: url, final_url, status, file, depth, fetched_at
    pdf_links.jsonl       PDF links seen (publication lists, brochures) for a later step

Resumable: rerun the same command and saved URLs are skipped; the link frontier is
rebuilt from the saved pages. Progress: a summary on the console every few seconds,
data/raw/progress.json for other tools, and data/raw/crawl.log with every request.
"""
import asyncio
import hashlib
import heapq
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlsplit

import httpx

from . import config
from .robots import Robots
from .sources import Source

SKIP_EXT = re.compile(r"\.(jpe?g|png|gif|svg|webp|ico|zip|docx?|xlsx?|pptx?|mp4|mp3|wav|ics|vcf|css|js|xml|json)(\?|$)", re.I)
PDF_EXT = re.compile(r"\.pdf(\?|$)", re.I)
PRIORITY_WORDS = [
    "team", "people", "personen", "mitarbeitende", "staff", "member", "profile", "prof_",
    "research", "forschung", "group", "gruppe", "project", "projekt", "expertise",
    "publication", "publikation", "service", "dienstleistung", "infrastructure", "infrastruktur",
    "facility", "facilities", "equipment", "platform", "lab", "labor", "news", "aktuell",
    # what a company looks for: infrastructure, services, transfer, collaboration
    "geraete", "ausstattung", "core", "technolog", "method", "methode", "angebot", "industry",
    "industrie", "kooperation", "collaborat", "partner", "transfer", "innovation", "patent", "spin",
    "startup", "consult", "analys", "messung", "testing", "clinical", "trial", "studie", "study",
]
SKIP_WORDS = ["login", "logout", "/search", "/suche", "index_print", "_fra.html", "/fr/", "/it/", "/events/",
              "/agenda/", "/jobs", "/stellen", "career", "impressum", "datenschutz", "privacy",
              "data-protection", "mailto:", "javascript:", "tel:", "/feed", "?share=", "wp-login",
              "replytocom", "/tag/", "/author/",
              # UniBE-wide portals linked from every page: staff intranet, LMS, library, jobs
              "karriere.unibe", "intern.unibe", "ilias.unibe", "teachinghub.unibe", "ub.unibe",
              "edit.cms.unibe", "beratungswegweiser.unibe"]
MAX_BYTES = 5_000_000
GER_PENALTY = 3  # UniBE pages exist as *_ger.html and *_eng.html; fetch English first


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _priority(url: str, depth: int) -> float:
    u = url.lower()
    return depth - sum(0.6 for w in PRIORITY_WORDS if w in u) + (GER_PENALTY if "_ger." in u else 0)


def _eng_twin(url: str) -> str | None:
    return url.replace("_ger.", "_eng.") if "_ger." in url else None


def _links(html: str, base: str) -> list[str]:
    # A regex is enough to find hrefs and is ~20x faster than a full parse.
    out = []
    for href in re.findall(r"""href\s*=\s*["']([^"'#]+)""", html, re.I):
        href = href.strip()
        if href and not href.lower().startswith(("mailto:", "javascript:", "tel:")):
            out.append(urldefrag(urljoin(base, href))[0])
    return out


class SourceCrawl:
    """Crawls one website, one request at a time (politeness), resumable."""

    def __init__(self, source: Source, max_pages: int, delay: float, log):
        self.s, self.max_pages, self.delay, self.log = source, max_pages, delay, log
        self.dir = config.RAW_DIR / source.id
        self.pages_dir = self.dir / "pages"
        self.stats = {"id": source.id, "name": source.name, "status": "queued", "saved": 0,
                      "new": 0, "errors": 0, "skipped_robots": 0, "pdf_links": 0, "frontier": 0,
                      "last_url": "", "started": None, "finished": None}
        self.done: set[str] = set()
        self.pdfs: set[str] = set()
        self.queue: list = []
        self.queued: set[str] = set()
        self.saved_urls: set[str] = set()

    def _same_site(self, url: str) -> bool:
        host = urlsplit(url).netloc.lower().split(":")[0].removeprefix("www.")
        return host == self.s.host or host.endswith("." + self.s.host)

    def _enqueue(self, url: str, depth: int, found_on: str):
        if not url.startswith(("http://", "https://")) or not self._same_site(url):
            return
        if PDF_EXT.search(url):
            if url not in self.pdfs:
                self.pdfs.add(url)
                with open(self.dir / "pdf_links.jsonl", "a", encoding="utf-8") as f:
                    f.write(json.dumps({"url": url, "found_on": found_on}) + "\n")
            return
        low = url.lower()
        if (url in self.queued or url in self.done or len(url) > 300 or SKIP_EXT.search(url)
                or any(w in low for w in SKIP_WORDS)):
            return
        self.queued.add(url)
        heapq.heappush(self.queue, (_priority(url, depth), depth, url))

    def _resume(self):
        """Rebuild state from what an earlier run saved."""
        manifest = self.dir / "manifest.jsonl"
        if (self.dir / "pdf_links.jsonl").exists():
            self.pdfs = {json.loads(l)["url"] for l in open(self.dir / "pdf_links.jsonl", encoding="utf-8")}
        if not manifest.exists():
            return []
        saved = []
        for line in open(manifest, encoding="utf-8"):
            m = json.loads(line)
            if str(m.get("status")).startswith("error"):
                continue  # network errors are retried on the next run
            self.done.update({m["url"], m.get("final_url") or m["url"]})
            if m.get("file"):
                saved.append(m)
                self.saved_urls.add(m["final_url"])
        self.stats["saved"] = len(saved)
        return saved

    async def run(self, client: httpx.AsyncClient):
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        self.stats.update(status="running", started=_now())
        try:
            robots_resp = await client.get(f"https://{urlsplit(self.s.url).netloc}/robots.txt")
            robots = Robots(robots_resp.text if robots_resp.status_code == 200 else "", config.USER_AGENT)
        except httpx.HTTPError:
            robots = Robots("", config.USER_AGENT)

        for m in self._resume():
            html = (self.dir / m["file"]).read_text(encoding="utf-8", errors="replace")
            for link in _links(html, m["final_url"]):
                self._enqueue(link, m["depth"] + 1, m["final_url"])
        for seed in self.s.seeds():
            if seed not in self.done:
                self._enqueue(seed, 0, "seed")

        with open(self.dir / "manifest.jsonl", "a", encoding="utf-8") as manifest:
            while self.queue and self.stats["saved"] < self.max_pages:
                _, depth, url = heapq.heappop(self.queue)
                self.stats["frontier"] = len(self.queue)
                if url in self.done:
                    continue
                if _eng_twin(url) in self.saved_urls:
                    self.stats["skipped_ger"] = self.stats.get("skipped_ger", 0) + 1
                    self.done.add(url)  # English twin already saved; German copy adds little
                    continue
                if not robots.can_fetch(url):
                    self.stats["skipped_robots"] += 1
                    self.done.add(url)
                    continue
                self.stats["last_url"] = url
                rec = {"url": url, "final_url": None, "status": None, "content_type": None,
                       "file": None, "depth": depth, "bytes": 0, "fetched_at": _now()}
                try:
                    r = await client.get(url)
                    final = str(r.url)
                    ctype = r.headers.get("content-type", "").split(";")[0].strip()
                    rec.update(final_url=final, status=r.status_code, content_type=ctype, bytes=len(r.content))
                    self.done.update({url, final})
                    if r.status_code == 200 and ctype == "text/html" and self._same_site(final) \
                            and len(r.content) <= MAX_BYTES:
                        name = hashlib.sha1(final.encode()).hexdigest()[:20] + ".html"
                        (self.pages_dir / name).write_bytes(r.content)
                        rec["file"] = f"pages/{name}"
                        self.stats["saved"] += 1
                        self.stats["new"] += 1
                        self.saved_urls.add(final)
                        for link in _links(r.text, final):
                            self._enqueue(link, depth + 1, final)
                    elif ctype == "application/pdf":
                        self._enqueue(final, depth, url)
                except httpx.HTTPError as e:
                    rec["status"] = f"error:{type(e).__name__}"
                    self.stats["errors"] += 1
                    self.done.add(url)
                manifest.write(json.dumps(rec, ensure_ascii=False) + "\n")
                manifest.flush()
                self.log(f"{rec['fetched_at']}\t{self.s.id}\t{rec['status']}\t{url}")
                await asyncio.sleep(self.delay)

        self.stats["pdf_links"] = len(self.pdfs)
        self.stats["frontier"] = len(self.queue)
        self.stats.update(status="done", finished=_now(), last_url="")


class Reporter:
    """Prints a progress summary every `every` seconds and writes progress.json."""

    def __init__(self, crawls: list[SourceCrawl], max_pages: int, every: float = 10):
        self.crawls, self.max_pages, self.every = crawls, max_pages, every
        self.t0 = time.time()

    def snapshot(self) -> dict:
        st = [c.stats for c in self.crawls]
        by = lambda s: sum(1 for x in st if x["status"] == s)
        return {"updated": _now(), "elapsed_s": round(time.time() - self.t0),
                "sites": {"total": len(st), "done": by("done"), "running": by("running"), "queued": by("queued")},
                "pages_saved": sum(x["saved"] for x in st), "pages_new": sum(x["new"] for x in st),
                "errors": sum(x["errors"] for x in st), "pdf_links": sum(len(c.pdfs) for c in self.crawls),
                "max_pages_per_site": self.max_pages, "per_source": st}

    def line(self) -> str:
        s = self.snapshot()
        mins = max(s["elapsed_s"] / 60, 1 / 60)
        running = ", ".join(f"{x['id']} {x['saved']}/{self.max_pages}"
                            for x in s["per_source"] if x["status"] == "running")
        return (f"[{s['elapsed_s'] // 60:02d}:{s['elapsed_s'] % 60:02d}] sites {s['sites']['done']}/{s['sites']['total']} done"
                f" | pages {s['pages_saved']} ({s['pages_new']} new, {s['pages_new'] / mins:.0f}/min)"
                f" | errors {s['errors']} | pdf links {s['pdf_links']} | now: {running or '-'}")

    def write(self):
        (config.RAW_DIR / "progress.json").write_text(json.dumps(self.snapshot(), indent=1, ensure_ascii=False),
                                                      encoding="utf-8")

    async def loop(self):
        while True:
            await asyncio.sleep(self.every)
            print(self.line(), flush=True)
            self.write()


async def crawl_all(sources: list[Source], max_pages: int, concurrency: int, delay: float) -> dict:
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    log_file = open(config.RAW_DIR / "crawl.log", "a", encoding="utf-8")
    log = lambda msg: (log_file.write(msg + "\n"), log_file.flush())
    crawls = [SourceCrawl(s, max_pages, delay, log) for s in sources]
    reporter = Reporter(crawls, max_pages)
    sem = asyncio.Semaphore(concurrency)
    headers = {"User-Agent": config.USER_AGENT, "Accept-Language": "en,de;q=0.8"}

    async with httpx.AsyncClient(headers=headers, timeout=30, follow_redirects=True) as client:
        async def one(c: SourceCrawl):
            async with sem:
                try:
                    await c.run(client)
                except Exception as e:  # one broken site must not stop the others
                    c.stats.update(status="done", finished=_now(), error=f"{type(e).__name__}: {e}")
                st = c.stats
                print(f"  [done] {st['id']:<16} {st['saved']:>4} pages ({st['new']} new) | "
                      f"{st['errors']} errors | {st['skipped_robots']} blocked by robots.txt | "
                      f"{len(c.pdfs)} pdf links{' | ' + st['error'] if st.get('error') else ''}", flush=True)

        ticker = asyncio.create_task(reporter.loop())
        try:
            await asyncio.gather(*(one(c) for c in crawls))
        finally:
            ticker.cancel()
            reporter.write()
            log_file.close()
    print(reporter.line())
    return reporter.snapshot()
