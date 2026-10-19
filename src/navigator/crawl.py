"""Step 1 — crawl every source website into data/pages.jsonl, one cleaned page per line.

Per site: start URL first, then same-host links (team / research / service pages before the rest),
robots.txt respected, at most MAX_PAGES_PER_SOURCE pages. News, events, publication lists, legal and
teaching pages are not fetched: they rarely describe expertise. Sites already in pages.jsonl are
skipped, so a rerun only crawls newly added sources.
"""
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import urldefrag, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from . import config
from .sources import Source

SKIP = re.compile(r"\.(jpe?g|png|gif|svg|webp|ico|pdf|zip|docx?|xlsx?|pptx?|mp4|mp3|ics|vcf|css|js|xml|json)(\?|$)"
                  r"|news|aktuell|newsletter|archiv|/events?/|veranstaltung|publikation|publication|legal|"
                  r"impressum|datenschutz|privacy|lehrlingsausbildung|/studium/|/studies/|lehrveranstaltung|"
                  r"/category/|/page/\d|/jobs?\b|stellen|/tag/|/blog|/feed|login", re.I)
PRIORITY = re.compile(r"team|people|person|staff|member|mitarbeit|research|forschung|group|gruppe|lab|project|"
                      r"projekt|service|dienstleistung|infrastru|facilit|equipment|geraete|platform|expertise", re.I)
LANG_SWITCH = re.compile(r"^(en|de|fr|english|englisch|german|deutsch|français|french)$", re.I)
NOISE_TAGS = ["script", "style", "noscript", "nav", "footer", "header", "form", "svg", "iframe"]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
MIN_CHARS = 200  # shorter pages are menus or redirects


def is_english(url: str) -> bool:
    return bool(re.search(r"_eng\.html|/en/", url))


def keep(page: dict, urls: set[str]) -> bool:
    """Pages worth indexing: not news/legal/teaching, and not the German twin of a crawled English page
    (unibe.ch and dcberne.com publish most pages in both languages)."""
    if SKIP.search(page["url"]):
        return False
    return is_english(page["url"]) or not any(t in urls and is_english(t) for t in page.get("translations", []))


def parse(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    links, translations = [], []
    for a in soup.find_all("a", href=True):
        target = urldefrag(urljoin(url, a["href"].strip()))[0]
        if not target.startswith("http"):
            continue
        links.append(target)
        label = (a.get("aria-label") or a.get("title") or "").lower()
        if target != url and (a.get("hreflang") or LANG_SWITCH.match(a.get_text(strip=True))
                              or label.startswith(("wechseln zu", "switch to"))):
            translations.append(target)
    title = (soup.title.get_text(" ", strip=True) if soup.title else "") or url
    for tag in soup(NOISE_TAGS):
        tag.decompose()
    main = soup.find("main") or soup.find(id="content") or soup.body or soup
    text = re.sub(r"\n\s*\n+", "\n", main.get_text("\n", strip=True))
    return {"title": title, "text": text, "emails": sorted(set(EMAIL.findall(html))),
            "links": links, "translations": sorted(set(translations))}


def crawl_site(src: Source, max_pages: int, delay: float) -> list[dict]:
    client = httpx.Client(headers={"User-Agent": config.USER_AGENT}, follow_redirects=True, timeout=20)
    robots = RobotFileParser()
    try:
        r = client.get(urljoin(src.url, "/robots.txt"))
        robots.parse(r.text.splitlines() if r.status_code == 200 else [])
    except httpx.HTTPError:
        robots.parse([])

    first, rest = list(src.seeds()), []  # priority links go to `first`
    seen, texts, pages, fetched = set(first), set(), [], 0
    while (first or rest) and len(pages) < max_pages and fetched < 3 * max_pages:
        url = first.pop(0) if first else rest.pop(0)
        if not robots.can_fetch(config.USER_AGENT, url):
            continue
        try:
            r = client.get(url)
        except httpx.HTTPError:
            continue
        finally:
            fetched += 1
            time.sleep(delay)
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            continue
        final = str(r.url)
        page = parse(r.text, final)
        for link in page.pop("links"):
            if link not in seen and urlsplit(link).netloc.lower().removeprefix("www.") == src.host \
                    and not SKIP.search(link):
                seen.add(link)
                (first if PRIORITY.search(link) else rest).append(link)
        digest = hashlib.sha1(page["text"].encode()).hexdigest()
        if len(page["text"]) < MIN_CHARS or digest in texts:
            continue
        texts.add(digest)
        pages.append({"page_id": hashlib.sha1(final.encode()).hexdigest()[:16], "url": final, **page,
                      "source_id": src.id, "source_name": src.name, "institution": src.institution,
                      "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    client.close()
    return pages


def crawl_all(sources: list[Source], max_pages: int, delay: float, workers: int = 8) -> int:
    done = {p["source_id"] for p in config.read_jsonl(config.PAGES_FILE)}
    todo = [s for s in sources if s.id not in done]
    print(f"{len(sources) - len(todo)} sources already crawled, {len(todo)} to go")
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    with ThreadPoolExecutor(workers) as ex, open(config.PAGES_FILE, "a", encoding="utf-8") as f:
        futures = {ex.submit(crawl_site, s, max_pages, delay): s for s in todo}
        for fut in as_completed(futures):
            try:
                pages = fut.result()
            except Exception as e:  # one broken site must not stop the others
                print(f"  ! {futures[fut].id}: {e}")
                continue
            for p in pages:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
            f.flush()
            total += len(pages)
            print(f"  {futures[fut].id}: {len(pages)} pages")
    return total
