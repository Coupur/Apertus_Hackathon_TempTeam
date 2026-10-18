"""Company-name web enrichment.

Given a company name (and optional website), search the public web, gather a
short context window, then optionally ask Kimi k2.6 to synthesize a summary.
Falls back to Wikipedia + DuckDuckGo when Moonshot search/LLM is unavailable.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .kimi_summary import _load_dotenv, kimi_configured, summarize_company_text, summary_model_label

_UA = (
    "Mozilla/5.0 (compatible; BernCompanyMatch/0.3; +https://localhost) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


@dataclass
class WebEnrichment:
    company_name: str
    resolved_name: str = ""
    context: str = ""
    summary: str | None = None
    keywords: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    method: str = "none"  # moonshot+kimi | wiki+ddg | moonshot | rules
    warnings: list[str] = field(default_factory=list)


# Common life-science typos / shorthand → canonical search name
_NAME_ALIASES: dict[str, str] = {
    "norvatis": "Novartis",
    "novatis": "Novartis",
    "novartiss": "Novartis",
    "novartis ag": "Novartis",
    "pfiser": "Pfizer",
    "pfizzer": "Pfizer",
    "astrazenica": "AstraZeneca",
    "astra zeneca": "AstraZeneca",
    "janssen": "Johnson & Johnson",
    "j&j": "Johnson & Johnson",
    "gs k": "GSK",
    "glaxosmithkline": "GSK",
    "boehringer": "Boehringer Ingelheim",
    "sanofii": "Sanofi",
    "merck kgaa": "Merck KGaA",
    "bms": "Bristol Myers Squibb",
    "amedisys": "Amedisys",
}


def _http_json(url: str, *, timeout: float = 10.0) -> Any | None:
    from . import budget

    if not budget.has(3):
        return None
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=budget.clamp(timeout)) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception:
        return None


def _http_text(url: str, *, timeout: float = 10.0) -> str:
    from . import budget

    if not budget.has(3):
        return ""
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "text/html,application/json"})
    try:
        with urllib.request.urlopen(req, timeout=budget.clamp(timeout)) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _moonshot_web_search(query: str, *, limit: int = 5) -> list[dict[str, str]]:
    """Moonshot POST /v1/tools/search — used when API key has credit."""
    _load_dotenv()
    key = os.getenv("KIMI_API_KEY") or os.getenv("MOONSHOT_API_KEY")
    if not key:
        return []
    base = (os.getenv("KIMI_BASE_URL") or "https://api.moonshot.ai/v1").rstrip("/")
    endpoint = f"{base}/tools/search"
    payload = {"text_query": query, "limit": limit, "include_content": False}
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    try:
        from . import budget

        with urllib.request.urlopen(req, timeout=budget.clamp(8)) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []
    out: list[dict[str, str]] = []
    for hit in body.get("search_results") or []:
        out.append(
            {
                "title": str(hit.get("title") or ""),
                "url": str(hit.get("url") or ""),
                "snippet": str(hit.get("snippet") or hit.get("text") or "")[:600],
            }
        )
    return out


def _name_tokens(name: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", name.lower()) if len(t) >= 3}


def _levenshtein(a: str, b: str) -> int:
    a, b = a.lower(), b.lower()
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _fuzzy_name_match(seed: str, candidate: str) -> bool:
    """True when candidate looks like a typo/correction of seed (norvatis→Novartis)."""
    s = re.sub(r"[^a-z0-9]", "", (seed or "").lower())
    c = re.sub(r"[^a-z0-9]", "", (candidate or "").lower().split("(")[0])
    if not s or not c:
        return False
    if s == c or c.startswith(s) or s.startswith(c):
        return True
    # Allow small edit distance for short brand names
    max_dist = 1 if len(s) <= 5 else (2 if len(s) <= 10 else 3)
    return _levenshtein(s, c) <= max_dist


def _looks_like_company_hit(name: str, title: str, snippet: str) -> bool:
    """Reject near-misses like ARKRAY → Arkansas; allow fuzzy brand typos."""
    name_l = name.lower().strip()
    title_l = (title or "").lower()
    snip_l = (snippet or "").lower()
    title_core = title_l.split("(")[0].strip()
    if _fuzzy_name_match(name_l, title_core):
        # Prefer corporate / life-science pages over awards/people
        bad = ("medal", "prize", "award", "list of", "disambiguation")
        if any(b in title_l for b in bad) and "compan" not in snip_l and "pharma" not in snip_l:
            return False
        return True
    tokens = _name_tokens(name)
    if not tokens:
        return False
    title_tokens = set(re.findall(r"[a-z0-9]+", title_l))
    if not tokens.intersection(title_tokens):
        if not re.search(rf"\b{re.escape(name_l)}\b", f"{title_l} {snip_l}"):
            return False
    corp = (
        "company", "inc", "ltd", "corporation", "co.", "株式会社", "medical",
        "diagnostic", "device", "healthcare", "pharma", "pharmaceutical",
        "biotech", "biopharma", "ag ", " se",
    )
    if any(c in snip_l or c in title_l for c in corp):
        return True
    compact_name = re.sub(r"[^a-z0-9]", "", name_l)
    compact_title = re.sub(r"[^a-z0-9]", "", title_core)
    return compact_title.startswith(compact_name) or compact_name == compact_title


def _wiki_summary(title: str) -> dict[str, str] | None:
    page = urllib.parse.quote(title.replace(" ", "_"))
    summary = _http_json(
        f"https://en.wikipedia.org/api/rest_v1/page/summary/{page}",
        timeout=8,
    )
    if not isinstance(summary, dict):
        return None
    extract = str(summary.get("extract") or "").strip()
    if not extract:
        return None
    return {
        "title": str(summary.get("title") or title),
        "url": str((summary.get("content_urls") or {}).get("desktop", {}).get("page")
                   or f"https://en.wikipedia.org/wiki/{page}"),
        "snippet": extract[:900],
    }


def _wikipedia_official_website(title: str) -> str | None:
    """Best-effort official site from Wikipedia external links."""
    data = _http_json(
        "https://en.wikipedia.org/w/api.php?action=query&prop=extlinks"
        f"&titles={urllib.parse.quote(title)}&ellimit=30&format=json",
        timeout=6,
    )
    if not isinstance(data, dict):
        return None
    pages = (data.get("query") or {}).get("pages") or {}
    skip = (
        "wikipedia.org", "wikimedia.org", "wikidata.org", "archive.org",
        "facebook.com", "twitter.com", "x.com", "linkedin.com", "youtube.com",
        "instagram.com", "doi.org", "pubmed", "ncbi.nlm.nih.gov",
    )
    name_token = re.sub(r"[^a-z0-9]", "", title.lower())[:10]
    best: tuple[int, str] | None = None
    for page in pages.values():
        for row in page.get("extlinks") or []:
            url = str(row.get("*") or row.get("url") or "")
            if not url.startswith("http"):
                continue
            host = urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")
            if any(s in host for s in skip):
                continue
            score = 1
            if name_token and name_token in re.sub(r"[^a-z0-9]", "", host):
                score += 5
            if host.endswith((".com", ".ch", ".com.cn", ".de", ".jp")):
                score += 2
            if best is None or score > best[0]:
                best = (score, url.split("?")[0].rstrip("/"))
    return best[1] if best else None


def resolve_company_name(name: str) -> tuple[str, list[str]]:
    """Resolve typos / aliases to a searchable company name."""
    notes: list[str] = []
    raw = (name or "").strip()
    if not raw:
        return raw, notes
    key = re.sub(r"\s+", " ", raw.lower())
    key_compact = re.sub(r"[^a-z0-9]", "", key)
    if key in _NAME_ALIASES:
        notes.append(f"Corrected '{raw}' → '{_NAME_ALIASES[key]}' (alias).")
        return _NAME_ALIASES[key], notes
    if key_compact in _NAME_ALIASES:
        notes.append(f"Corrected '{raw}' → '{_NAME_ALIASES[key_compact]}' (alias).")
        return _NAME_ALIASES[key_compact], notes

    # Wikipedia opensearch suggestions (handles norvatis → Novartis)
    data = _http_json(
        "https://en.wikipedia.org/w/api.php?action=opensearch"
        f"&search={urllib.parse.quote(raw)}&limit=8&namespace=0&format=json",
        timeout=8,
    )
    if isinstance(data, list) and len(data) >= 2:
        for title in data[1]:
            core = str(title).split("(")[0].strip()
            if _fuzzy_name_match(raw, core) and "medal" not in core.lower() and "prize" not in core.lower():
                if core.lower() != raw.lower():
                    notes.append(f"Corrected '{raw}' → '{core}' (Wikipedia suggest).")
                return core, notes
    return raw, notes


def _wikipedia_search(name: str) -> list[dict[str, str]]:
    # Direct page hit (resolved aliases like Novartis) — skip slow search loops
    direct = _wiki_summary(name)
    if direct and _looks_like_company_hit(name, direct["title"], direct["snippet"]):
        return [direct]

    queries = [
        f"{name} pharmaceutical company",
        f"{name} company",
        name,
    ]
    # Full-text search finds the company page better than opensearch alone
    for raw_q in queries:
        data = _http_json(
            "https://en.wikipedia.org/w/api.php?action=query&list=search"
            f"&srsearch={urllib.parse.quote(raw_q)}&srlimit=5&format=json",
            timeout=8,
        )
        if not isinstance(data, dict):
            continue
        for row in (data.get("query") or {}).get("search") or []:
            title = str(row.get("title") or "")
            snippet = re.sub(r"<[^>]+>", "", str(row.get("snippet") or ""))
            if not _looks_like_company_hit(name, title, snippet):
                continue
            hit = _wiki_summary(title)
            if hit and _looks_like_company_hit(name, hit["title"], hit["snippet"]):
                return [hit]

    # Opensearch fallback (also recovers typo suggestions)
    data = _http_json(
        "https://en.wikipedia.org/w/api.php?action=opensearch"
        f"&search={urllib.parse.quote(name)}&limit=8&namespace=0&format=json",
        timeout=8,
    )
    if isinstance(data, list) and len(data) >= 4:
        for title, desc, url in zip(data[1], data[2], data[3]):
            if not _looks_like_company_hit(name, title, str(desc or "")):
                continue
            hit = _wiki_summary(title)
            if hit:
                return [hit]
            return [{"title": title, "url": url, "snippet": str(desc or "")[:900]}]
    return []


def _duckduckgo_html_search(name: str) -> list[dict[str, str]]:
    """Scrape DuckDuckGo HTML results for company snippets (no API key)."""
    q = urllib.parse.quote_plus(f"{name} company medical diagnostics")
    html = _http_text(f"https://html.duckduckgo.com/html/?q={q}", timeout=12)
    if not html:
        return []
    hits: list[dict[str, str]] = []
    # result blocks: <a class="result__a" href="...">title</a> ... <a class="result__snippet">
    for m in re.finditer(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</(?:a|td)',
        html,
        flags=re.I | re.S,
    ):
        url = urllib.parse.unquote(m.group(1))
        # DDG wraps redirects: //duckduckgo.com/l/?uddg=<url>
        uddg = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("uddg")
        if uddg:
            url = urllib.parse.unquote(uddg[0])
        title = re.sub(r"<[^>]+>", "", m.group(2))
        title = re.sub(r"\s+", " ", title).strip()
        snippet = re.sub(r"<[^>]+>", "", m.group(3))
        snippet = re.sub(r"\s+", " ", snippet).strip()
        if not snippet:
            continue
        if not _looks_like_company_hit(name, title, snippet):
            # Still keep if company name appears in title or snippet
            if name.lower() not in f"{title} {snippet}".lower():
                continue
        hits.append({"title": title[:120], "url": url, "snippet": snippet[:500]})
        if len(hits) >= 5:
            break
    return hits


def _duckduckgo_search(name: str) -> list[dict[str, str]]:
    """DuckDuckGo Instant Answer + HTML results (no API key)."""
    q = urllib.parse.quote(f"{name} Inc company medical diagnostics Japan")
    data = _http_json(
        f"https://api.duckduckgo.com/?q={q}&format=json&no_html=1&skip_disambig=1",
        timeout=10,
    )
    hits: list[dict[str, str]] = []
    if isinstance(data, dict):
        abstract = str(data.get("AbstractText") or "").strip()
        abs_url = str(data.get("AbstractURL") or "").strip()
        heading = str(data.get("Heading") or name).strip()
        if abstract and _looks_like_company_hit(name, heading, abstract):
            hits.append({"title": heading, "url": abs_url, "snippet": abstract[:900]})
        for topic in (data.get("RelatedTopics") or [])[:8]:
            if not isinstance(topic, dict) or "Topics" in topic:
                continue
            text = str(topic.get("Text") or "").strip()
            url = str((topic.get("FirstURL") or "")).strip()
            title = text.split(" - ")[0][:80]
            if text and _looks_like_company_hit(name, title, text):
                hits.append({"title": title, "url": url, "snippet": text[:500]})
    if len(hits) < 2:
        hits.extend(_duckduckgo_html_search(name))
    return hits


def _build_context(name: str, hits: list[dict[str, str]], *, website: str | None = None) -> str:
    parts = [f"Company name: {name}"]
    if website:
        parts.append(f"Website: {website}")
    for i, hit in enumerate(hits[:6], 1):
        title = hit.get("title") or ""
        snippet = hit.get("snippet") or ""
        url = hit.get("url") or ""
        if not (title or snippet):
            continue
        parts.append(f"[{i}] {title}\n{snippet}\nSource: {url}".strip())
    return "\n\n".join(parts).strip()


_KEYWORD_HINTS = [
    "diabetes", "glucose", "cgm", "hba1c", "urinalysis", "urine", "biosensor",
    "diagnostic", "diagnostics", "medtech", "medical device", "in vitro",
    "immunoassay", "point of care", "blood glucose", "insulin", "metabolic",
    "clinical chemistry", "veterinary", "oral care", "laboratory",
    "pharmaceutical", "pharma", "biotech", "biopharma", "oncology", "vaccine",
    "immunology", "cardiology", "drug development", "clinical trial",
]


def _keywords_from_context(context: str, limit: int = 16) -> list[str]:
    low = context.lower()
    found: list[str] = []
    for term in _KEYWORD_HINTS:
        if term in low:
            found.append(term)
    return found[:limit]


def enrich_company_from_web(
    company_name: str,
    *,
    website: str | None = None,
    use_llm: bool = True,
    summarize: bool | None = None,
    force: bool = False,
) -> WebEnrichment:
    """Search the web by company name and return context + summary + keywords.

    ``force=True`` runs even when ``WEB_ENRICH`` is off — used for name-only
    seeds so a short company name can still build an LLM context window.

    ``summarize=False`` skips the LLM rewrite of search hits (snippet summary
    only). Prefer this when the medical-profile LLM will run next — avoids a
    double local-model round-trip (~15–30s saved on Ollama).
    """
    from concurrent.futures import ThreadPoolExecutor

    if summarize is None:
        summarize = use_llm

    seed = (company_name or "").strip()
    result = WebEnrichment(company_name=seed or "Unknown")
    if not seed or seed.lower() in {"unknown", "unknown company"}:
        result.warnings.append("Web enrich skipped: no company name.")
        return result
    # Opt-in by default (offline). Name-only / thin seeds pass force=True.
    if (
        not force
        and os.getenv("WEB_ENRICH", "0").strip().lower() not in {"1", "true", "on", "yes"}
    ):
        result.method = "disabled"
        return result

    name, resolve_notes = resolve_company_name(seed)
    result.resolved_name = name
    result.warnings.extend(resolve_notes)

    hits: list[dict[str, str]] = []
    method_bits: list[str] = []

    # Fast path: Wikipedia company page is enough for most known brands.
    # Avoid waiting on DuckDuckGo/Moonshot (often 5–12s) when wiki already hit.
    wiki = _wikipedia_search(name)
    official_site: str | None = None
    if wiki:
        hits.extend(wiki)
        method_bits.append("wikipedia")
        official_site = _wikipedia_official_website(wiki[0].get("title") or name)
        if official_site:
            hits.append({
                "title": f"{name} official site",
                "url": official_site,
                "snippet": f"Official website: {official_site}",
            })
    else:
        query = f"{name} pharmaceutical biotech medical device company"
        with ThreadPoolExecutor(max_workers=3) as pool:
            from . import budget as _b  # threads must inherit the request's time budget

            fut_moon = pool.submit(_b.wrap(_moonshot_web_search), query, limit=5)
            fut_ddg = pool.submit(_b.wrap(_duckduckgo_search), name)
            fut_ddg_seed = (
                pool.submit(_b.wrap(_duckduckgo_html_search), seed)
                if name.lower() != seed.lower()
                else None
            )
            moon = fut_moon.result() or []
            ddg = fut_ddg.result() or []
            if fut_ddg_seed is not None:
                ddg = ddg + (fut_ddg_seed.result() or [])
        if moon:
            hits.extend(moon)
            method_bits.append("moonshot-search")
        if ddg:
            hits.extend(ddg)
            method_bits.append("duckduckgo")

    # de-dupe by URL/title
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for hit in hits:
        key = (hit.get("url") or hit.get("title") or "").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(hit)
    hits = unique

    # Last resort: ask the local LLM what it knows about this company name
    if not hits and use_llm and kimi_configured():
        from .llm_client import chat

        content, label, lw = chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You identify life-science / pharma / medtech companies from a "
                        "possibly misspelled name. If you recognize the company, write 3–5 "
                        "factual English sentences (what they do, HQ country, main therapies "
                        "or products). If the name is unknown, reply with exactly UNKNOWN. "
                        "Plain text only."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Company name seed: {seed}\nResolved guess: {name}",
                },
            ],
            max_tokens=220,
            json_mode=False,
            timeout=60,
        )
        result.warnings.extend(lw)
        if content and "UNKNOWN" not in content.upper()[:40] and len(content.strip()) > 60:
            hits = [{
                "title": name,
                "url": "",
                "snippet": content.strip()[:900],
            }]
            method_bits.append(f"llm-knowledge:{label}")

    if not hits:
        result.warnings.append(
            f"Web enrich found no public results for '{seed}'"
            + (f" (tried '{name}')" if name != seed else "")
            + "."
        )
        result.method = "none"
        return result

    context = _build_context(name, hits, website=website)
    if seed.lower() != name.lower():
        context = f"User typed: {seed}\nCanonical name: {name}\n\n{context}"
    result.context = context
    result.company_name = name  # surface corrected name to callers
    result.sources = [h.get("url") or "" for h in hits if h.get("url")]
    if official_site and official_site not in result.sources:
        result.sources.insert(0, official_site)
    elif official_site:
        # Prefer official site first for website picker
        result.sources = [official_site] + [s for s in result.sources if s != official_site]
    result.keywords = _keywords_from_context(context)

    summary = None
    if summarize and kimi_configured():
        summary, llm_warn = summarize_company_text(
            context,
            source_type="web_search",
            source_ref=website or name,
            name_hint=name,
            keywords=result.keywords,
        )
        if summary:
            method_bits.append(summary_model_label())
        else:
            for w in llm_warn:
                if "billing" not in w.lower() and "credit" not in w.lower():
                    result.warnings.append(w)

    if not summary:
        snippets = sorted(
            (h.get("snippet") or "" for h in hits),
            key=len,
            reverse=True,
        )
        for snip in snippets:
            clean = re.sub(r"\s+", " ", snip).strip()
            clean = re.sub(r"^[^\w]+", "", clean)
            if len(clean) >= 60:
                summary = clean[:700]
                break
        if summary:
            method_bits.append("snippet")

    result.summary = summary
    result.method = "+".join(method_bits) if method_bits else "none"
    return result
