"""CLI.  From the repo root:

  python -m navigator --help            (with PYTHONPATH=src)
  python -m navigator crawl [--only artorg dcberne] [--max-pages 40]
  python -m navigator enrich
  python -m navigator search "we need a partner to validate a glucose sensor"
"""
import argparse
import asyncio
import json

from . import config
from .sources import load_sources


def main():
    ap = argparse.ArgumentParser(prog="navigator")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("crawl", help="step 2a: crawl sources into data/pages.jsonl")
    c.add_argument("--only", nargs="*", help="source ids, e.g. artorg dcberne inf")
    c.add_argument("--max-pages", type=int, default=config.MAX_PAGES_PER_SOURCE)
    c.add_argument("--concurrency", type=int, default=config.CRAWL_CONCURRENCY)
    c.add_argument("--delay", type=float, default=config.CRAWL_DELAY_S)
    sub.add_parser("sources", help="list configured sources")
    e = sub.add_parser("enrich", help="step 2b: Apertus extracts structured records")
    e.add_argument("--workers", type=int, default=4)
    s = sub.add_parser("search", help="steps 1+3: run a company request")
    s.add_argument("need")
    s.add_argument("--keywords", nargs="*", default=[])
    s.add_argument("--n", type=int, default=5)
    args = ap.parse_args()

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
    elif args.cmd == "enrich":
        from .enrich import enrich_all
        if not config.LLM_ENABLED:
            print("LLM_BASE_URL not set: writing heuristic records only")
        print(f"Wrote {enrich_all(args.workers)} records to {config.ENTITIES_FILE}")
    elif args.cmd == "search":
        from .models import CompanyRequest
        from .search import search
        res = search(CompanyRequest(need=args.need, keywords=args.keywords, max_results=args.n))
        print(json.dumps(res.model_dump(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
