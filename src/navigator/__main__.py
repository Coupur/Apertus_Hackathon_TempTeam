"""CLI.  From the repo root:

  python -m navigator --help            (with PYTHONPATH=src)
  python -m navigator crawl [--only artorg dcberne] [--max-pages 40]
  python -m navigator pages                 raw HTML -> data/pages.jsonl
  python -m navigator embed                 pages.jsonl -> data/index/ (only new chunks)
  python -m navigator retrieve "clinical validation of glucose sensors"   (or a queries/company .json)
  python -m navigator enrich
  python -m navigator search "we need a partner to validate a glucose sensor"
  python -m navigator company-report company.json --out data/company-report.json
"""
import argparse
import asyncio
import json
import sys

from . import config
from .sources import load_sources


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # page text has umlauts, Greek letters, etc.
    ap = argparse.ArgumentParser(prog="navigator")
    sub = ap.add_subparsers(dest="cmd", required=True)
    from .focused.cli import add_commands, dispatch
    add_commands(sub)
    from .focused.company_report import add_command, dispatch as dispatch_report
    add_command(sub)
    c = sub.add_parser("crawl", help="crawl sources into data/raw/; run pages to produce pages.jsonl")
    c.add_argument("--only", nargs="*", help="source ids, e.g. artorg dcberne inf")
    c.add_argument("--max-pages", type=int, default=config.MAX_PAGES_PER_SOURCE)
    c.add_argument("--concurrency", type=int, default=config.CRAWL_CONCURRENCY)
    c.add_argument("--delay", type=float, default=config.CRAWL_DELAY_S)
    sub.add_parser("sources", help="list configured sources")
    d = sub.add_parser("discover", help="add *.unibe.ch subdomains linked from crawled pages as sources")
    d.add_argument("--min-links", type=int, default=5)
    p = sub.add_parser("pdfs", help="download PDFs listed in data/raw/<source>/pdf_links.jsonl")
    p.add_argument("--only", nargs="*", help="source ids")
    p.add_argument("--max-per-site", type=int, default=300)
    p.add_argument("--concurrency", type=int, default=config.CRAWL_CONCURRENCY)
    p.add_argument("--delay", type=float, default=config.CRAWL_DELAY_S)
    b = sub.add_parser("boris", help="harvest BORIS publication metadata (OAI-PMH) into data/raw/boris/")
    b.add_argument("--max-requests", type=int, default=None)
    b.add_argument("--from-date", help="only records changed since YYYY-MM-DD")
    sub.add_parser("dcberne-api", help="dump the Diabetes Center Berne WordPress API into data/raw/dcberne_api/")
    e = sub.add_parser("enrich", help="step 2b: Apertus extracts structured records")
    e.add_argument("--workers", type=int, default=4)
    sub.add_parser("pages", help="raw HTML -> data/pages.jsonl (incremental)")
    em = sub.add_parser("embed", help="pages.jsonl -> data/index/ chunk vectors (only new chunks)")
    em.add_argument("--batch-size", type=int, default=64)
    r = sub.add_parser("retrieve", help="queries.json | company.json | text -> chunks above a similarity threshold")
    r.add_argument("query", nargs="+", help="a .json file or one or more query strings")
    r.add_argument("--threshold", type=float, default=None)
    r.add_argument("--top-k", type=int, default=None, help="max chunks per query")
    r.add_argument("--out", help="write matches.json here instead of printing a summary")
    s = sub.add_parser("search", help="steps 1+3: run a company request")
    s.add_argument("need")
    s.add_argument("--keywords", nargs="*", default=[])
    s.add_argument("--n", type=int, default=5)
    args = ap.parse_args()

    if args.cmd == "company-report":
        dispatch_report(args, ap)
        return

    if args.cmd in ("focused-crawl", "highlights", "refresh-keywords", "refresh-evaluations", "keywords"):
        dispatch(args, ap)
        return

    if args.cmd == "sources":
        for s in load_sources():
            print(f"{s.id:20} {s.url:45} {s.name}")
    elif args.cmd == "crawl":
        sources = load_sources()
        if args.only:
            sources = [s for s in sources if s.id in args.only]
        from .crawl import crawl_all
        print(f"Crawling {len(sources)} sources, max {args.max_pages} pages each, "
              f"{args.concurrency} sites in parallel, {args.delay}s between requests per site")
        snap = asyncio.run(crawl_all(sources, args.max_pages, args.concurrency, args.delay))
        print(f"Saved {snap['pages_saved']} raw pages under {config.RAW_DIR}")
    elif args.cmd == "discover":
        from .discover import discover
        found = discover(args.min_links)
        print(f"{len(found)} new sources -> {config.DISCOVERED_SOURCES}")
    elif args.cmd == "pdfs":
        from .pdfs import download_all
        st = asyncio.run(download_all(args.only, args.max_per_site, args.concurrency, args.delay))
        print(f"Saved {st['saved']} PDFs ({st['mb']:.0f} MB) from {st['sites']} sites, {st['errors']} errors")
    elif args.cmd == "boris":
        from .boris import harvest
        st = harvest(args.max_requests, args.from_date)
        print(f"BORIS: {st['records']}/{st['total']} records in {config.RAW_DIR / 'boris'}")
    elif args.cmd == "dcberne-api":
        from .dcb_api import dump
        print(json.dumps(dump(), indent=1))
    elif args.cmd == "enrich":
        from .enrich import enrich_all
        if not config.LLM_ENABLED:
            print("LLM_BASE_URL not set: writing heuristic records only")
        print(f"Wrote {enrich_all(args.workers)} records to {config.ENTITIES_FILE}")
    elif args.cmd == "pages":
        from .pages import build_pages
        added, total = build_pages()
        print(f"Added {added} pages, {total} in {config.PAGES_FILE}")
    elif args.cmd == "embed":
        from .embed import build_index
        print(json.dumps(build_index(args.batch_size), indent=2))
    elif args.cmd == "retrieve":
        from .retrieve import DEFAULT_THRESHOLD, DEFAULT_TOP_K, Retriever, load_queries
        res = Retriever().retrieve(load_queries(args.query),
                                   args.threshold if args.threshold is not None else DEFAULT_THRESHOLD,
                                   args.top_k or DEFAULT_TOP_K)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(res, f, indent=2, ensure_ascii=False)
            print(f"{len(res['matches'])} matches -> {args.out}")
        else:
            for q in res["queries"]:
                hits = [m for m in res["matches"] if m["qid"] == q["qid"]]
                print(f"\n[{q['qid']}] {q['text']}  ({len(hits)} chunks >= {res['threshold']})")
                for m in hits[:10]:
                    snippet = m["text"].split("\n", 1)[-1][:110].replace("\n", " ")
                    print(f"  {m['score']:.3f}  {m['source_id'][:14]:14}  {m['url']}\n         {snippet}")
    elif args.cmd == "search":
        from .models import CompanyRequest
        from .search import search
        res = search(CompanyRequest(need=args.need, keywords=args.keywords, max_results=args.n))
        print(json.dumps(res.model_dump(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
