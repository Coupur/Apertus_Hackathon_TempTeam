"""Focused frontier, temporary document processing, and bounded run reporting."""
import asyncio
import hashlib
import heapq
import json
import re
import time
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from ..extract import chunk, extract
from ..sources import Source, _from_xlsx
from .keywords import KEYWORD_VOCABULARY_VERSION, keyword_priority, record_keywords
from .models import Document, Settings
from .selection import RULESET_VERSION, evaluate, validate_findings
from .store import Store, identity_keys, refresh_keywords, refresh_evaluations
from .ranking import score_record, rank, ranking_summary, SELECTION_VERSION
from .entities import extract_entities, ENTITY_VERSION
from .privacy import clean_text
from .web import Boundary, BudgetExceeded, FetchError, Fetcher, host, normalize_url

IMPORTANT = re.compile(r"research|forschung|project|projekt|flagship|breakthrough|innovation|achievement|award|grant|transfer|patent|spin.?off|infrastructure|facility|facilities|service|platform|news|aktuell|archive|archiv|publication|publikation|ergebnis|entdeckung", re.I)
ROUTINE = re.compile(r"(?:^|[/ _-])(?:jobs?|vacanc\w*|careers?|karriere|stellen\w*|impressum|privacy|datenschutz|login|logout|search|suche|agenda|calendar|kalender)(?:[/ _?.-]|$)", re.I)
EDUCATION_PATH = re.compile(r"^/(?:studies|studium|teaching|courses|lectures|lehre)(?:/|$)", re.I)
SKIP_FILE = re.compile(r"\.(?:pdf|jpe?g|png|gif|webp|svg|ico|zip|docx?|xlsx?|pptx?|mp[34]|wav|css|js|xml|ics|vcf)(?:$|\?)", re.I)
API_PATH = "/wp-json/wp/v2/"
API_TYPES = ("project", "publication", "posts", "pages")
API_PRIORITY = {"project": 230, "posts": 220, "pages": 200, "publication": 80}
OUTCOME = re.compile(r"clinical|validated|demonstrat|licensed|approved|breakthrough|entdeckung|nachgewiesen|nccr|core facilit|organs.on.chip", re.I)
ANNOUNCEMENT = re.compile(r"newsletter|call for|applications? open|conference|anniversary|seminar|defen[cs]e|ausschreibung|veranstaltung", re.I)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def focused_sources() -> list[Source]:
    """Only the supplied inventory and the two explicitly requested centers."""
    by_host = {s.host: s for s in _from_xlsx()}
    for s in (Source("artorg", "ARTORG Center for Biomedical Engineering Research", "https://www.artorg.unibe.ch/", "ARTORG"),
              Source("dcberne", "Diabetes Center Berne", "https://www.dcberne.com/", "Diabetes Center Berne")):
        by_host[s.host] = s
    return list(by_host.values())


def page_links(html: str, base: str) -> list[tuple[str, str, str]]:
    if "<" not in html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    result = []
    for node in soup.select("a[href]"):
        url = normalize_url(urljoin(base, node["href"]))
        if not url:
            continue
        context = node.parent.get_text(" ", strip=True)[:500] if node.parent else ""
        result.append((url, node.get_text(" ", strip=True)[:200], context))
    return result


def priority(url: str, anchor: str, context: str, parent_title: str, depth: int) -> float:
    # Specific anchor/context signals dominate generic template navigation.
    archive_link = (re.search(r"news|aktuell|archive|archiv", parent_title, re.I)
                    and (re.search(r"\b\d{4}\b|older|next|previous|ältere|weitere|nächste", anchor, re.I)
                         or re.search(r"/\d{4}(?:/|$)", urlsplit(url).path)))
    return ((8 if archive_link else 0) + (18 if OUTCOME.search(anchor + " " + urlsplit(url).path) else 0)
            + keyword_priority(anchor + " " + unquote(urlsplit(url).path))
            - (16 if ANNOUNCEMENT.search(anchor + " " + urlsplit(url).path) else 0)
            + 4 * len(IMPORTANT.findall(anchor)) + 2 * len(IMPORTANT.findall(urlsplit(url).path))
            + min(4, len(IMPORTANT.findall(context))) + min(2, len(IMPORTANT.findall(parent_title)))
            - depth * 0.75 - (4 if re.search(r"people|staff|team|personen|mitarbeit", url, re.I) else 0))


def prefilter(document: Document) -> str | None:
    if (ROUTINE.search(urlsplit(document.url).path) or ROUTINE.search(document.title)
            or EDUCATION_PATH.search(urlsplit(document.url).path)):
        return "routine_content"
    if len(document.text.strip()) < 160:
        return "insufficient_content"
    return None


def plain(value) -> str:
    if isinstance(value, str):
        return extract(value, "", paragraphs=True)["text"] if "<" in value else unescape(value)
    if isinstance(value, dict):
        return "\n".join(plain(v) for k, v in value.items() if k not in ("url", "sizes", "image", "id", "ID"))
    if isinstance(value, list):
        return "\n".join(plain(v) for v in value)
    return ""


def fragments(value):
    """Yield API content strings, including reference URLs, without image metadata."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, child in value.items():
            if key not in ("sizes", "image", "id", "ID"):
                yield from fragments(child)
    elif isinstance(value, list):
        for child in value:
            yield from fragments(child)


def consolidate(records: list[dict]) -> list[dict]:
    """Combine overlapping chunks before replacing a source's previous observation."""
    groups = []
    for record in records:
        keys = identity_keys(record)
        matches = [group for group in groups if keys & group[0]]
        candidates = [record]
        for group in matches:
            keys |= group[0]
            candidates.extend(group[1])
            groups.remove(group)
        groups.append((keys, candidates))
    output = []
    for _, candidates in groups:
        best = max(candidates, key=rank)
        result = {**best}
        for field, bound in (("evidence", 20), ("identifiers", 10), ("organizations", 3), ("experts", 10)):
            unique = {}
            for item in [best, *candidates]:
                for value in item[field]:
                    unique[json.dumps(value, sort_keys=True)] = value
            result[field] = list(unique.values())[:bound]
        result["keywords"] = record_keywords(result)
        score_record(result)
        output.append(result)
    return output


class Crawler:
    def __init__(self, sources: list[Source], store: Store, settings: Settings, evaluator=evaluate, progress=None, checkpoint=None):
        self.sources = {s.host: s for s in sources}
        self.store, self.settings, self.evaluator, self.progress = store, settings, evaluator, progress
        self.checkpoint = checkpoint
        self.last_checkpoint = 0.0
        self.traversal_version = "complete-v1:" + RULESET_VERSION + ":" + SELECTION_VERSION + ":" + ENTITY_VERSION
        self.boundary = Boundary([s.url for s in sources])
        self.queue = []
        self.queued: set[str] = set()
        self.seen = store.completed_urls(self.traversal_version) if settings.complete and not settings.reevaluate else set()
        self.pending_updates: dict[str, dict] = {}
        self.hashes: set[str] = set()
        self.rejections = Counter()
        self.errors = Counter()
        self.selection_evaluations = 0
        self.fingerprint = RULESET_VERSION + ":" + SELECTION_VERSION + ":" + ENTITY_VERSION
        self.report = {"started_at": now(), "mode": "source_check" if settings.source_check else "collection",
                       "selection_method": "rules", "ruleset_version": RULESET_VERSION,
                       "traversal_mode": "complete" if settings.complete else "focused_budget",
                       "resumed_checked_urls": len(self.seen),
                       "documents_considered": 0,
                       "candidates_considered": 0, "accepted_observations": 0,
                       "rejected_candidates": 0,
                       "unchanged_documents": 0, "duplicate_documents": 0, "truncated_documents": 0,
                       "outside_links_not_followed": 0, "frontier_dropped": 0,
                       "coverage": {s.id: {"url": s.url, "documents": 0, "fetches": 0, "errors": 0} for s in sources}}

    def enqueue(self, url: str, score: float = 0, depth: int = 0, found_on: str = "seed"):
        url = normalize_url(url)
        if not self.boundary.allows(url):
            return
        if url in self.queued or url in self.seen or (not self.settings.complete and depth > self.settings.max_depth):
            return
        if (len(url) > 1500 or SKIP_FILE.search(url) or ROUTINE.search(urlsplit(url).path)
                or EDUCATION_PATH.search(urlsplit(url).path)):
            return
        if any(k.lower() in ("replytocom", "share", "print", "s", "search", "q") for k, _ in parse_qsl(urlsplit(url).query)):
            return
        if not self.settings.complete and len(self.queue) >= self.settings.max_frontier:
            self.report["frontier_dropped"] += 1
            worst = max(self.queue)
            if (-score, depth, url, found_on) >= worst:
                return
            self.queue.remove(worst)
            self.queued.discard(worst[2])
            heapq.heapify(self.queue)
        self.queued.add(url)
        heapq.heappush(self.queue, (-score, depth, url, found_on))
        if self.settings.complete:
            self.pending_updates[url] = {"status": "pending", "score": score, "depth": depth, "found_on": found_on}

    def seed(self):
        for source in self.sources.values():
            self.enqueue(source.url, 1000)
            if source.id == "dcberne" and not self.settings.source_check:
                for kind in API_TYPES:
                    self.enqueue(urljoin(source.url, API_PATH + kind + "?per_page=20&page=1"), API_PRIORITY[kind])
        if not self.settings.source_check:
            for url, state in self.store.pending(include_failed=self.settings.complete):
                self.enqueue(url, state.get("score", 0), state.get("depth", 1), state.get("found_on", "resume"))

    def batch(self) -> list[tuple]:
        picked, skipped, domains = [], [], set()
        while self.queue and len(picked) < self.settings.concurrency:
            entry = heapq.heappop(self.queue)
            if entry[2] in self.seen:
                self.queued.discard(entry[2])
                continue
            domain = host(entry[2])
            if domain in domains:
                skipped.append(entry)
                continue
            domains.add(domain)
            self.queued.discard(entry[2])
            self.seen.add(entry[2])
            picked.append(entry)
        for entry in skipped:
            heapq.heappush(self.queue, entry)
        return picked

    def html_document(self, response, depth: int) -> Document:
        source = self.sources[host(response.url)]
        page = extract(response.text, response.url, paragraphs=True)
        references = []
        for url, anchor, context in page_links(response.text, response.url):
            if self.boundary.allows(url):
                if not self.settings.source_check:
                    score = priority(url, anchor, context, page["title"], depth + 1)
                    # Homepage sections form the initial survey; later traversal needs a signal.
                    if self.settings.complete or depth == 0 or score > 0:
                        self.enqueue(url, score + (100 if depth == 0 and IMPORTANT.search(anchor) else 0), depth + 1, response.url)
            else:
                self.report["outside_links_not_followed"] += 1
                if IMPORTANT.search(anchor + " " + context) or "doi.org" in url:
                    references.append(url)
        return Document(response.url, page["title"], clean_text(page["text"]), source.id, source.institution,
                        now(), response.url, tuple(dict.fromkeys(references))[:20], tuple(page_links(response.text,response.url)))

    def api_documents(self, response, depth: int) -> list[Document]:
        data = json.loads(response.text)
        if not isinstance(data, list):
            raise FetchError("invalid_api_response")
        source = self.sources[host(response.url)]
        docs = []
        for item in data[:20]:
            if not isinstance(item, dict):
                continue
            url = normalize_url(item.get("link", ""))
            if not self.boundary.allows(url):
                continue
            title = plain(item.get("title", {}))
            body = "\n".join(plain(item.get(key, "")) for key in ("content", "excerpt", "acf"))
            if len(re.sub(r"https?://\S+", "", body).strip()) < 80:
                # A long title or timestamp is not a substantive API response.
                self.enqueue(url, 15, depth + 1, response.url)
                self.report["api_page_fallbacks"] = self.report.get("api_page_fallbacks", 0) + 1
                continue
            content = title + "\n" + body
            if item.get("date"):
                content += "\nSource publication date: " + str(item["date"])
            references = []
            for field in ("content", "excerpt", "acf"):
                for fragment in fragments(item.get(field, "")):
                    links = page_links(fragment, url)
                    if normalize_url(fragment):
                        links.append((normalize_url(fragment), "Reference", title))
                    for link, anchor, context in links:
                        if self.boundary.allows(link):
                            score = priority(link, anchor, context, title, depth + 1)
                            if self.settings.complete or score > 0:
                                self.enqueue(link, score, depth + 1, url)
                        elif link not in references and len(references) < 20:
                            references.append(link)
                            self.report["outside_links_not_followed"] += 1
            # Explicit reference URLs can supply a DOI identity without contacting publishers.
            if references:
                content += "\nSource references: " + " ".join(references)
            docs.append(Document(url, title, content, source.id, source.institution, now(), response.url, tuple(references)))
        parts = urlsplit(response.url)
        params = dict(parse_qsl(parts.query))
        page = int(params.get("page", 1))
        pages = int(response.headers.get("x-wp-totalpages", "1"))
        if page < pages:
            params["page"] = str(page + 1)
            self.enqueue(urlunsplit(parts._replace(query=urlencode(params))), 10, depth, response.url)
        return docs

    async def process(self, document: Document):
        """Select candidates locally; failed evaluations preserve prior observations."""
        self.report["documents_considered"] += 1
        self.report["coverage"][document.source_id]["documents"] += 1
        if self.settings.source_check:
            return
        rejection = prefilter(document)
        digest = hashlib.sha256((document.title + "\n" + document.text).encode()).hexdigest()
        previous = self.store.state(document.url)
        if rejection:
            self.rejections[rejection] += 1
            return
        if not self.settings.reevaluate and previous.get("hash") == digest and previous.get("evaluated") == self.fingerprint:
            self.report["unchanged_documents"] += 1
            return
        if digest in self.hashes:
            self.report["duplicate_documents"] += 1
            return
        self.hashes.add(digest)
        if len(document.text) > 36000:
            self.report["truncated_documents"] += 1
        successful = True
        drafts = []
        for text in chunk(document.text[:36000], size=12000, overlap=500):
            self.selection_evaluations += 1
            piece = replace(document, text=text)
            try:
                raw = await asyncio.to_thread(self.evaluator, piece)
                records, rejected = validate_findings(raw, piece)
                self.rejections.update(rejected)
                self.report["rejected_candidates"] += sum(rejected.values()) - rejected.get("invalid_response", 0)
                if isinstance(raw, dict) and isinstance(raw.get("findings"), list):
                    self.report["candidates_considered"] += len(raw["findings"])
                    if not raw["findings"]:
                        self.rejections["no_significant_finding"] += 1
                if any(reason != "below_threshold" for reason in rejected):
                    successful = False
                drafts.extend(records)
                self.report["accepted_observations"] += len(records)
            except Exception as error:
                self.errors[f"selection_{type(error).__name__}"] += 1
                successful = False
        works = consolidate(drafts)
        accepted_ids = set()
        for work in works:
            work["id"] = self.store.upsert(work)
            accepted_ids.add(work["id"])
        entities = extract_entities(document, works)
        for entity in entities:
            entity["source_read_version"] = SELECTION_VERSION
            entity["id"] = self.store.upsert(entity)
            accepted_ids.add(entity["id"])
        for work in works:
            for entity in entities:
                for link in entity["related_works"]:
                    if link["work_id"] == work["id"]:
                        field = "experts" if entity["type"] == "expert" else "teams"
                        work.setdefault(field, []).append({"id":entity["id"],"name":entity["original_name"],
                            "role":link["role"],"source_url":link["source_url"],"quote":link["quote"]})
            if work.get("experts") or work.get("teams"):
                self.store.upsert(work)
        if successful and len(document.text) <= 36000:
            self.store.reconcile_source(document.url, accepted_ids)
        self.store.save_state(document.url, {"hash": digest, "evaluated": self.fingerprint if successful else None,
                                            "status": "checked"}, document.fetched_at)

    async def run(self, client: httpx.AsyncClient) -> dict:
        self.seed()
        fetcher = Fetcher(client, self.boundary, self.settings)
        reason = "frontier_exhausted"
        while self.queue:
            if not self.settings.complete and fetcher.content_requests >= self.settings.max_fetches:
                reason = "fetch_budget"
                break
            batch = self.batch()
            self.store.save_pending(self.pending_updates, now())
            self.pending_updates.clear()
            try:
                responses = await asyncio.gather(*(fetcher.get(entry[2]) for entry in batch), return_exceptions=True)
            except asyncio.CancelledError:
                reason = "interrupted"
                break
            exhausted = False
            for entry, response in zip(batch, responses):
                negscore, depth, url, found_on = entry
                source = self.sources[host(url)]
                coverage = self.report["coverage"][source.id]
                if isinstance(response, BaseException):
                    if isinstance(response, BudgetExceeded):
                        exhausted, reason = True, "fetch_budget"
                        self.store.save_state(url, {"status": "pending", "score": -negscore,
                                                   "depth": depth, "found_on": found_on}, now())
                    else:
                        error_key = str(response) if isinstance(response, FetchError) else type(response).__name__
                        self.errors[error_key] += 1
                        coverage["errors"] += 1
                        self.store.save_state(url, {"status": "failed", "error": error_key, "score": -negscore,
                                                   "depth": depth, "found_on": found_on}, now())
                    continue
                coverage["fetches"] += 1
                self.seen.add(normalize_url(response.url))
                try:
                    if "html" in response.content_type:
                        docs = [self.html_document(response, depth)]
                    elif ("json" in response.content_type and host(response.url) == "dcberne.com"
                          and urlsplit(response.url).path.rstrip("/").split("/")[-1] in API_TYPES
                          and urlsplit(response.url).path.startswith(API_PATH)):
                        docs = self.api_documents(response, depth)
                    else:
                        self.rejections["unsupported_content_type"] += 1
                        docs = []
                    for doc in docs:
                        await self.process(doc)
                    state = self.store.state(response.url)
                    if response.url != url:
                        self.store.save_state(url, {"status": "checked", "final_url": response.url,
                                                   "traversal_version": self.traversal_version if self.settings.complete else None}, now())
                    if not state.get("hash"):
                        state["status"] = "checked"
                    if self.settings.complete:
                        retry = any((s := self.store.state(doc.url)).get("hash") and s.get("evaluated") != self.fingerprint for doc in docs)
                        if retry:
                            state.update(status="failed", error="selection_retry", score=-negscore, depth=depth,
                                         found_on=found_on, traversal_version=None)
                        else:
                            state["traversal_version"] = self.traversal_version
                    self.store.save_state(response.url, state, now())
                except (ValueError, TypeError, FetchError) as error:
                    self.errors[f"parse_{type(error).__name__}"] += 1
                    coverage["errors"] += 1
                    self.store.save_state(url, {"status": "failed", "error": f"parse_{type(error).__name__}",
                                               "score": -negscore, "depth": depth, "found_on": found_on}, now())
                except asyncio.CancelledError:
                    exhausted, reason = True, "interrupted"
                    break
            if self.progress:
                budget = "unlimited" if self.settings.complete else self.settings.max_fetches
                self.progress(f"Fetched {fetcher.content_requests}/{budget}; queued {len(self.queue)}; "
                              f"rule evaluations {self.selection_evaluations}; "
                              f"retained {len(self.store.findings())} findings")
            if self.checkpoint and time.monotonic() - self.last_checkpoint >= 30:
                self.checkpoint(self.snapshot(fetcher, "running"))
                self.last_checkpoint = time.monotonic()
            if exhausted:
                break
        self.store.save_pending(self.pending_updates, now())
        self.pending_updates.clear()
        for negscore, depth, url, found_on in self.queue:
            self.store.save_state(url, {"status": "pending", "score": -negscore, "depth": depth, "found_on": found_on}, now())
        if not self.settings.source_check:
            with self.store.db:
                self.store._trim()
        self.report = self.snapshot(fetcher, reason)
        self.store.finish(self.report, None if self.settings.complete else self.settings.max_frontier)
        return self.report

    def snapshot(self, fetcher: Fetcher, reason: str) -> dict:
        report = {**self.report}
        report.update(updated_at=now(), finished_at=None if reason == "running" else now(),
                           stopping_reason=reason, content_fetches=fetcher.content_requests,
                           robots_fetches=fetcher.robots_requests, selection_evaluations=self.selection_evaluations,
                           retained_findings=len(self.store.findings()), pending_urls=len(self.queue) if reason == "running" else len(self.store.pending()),
                           rejection_reasons=dict(self.rejections), errors=dict(self.errors),
                           limits={"content_fetches": None if self.settings.complete else self.settings.max_fetches,
                                   "findings": self.settings.max_findings,
                                   "depth": None if self.settings.complete else self.settings.max_depth,
                                   "frontier": None if self.settings.complete else self.settings.max_frontier},
                           exhaustive=False)
        report["selection_threshold"] = 2
        report["keyword_vocabulary_version"] = KEYWORD_VOCABULARY_VERSION
        report["ranking"] = ranking_summary(self.store.findings())
        report["retained_by_priority"] = dict(Counter(
            "entity" if record["type"] in ("expert", "team") else "high_priority" if max(record["scores"].values()) >= 3 else "substantive"
            for record in self.store.findings()))
        return report


async def run_crawl(path: Path, settings: Settings, only: list[str] | None = None, progress=None, checkpoint=None) -> dict:
    sources = focused_sources()
    if only:
        unknown = set(only) - {s.id for s in sources}
        if unknown:
            raise ValueError("Unknown source IDs: " + ", ".join(sorted(unknown)))
        sources = [s for s in sources if s.id in only]
    store = Store(path, settings.max_findings)
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            return await Crawler(sources, store, settings, progress=progress, checkpoint=checkpoint).run(client)
    finally:
        store.close()
