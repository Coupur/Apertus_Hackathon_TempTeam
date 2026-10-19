"""Company JSON -> keyword shortlist -> source text -> source-backed Apertus report."""
import asyncio
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .. import config, llm
from ..extract import extract
from .keywords import KEYWORD_VOCABULARY_VERSION, PATTERNS, matches_keyword, normalize
from .models import Settings
from .ranking import rank, evaluation_for
from .privacy import clean_text, has_contact, public_record
from .store import read_highlights
from .web import Boundary, FetchError, Fetcher, normalize_url


class CompanyBrief(BaseModel):
    # Keep additional company fields as context; only keywords drive retrieval.
    model_config = ConfigDict(extra="allow", strict=True)
    company_name: str = ""
    need: str = ""
    keywords: list[str] = Field(min_length=1, max_length=50)
    requirements: list[str] = Field(default_factory=list, max_length=50)
    goals: list[str] = Field(default_factory=list, max_length=50)
    report_language: str = "English"

    @field_validator("keywords", "requirements", "goals")
    @classmethod
    def clean_items(cls, values):
        if any(not value.strip() or len(value) > 2000 for value in values):
            raise ValueError("List items must be nonempty strings of at most 2000 characters")
        return list(dict.fromkeys(value.strip() for value in values))

    @model_validator(mode="after")
    def has_requirements(self):
        if not (self.need.strip() or self.requirements or self.goals):
            raise ValueError("Provide need, requirements or goals as well as keywords")
        if not self.report_language.strip():
            raise ValueError("report_language must not be empty")
        if len(self.model_dump_json()) > 20000:
            raise ValueError("Company JSON must fit within 20000 characters")
        return self


def canonical_keyword(value: str) -> str:
    normalized = normalize(value)
    if normalized in PATTERNS:
        return normalized
    aliases = [label for label, pattern in PATTERNS.items() if pattern.fullmatch(normalized)]
    # CGM also matches the broad glucose tag; prefer the most specific label.
    return max(aliases, key=lambda label: (len(label.split()), len(label), label)) if aliases else normalized


def shortlist(company: CompanyBrief, findings: list[dict], top_k: int = 5) -> list[dict]:
    if not 1 <= top_k <= 10:
        raise ValueError("top_k must be between 1 and 10")
    keywords = list(dict.fromkeys(canonical_keyword(k) for k in company.keywords))
    matches = []
    for finding in findings:
        matched = [k for k in keywords if matches_keyword(finding, k)]
        if matched:
            matches.append({"finding": finding, "matched_keywords": matched,
                            "unmatched_keywords": [k for k in keywords if k not in matched],
                            "keyword_match_count": len(matched)})
    return sorted(matches, key=lambda m: (m["keyword_match_count"], rank(m["finding"])), reverse=True)[:top_k]


def source_text(text: str, keywords: list[str], limit: int) -> str:
    """Keep keyword-rich windows in source order when a page exceeds the budget."""
    if len(text) <= limit:
        return text
    # Keep source spans on natural boundaries; fixed offsets cut words and can
    # detach a name from its role. Adjacent selected spans are joined unchanged.
    spans, start = [], 0
    while start < len(text):
        end = min(start + 1000, len(text))
        if end < len(text):
            boundary = max(text.rfind('\n\n', start + 400, end),
                           text.rfind('\n', start + 400, end),
                           text.rfind('. ', start + 400, end))
            if boundary < start + 400:
                boundary = text.rfind(' ', start + 1, end)
            if boundary > start:
                end = boundary + (1 if text[boundary] == '.' else 0)
        spans.append((start,end))
        start = end
    parts = [text[start:end] for start,end in spans]

    def score(part):
        normalized = normalize(part)
        return sum(bool(PATTERNS[k].search(normalized)) if k in PATTERNS else
                   bool(re.search(r"(?<!\w)" + re.escape(k) + r"(?!\w)", normalized)) for k in keywords)

    chosen, used = [], 0
    for i in sorted(range(len(parts)), key=lambda i: (-score(parts[i]), i)):
        cost = len(parts[i]) + 5
        if used + cost <= limit:
            chosen.append(i)
            used += cost
    groups = []
    for i in sorted(chosen):
        start,end = spans[i]
        if groups and groups[-1][1] == start:
            groups[-1] = (groups[-1][0],end)
        else:
            groups.append((start,end))
    return "\n...\n".join(text[start:end] for start,end in groups)


def evidence_urls(finding: dict) -> list[str]:
    """Prefer the finding's own detail pages over multi-article catalogues."""
    urls = list(dict.fromkeys(normalize_url(u) for u in finding.get('source_urls', []) if normalize_url(u)))
    if finding.get('type') in ('expert','team'):
        work_urls = [l['source_url'] for l in finding.get('related_works', [])]
        profile = [finding['identity_url']] if finding.get('identity_url') else []
        return list(dict.fromkeys(urls[:1] + work_urls[:1] + profile + urls[1:]))
    def tokens(value):
        plain = unicodedata.normalize('NFKD', unquote(value)).encode('ascii','ignore').decode().lower()
        return set(re.findall(r'[a-z]{4,}',plain)) - {'research','project','study','diabetes','center','berne','university'}
    name = tokens(finding['original_name'])
    def overlap(url):
        return len(name & tokens(urlsplit(url).path))
    details = [u for u in urls if not re.search(r'/(?:category|project_category|tag|page)/|/20\d\d/\d\d(?:/|$)',urlsplit(u).path)]
    if details:
        strongest = max(map(overlap,details))
        # Do not follow another work's detail URL merely because it was merged
        # into a broad legacy catalogue observation.
        if strongest:
            details = [u for u in details if overlap(u) >= max(1,strongest/2)]
        return sorted(details,key=lambda u:(-overlap(u),urls.index(u)))
    return urls


async def prepare_context(company: CompanyBrief, matches: list[dict], fetcher: Fetcher,
                          max_chars: int = 6000) -> dict:
    if not 1500 <= max_chars <= 6000:
        raise ValueError("max_chars must be between 1500 and 6000")
    keywords = list(dict.fromkeys(canonical_keyword(k) for k in company.keywords))
    keywords += [normalize(m["finding"]["original_name"]) for m in matches]
    planned = [[u for u in evidence_urls(m['finding']) if fetcher.boundary.allows(u)][:3] for m in matches]
    per_page = min(max_chars, 60000 // max(1, len({u for urls in planned for u in urls})))
    candidates, sources, by_url = [], [], {}
    for match, urls in zip(matches, planned):
        finding = match["finding"]
        ids = []
        for url in urls:
            if url not in by_url:
                source = {"id": f"S{len(sources) + 1}", "url": url, "retrieval_url": url,
                          "title": finding["original_name"], "status": "unavailable", "text": "",
                          "fetched_at": None, "truncated": False}
                try:
                    response = await fetcher.get(url)
                    if "html" in response.content_type or not response.content_type:
                        parsed = extract(response.text, response.url, paragraphs=True)
                    elif response.content_type == "text/plain":
                        parsed = {"title": source["title"], "text": response.text}
                    else:
                        raise FetchError("unsupported_content_type")
                    if len(parsed["text"].strip()) < 80:
                        raise FetchError("insufficient_page_text")
                    parsed["text"] = clean_text(parsed["text"])
                    source.update(status="fetched", retrieval_url=response.url, title=clean_text(parsed["title"]),
                                  text=source_text(parsed["text"], keywords, per_page),
                                  fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                  truncated=len(parsed["text"]) > per_page)
                except FetchError as error:
                    # Only retained evidence for this exact source may be used as fallback.
                    evidence = [e for m in matches for e in (m["finding"].get("evidence", []) +
                                [l for l in m["finding"].get("related_works", [])])
                                if normalize_url(e.get("source_url", "")) == url]
                    text = clean_text("\n".join(dict.fromkeys(e["quote"] for e in evidence)))
                    source.update(error=str(error), text=source_text(text, keywords, per_page),
                                  status="stored_excerpt" if text else "unavailable",
                                  truncated=len(text) > per_page,
                                  evidence_dates=sorted({e["fetched_at"] for e in evidence if e.get("fetched_at")}))
                by_url[url] = source
                sources.append(source)
            ids.append(by_url[url]["id"])
        candidates.append({"id": finding["id"], "name": finding["original_name"],
                           "organizations": finding.get("organizations", []), "type": finding["type"],
                           "unit": finding.get("unit", ""), "keywords": finding.get("keywords", []),
                           "review_status": finding.get("review_status", "unreviewed"),
                           "matched_keywords": match["matched_keywords"],
                           "unmatched_keywords": match["unmatched_keywords"],
                           "keyword_match_count": match["keyword_match_count"], "source_ids": ids})
        candidates[-1].update(selection_score=rank(finding)[0],
                              selection_version=finding.get("selection_version", "legacy-evidence-v1"),
                              evaluation=finding.get("evaluation") or evaluation_for(finding),
                              experts=public_record(finding.get("experts", [])),
                              teams=public_record(finding.get("teams", [])),
                              related_works=public_record([{k:l[k] for k in ("work_id","work_name","role","source_url","quote")}
                                                          for l in finding.get("related_works", [])[:3]]))
    limitations = ["The shortlist covers the collected Bern inventory, not every option in the canton.",
                   "Keyword overlap indicates topical similarity, not confirmed suitability or availability.",
                   "At most three source URLs per candidate are read; keyword/name windows share a 60000-character budget.",
                   "A separate Apertus entailment check filters claims; it does not guarantee their truth."]
    for source in sources:
        if source["status"] == "stored_excerpt":
            dates = ", ".join(source["evidence_dates"]) or "unknown date"
            limitations.append(f"{source['id']} could not be refreshed; only retained excerpts from {dates} were available.")
        elif source["status"] == "unavailable":
            limitations.append(f"{source['id']} was unavailable and has no retained text to assess.")
    return {"schema_version": 2, "status": "prepared", "company": company.model_dump(),
            "keyword_vocabulary_version": KEYWORD_VOCABULARY_VERSION,
            "normalized_keywords": [canonical_keyword(k) for k in company.keywords], "selection_method": "keyword_overlap_then_selection_score",
            "candidates": candidates, "sources": sources, "limitations": limitations}


from .report_contract import generate_report, render_markdown


def add_command(sub):
    command = sub.add_parser("company-report", help="company JSON -> focused keyword matches -> source text -> Apertus report")
    command.add_argument("company", type=Path)
    command.add_argument("--db", type=Path, default=config.DATA_DIR / "focused.sqlite")
    command.add_argument("--top-k", type=int, default=5, help="shortlisted findings, 1–10")
    command.add_argument("--source-chars", type=int, default=6000, help="text budget per source, 1500–6000 characters")
    command.add_argument("--out", type=Path, required=True, help="JSON output, including source text and provenance")
    command.add_argument("--markdown-out", type=Path, help="also write the completed report as Markdown")
    command.add_argument("--prepare-only", action="store_true", help="select candidates and read sources without calling Apertus")


def dispatch(args, parser):
    from .cli import write_json
    from .crawl import focused_sources

    try:
        outputs = [args.out] + ([args.markdown_out] if args.markdown_out else [])
        protected = {args.company.resolve(), args.db.resolve()}
        if any(p.resolve() in protected for p in outputs) or len({p.resolve() for p in outputs}) != len(outputs):
            raise ValueError("Output paths must be distinct and must not overwrite the company JSON or database")
        if args.out.suffix.lower() != ".json" or (args.markdown_out and args.markdown_out.suffix.lower() != ".md"):
            raise ValueError("Use .json for --out and .md for --markdown-out")
        if args.prepare_only and args.markdown_out:
            raise ValueError("--markdown-out requires report generation; omit --prepare-only")
        company_input = json.loads(args.company.read_text(encoding="utf-8-sig"))
        company = CompanyBrief.model_validate(company_input)
        findings, _ = read_highlights(args.db)
        matches = shortlist(company, findings, args.top_k)
        if matches and not args.prepare_only and not config.LLM_ENABLED:
            raise llm.LLMUnavailable("Set LLM_BASE_URL for Apertus, or use --prepare-only to inspect selected source material")

        async def prepare():
            boundary = Boundary([s.url for s in focused_sources()])
            async with httpx.AsyncClient(timeout=30) as client:
                fetcher = Fetcher(client, boundary, Settings(max_fetches=120))
                return await prepare_context(company, matches, fetcher, args.source_chars)

        context = asyncio.run(prepare())
        context["company_input"] = company_input
        write_json(args.out, context)
        if args.prepare_only:
            print(f"Prepared {len(matches)} keyword matches and {len(context['sources'])} sources -> {args.out}")
            return
        # Preserve the prepared context if the model is unavailable or returns invalid citations.
        result = generate_report(context)
        write_json(args.out, result)
        if args.markdown_out:
            args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
            args.markdown_out.write_text(render_markdown(result), encoding="utf-8")
        print(f"{result['status']}: {len(result['report']['recommendations'])} recommendations -> {args.out}")
    except (ValueError, OSError, llm.LLMUnavailable, httpx.HTTPError) as error:
        parser.error(str(error))
