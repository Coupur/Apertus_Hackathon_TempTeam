"""Step 1: a company name, URL or idea -> a few pages of public text about the company.

url   the site's home page plus the pages most likely to say what it does and wants
      (about, products, technology, sustainability, careers, news); robots.txt obeyed.
name  Wikidata gives the official website, industry, headquarters and size, Wikipedia a summary;
      then as for a url. Without a Wikidata entry we try <name>.ch and <name>.com.
idea  the text itself is the only page; nothing is fetched.

Every page gets an id (P1, P2, ...) that the profile's quotes point back to.
"""
import re
import time
from urllib.parse import urldefrag, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from .. import config
from ..extract import extract
from ..robots import Robots

URL_RE = re.compile(r"^(https?://)?([\w-]+\.)+[a-z]{2,}(/\S*)?$", re.I)
# what a link leads to; one page of each kind is fetched before a second of any kind
PAGE_KINDS = [
    ("about", r"about|company|unternehmen|ueber|über|who-?we|mission|vision|purpose|strateg|history|geschichte|profil"),
    ("products", r"product|produkt|solution|loesung|lösung|portfolio|offer|angebot|services?\b|dienstleist|applications?"),
    ("technology", r"technolog|innovation|research|forschung|r-?and-?d|science|wissenschaft|pipeline|engineering|entwicklung"),
    ("sustainability", r"sustainab|nachhaltig|\besg\b|environment|umwelt|climate|klima|responsib|verantwortung"),
    ("careers", r"career|karriere|\bjobs?\b|stellen|join-?us|work-?with-?us|arbeiten-?bei"),
    ("news", r"news|press|medien|aktuell|stories|investor"),
]
SKIP_LINK = re.compile(r"\.(pdf|jpe?g|png|gif|svg|zip|docx?|xlsx?|mp4)$|login|account|cart|warenkorb|checkout|privacy"
                       r"|datenschutz|impressum|imprint|cookie|legal|terms|\bagb\b|sitemap|search|suche", re.I)
LANG_PREFIX = re.compile(r"^/([a-z]{2})(?:[-_][a-z]{2})?(?:/|$)", re.I)
ORG_WORDS = re.compile(r"compan|manufactur|business|enterprise|firm|start-?up|corporat|producer|maker|provider|developer"
                       r"|bank|insur|brand|group|holding|supplier|retailer|chain|cooperative|spin-?off|organi[sz]ation", re.I)
LEGAL_SUFFIX = re.compile(r"\b(ag|sa|gmbh|ltd|inc|llc|plc|s\.a\.|co\.?|corp\.?|holding)\b\.?", re.I)
MAX_CHARS_PER_PAGE = 20000  # stored; the profile prompt reads less
POSTAL_RE = re.compile(r"\b(CH[- ]?)?([1-9]\d{3})\s+([A-ZÄÖÜ][a-zäöüéè]+(?:[ -](?:bei |b\. )?[A-ZÄÖÜ][a-zäöüéè]+)?)")
BERN_TOWN = re.compile(r"(Bern|Berne|Biel|Bienne|Thun|Burgdorf|Langenthal|Köniz|Ittigen|Ostermundigen|Worb"
                       r"|Münsingen|Lyss|Interlaken|Zollikofen|Muri bei Bern|Liebefeld|Spiez|Steffisburg)\b")


def classify(text: str) -> str:
    s = text.strip()
    if URL_RE.match(s):
        return "url"
    if len(s.split()) <= 4 and not re.search(r"[.,;:!?]", s):
        return "name"
    return "idea"


class Fetcher:
    def __init__(self, trace: list[str]):
        self.trace = trace
        self.client = httpx.Client(headers={"User-Agent": config.USER_AGENT, "Accept-Language": "en,de;q=0.8"},
                                   follow_redirects=True, timeout=20)
        self.robots: dict[str, Robots | None] = {}
        self.last: dict[str, float] = {}

    def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        host = parts.netloc
        if host not in self.robots:
            try:
                r = self.client.get(f"{parts.scheme}://{host}/robots.txt")
                self.robots[host] = Robots(r.text, config.USER_AGENT) if r.status_code == 200 else None
            except httpx.HTTPError:
                self.robots[host] = None
        rb = self.robots[host]
        return rb is None or rb.can_fetch(url)

    def page(self, url: str) -> httpx.Response | None:
        """One HTML page, politely: robots.txt and CRAWL_DELAY_S between requests to the same host."""
        if not self._allowed(url):
            self.trace.append(f"robots.txt forbids {url}")
            return None
        host = urlsplit(url).netloc
        wait = self.last.get(host, 0) + config.CRAWL_DELAY_S - time.time()
        if wait > 0:
            time.sleep(wait)
        self.last[host] = time.time()
        try:
            r = self.client.get(url)
        except httpx.HTTPError as e:
            self.trace.append(f"fetch failed {url}: {type(e).__name__}")
            return None
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            self.trace.append(f"skipped {url}: HTTP {r.status_code} {r.headers.get('content-type', '')}")
            return None
        return r

    def json(self, url: str, **params) -> dict | None:
        try:
            r = self.client.get(url, params=params or None)
            return r.json() if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            return None


# ---------- name -> website and facts ----------

def _claim_ids(claims: dict, prop: str) -> list[str]:
    out = []
    for c in claims.get(prop, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, dict) and "id" in v:
            out.append(v["id"])
    return out


def _claim_value(claims: dict, prop: str):
    for c in claims.get(prop, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if v is not None:
            return v
    return None


def wikidata(f: Fetcher, name: str) -> dict | None:
    """Best Wikidata match for a company name: website, industry, HQ, country, staff, founding year, Wikipedia."""
    found = f.json("https://www.wikidata.org/w/api.php", action="wbsearchentities", search=name, language="en",
                   type="item", limit=7, format="json")
    hits = (found or {}).get("search", [])
    best = None
    for hit in hits:
        data = f.json(f"https://www.wikidata.org/wiki/Special:EntityData/{hit['id']}.json")
        ent = (data or {}).get("entities", {}).get(hit["id"])
        if not ent:
            continue
        has_site = "P856" in ent.get("claims", {})
        is_org = bool(ORG_WORDS.search(hit.get("description", "")))
        rank = 2 * has_site + is_org
        if rank and (best is None or rank > best[0]):
            best = (rank, hit, ent)
        if rank == 3:
            break
    if not best:
        return None
    _, hit, ent = best
    claims = ent["claims"]
    ids = {p: _claim_ids(claims, p) for p in ("P452", "P159", "P17")}
    want = sorted({i for v in ids.values() for i in v})
    labels = {}
    if want:
        got = f.json("https://www.wikidata.org/w/api.php", action="wbgetentities", ids="|".join(want[:40]),
                     props="labels", languages="en|de", format="json") or {}
        for qid, e in got.get("entities", {}).items():
            lab = e.get("labels", {})
            labels[qid] = (lab.get("en") or lab.get("de") or {}).get("value", qid)
    staff = _claim_value(claims, "P1128")
    inception = _claim_value(claims, "P571")
    sitelinks = ent.get("sitelinks", {})
    wiki = next(((lang, sitelinks[f"{lang}wiki"]["title"]) for lang in ("en", "de") if f"{lang}wiki" in sitelinks), None)
    return {
        "qid": hit["id"], "label": hit.get("label", name), "description": hit.get("description", ""),
        "website": _claim_value(claims, "P856"),
        "industry": [labels.get(i, i) for i in ids["P452"]],
        "headquarters": [labels.get(i, i) for i in ids["P159"]],
        "country": [labels.get(i, i) for i in ids["P17"]],
        "employees": int(float(staff["amount"])) if isinstance(staff, dict) and "amount" in staff else None,
        "founded": inception["time"][1:5] if isinstance(inception, dict) and "time" in inception else None,
        "wikipedia": wiki,
    }


def wikipedia_summary(f: Fetcher, lang: str, title: str) -> dict | None:
    data = f.json(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title.replace(' ', '_')}")
    if not data or not data.get("extract"):
        return None
    url = data.get("content_urls", {}).get("desktop", {}).get("page") or f"https://{lang}.wikipedia.org/wiki/{title}"
    return {"url": url, "title": f"Wikipedia: {data.get('title', title)}", "kind": "wikipedia", "text": data["extract"]}


def guess_website(f: Fetcher, name: str) -> str | None:
    core = LEGAL_SUFFIX.sub(" ", name).strip().lower()
    token = re.sub(r"[^a-z0-9]", "", core.split()[0]) if core else ""
    slugs = dict.fromkeys([re.sub(r"[^a-z0-9]", "", core), re.sub(r"[^a-z0-9]+", "-", core).strip("-")])
    for slug in filter(None, slugs):
        for tld in ("ch", "com"):
            url = f"https://www.{slug}.{tld}/"
            r = f.page(url)
            if r is not None and token and token in r.text[:20000].lower():
                return str(r.url)
    return None


# ---------- website -> pages ----------

def _same_site(a: str, b: str) -> bool:
    ha, hb = (urlsplit(u).netloc.lower().removeprefix("www.") for u in (a, b))
    return ha == hb or ha.endswith("." + hb) or hb.endswith("." + ha)


def _lang(url: str) -> str | None:
    m = LANG_PREFIX.match(urlsplit(url).path)
    return m.group(1).lower() if m else None


def _meta(soup: BeautifulSoup) -> dict:
    def content(**attrs):
        tag = soup.find("meta", attrs=attrs)
        return tag.get("content", "").strip() if tag else ""
    html = soup.find("html")
    return {"description": content(name="description") or content(property="og:description"),
            "site_name": content(property="og:site_name"),
            "title": soup.title.get_text(" ", strip=True) if soup.title else "",
            "lang": (html.get("lang", "") if html else "")[:2].lower(),
            "headings": [h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2"])][:25],
            "addresses": addresses(soup.get_text(" "))}


def addresses(text: str) -> list[dict]:
    """Swiss postal addresses ("CH-3401 Burgdorf", "8802 Kilchberg ... Switzerland"), usually in the
    footer, which the page text drops. bern: the town or the postcode is in the Canton of Bern."""
    out = []
    for m in POSTAL_RE.finditer(text):
        swiss = bool(m.group(1)) or re.search(r"switzerland|schweiz|suisse|svizzera", text[m.end():m.end() + 80], re.I)
        code, town = int(m.group(2)), m.group(3)
        if not swiss and not BERN_TOWN.match(town):
            continue
        bern = bool(BERN_TOWN.match(town)) or 2500 <= code < 2800 or 3000 <= code < 3900
        entry = {"postcode": code, "town": town, "bern": bern}
        if entry not in out:
            out.append(entry)
    return out[:5]


def _pick_links(soup: BeautifulSoup, home: str, base: str, n: int) -> list[tuple[str, str, str]]:
    """Up to n (kind, url, anchor) links worth reading, one per kind first, shallow paths first."""
    home_lang = _lang(home)
    seen, by_kind = {urldefrag(home)[0].rstrip("/")}, {k: [] for k, _ in PAGE_KINDS}
    for a in soup.find_all("a", href=True):
        url = urldefrag(urljoin(base, a["href"].strip()))[0]
        if not url.startswith("http") or not _same_site(url, home) or SKIP_LINK.search(url):
            continue
        key = url.rstrip("/")
        if key in seen:
            continue
        lang = _lang(url)
        if lang and lang != (home_lang or lang) or (lang and not home_lang and lang not in ("en", "de")):
            continue
        anchor = a.get_text(" ", strip=True)[:80]
        path = urlsplit(url).path.lower()
        for kind, rx in PAGE_KINDS:
            in_anchor, in_path = re.search(rx, anchor, re.I), re.search(rx, path)
            if in_anchor or in_path:
                seen.add(key)
                by_kind[kind].append((0 if in_anchor else 1, path.count("/"), url, anchor))
                break
    for links in by_kind.values():
        links.sort()
    picks = []
    while len(picks) < n and any(by_kind.values()):
        for kind, _ in PAGE_KINDS:
            if by_kind[kind] and len(picks) < n:
                _, _, url, anchor = by_kind[kind].pop(0)
                picks.append((kind, url, anchor))
    return picks


def _page(url: str, html: str, kind: str) -> dict:
    ex = extract(html, url)
    return {"url": url, "title": ex["title"], "kind": kind, "text": ex["text"][:MAX_CHARS_PER_PAGE]}


def _english_version(soup: BeautifulSoup, home: str) -> str | None:
    """The English home page, if this one is in another language and links to it."""
    if _lang(home) in (None, "en"):
        return None
    alt = soup.find("link", rel="alternate", hreflang=re.compile(r"^en", re.I), href=True)
    if alt:
        return urljoin(home, alt["href"])
    for a in soup.find_all("a", href=True):
        url = urljoin(home, a["href"])
        if _same_site(url, home) and _lang(url) == "en" and urlsplit(url).path.strip("/").count("/") == 0:
            return url
    return None


def fetch_site(f: Fetcher, url: str, max_pages: int) -> tuple[list[dict], dict]:
    r = f.page(url)
    if r is None:
        return [], {}
    soup = BeautifulSoup(r.text, "html.parser")
    en = _english_version(soup, str(r.url))
    if en and (r_en := f.page(en)) is not None:
        f.trace.append(f"switched to the English site {r_en.url}")
        r, soup = r_en, BeautifulSoup(r_en.text, "html.parser")
    home = str(r.url)
    base = soup.find("base", href=True)
    base_url = urljoin(home, base["href"]) if base else home  # relative links resolve against <base href>
    meta = _meta(soup)
    pages = [_page(home, r.text, "home")]
    for kind, link, anchor in _pick_links(soup, home, base_url, max_pages - 1):
        sub = f.page(link)
        if sub is not None:
            pages.append(_page(str(sub.url), sub.text, kind))
            f.trace.append(f"read {kind:14} {link}  ({anchor!r})")
    if sum(len(p["text"]) for p in pages) < 500:
        f.trace.append("site gave almost no text: probably built by JavaScript or blocks our crawler")
    return pages, meta


# ---------- entry point ----------

def collect(inp: str, kind: str = "auto", max_pages: int = 8) -> dict:
    inp = inp.strip()
    kind = classify(inp) if kind == "auto" else kind
    trace = [f"input classified as {kind}"]
    f = Fetcher(trace)
    out = {"input": inp, "kind": kind, "name": None, "website": None, "facts": None, "meta": {}, "pages": [],
           "trace": trace}

    if kind == "name":
        facts = wikidata(f, inp)
        if facts:
            out["facts"], out["name"] = facts, facts["label"]
            trace.append(f"wikidata {facts['qid']} {facts['label']} ({facts['description']}) -> {facts['website']}")
            out["website"] = facts["website"]
        else:
            trace.append("no company found on Wikidata")
        if not out["website"]:
            out["website"] = guess_website(f, inp)
            trace.append(f"guessed website: {out['website']}" if out["website"] else "no website found")
        out["name"] = out["name"] or inp
    elif kind == "url":
        out["website"] = inp if inp.startswith("http") else f"https://{inp}"

    if out["website"]:
        pages, meta = fetch_site(f, out["website"], max_pages)
        out["pages"] += pages
        out["meta"] = meta
        if pages:
            out["website"] = pages[0]["url"]
    if out["facts"]:
        if out["facts"]["wikipedia"]:
            wp = wikipedia_summary(f, *out["facts"]["wikipedia"])
            if wp:
                out["pages"].append(wp)
        fx = out["facts"]
        lines = [f"{fx['label']}: {fx['description']}",
                 f"Industry: {', '.join(fx['industry'])}" if fx["industry"] else "",
                 f"Headquarters: {', '.join(fx['headquarters'])}" if fx["headquarters"] else "",
                 f"Country: {', '.join(fx['country'])}" if fx["country"] else "",
                 f"Employees: {fx['employees']}" if fx["employees"] else "",
                 f"Founded: {fx['founded']}" if fx["founded"] else ""]
        out["pages"].append({"url": f"https://www.wikidata.org/wiki/{fx['qid']}", "title": f"Wikidata: {fx['label']}",
                             "kind": "wikidata", "text": "\n".join(l for l in lines if l)})

    if not out["pages"]:
        if kind != "idea":
            trace.append("nothing found online: the input text is the only description")
        out["pages"].append({"url": "", "title": "Description given by the user", "kind": "input", "text": inp})
    if not out["name"]:
        meta = out["meta"]
        out["name"] = (meta.get("site_name") or re.split(r"\s[|–—-]\s", meta.get("title", ""))[0].strip()
                       or (urlsplit(out["website"]).netloc.removeprefix("www.").split(".")[0].capitalize()
                           if out["website"] else " ".join(inp.split()[:6])))
    for i, p in enumerate(out["pages"], 1):
        p["id"] = f"P{i}"
    return out
