"""CLI, run from src/ (or with PYTHONPATH=src):

  python -m navigator sources                       list the configured websites
  python -m navigator crawl [--only artorg dcberne] websites -> data/pages.jsonl
  python -m navigator enrich [--limit 20]           Apertus extraction -> data/entities.jsonl
  python -m navigator index                         person + unit profiles -> data/profiles.jsonl, vectors.npy
  python -m navigator search "we need a partner to validate a glucose sensor"
"""
import argparse
import json
import sys

from . import config
from .sources import load_sources


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # page text has umlauts, Greek letters, etc.
    ap = argparse.ArgumentParser(prog="navigator")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sources", help="list configured websites")
    c = sub.add_parser("crawl", help="websites -> data/pages.jsonl (skips sites already crawled)")
    c.add_argument("--only", nargs="*", help="source ids, e.g. artorg dcberne inf")
    c.add_argument("--max-pages", type=int, default=config.MAX_PAGES_PER_SOURCE)
    c.add_argument("--delay", type=float, default=config.CRAWL_DELAY_S, help="seconds between requests per site")
    e = sub.add_parser("enrich", help="Apertus extraction -> data/entities.jsonl (resumable)")
    e.add_argument("--workers", type=int, default=8)
    e.add_argument("--limit", type=int, default=None, help="at most this many pages (for a test run)")
    e.add_argument("--only", nargs="*", help="source ids")
    sub.add_parser("index", help="profiles + embeddings -> data/profiles.jsonl, data/vectors.npy")
    s = sub.add_parser("search", help="run a company request")
    s.add_argument("need")
    s.add_argument("--keywords", nargs="*", default=[])
    s.add_argument("--n", type=int, default=5)
    args = ap.parse_args()

    if args.cmd == "sources":
        for src in load_sources():
            print(f"{src.id:20} {src.url:45} {src.name}")
    elif args.cmd == "crawl":
        from .crawl import crawl_all
        sources = [s for s in load_sources() if not args.only or s.id in args.only]
        print(f"Saved {crawl_all(sources, args.max_pages, args.delay)} pages -> {config.PAGES_FILE}")
    elif args.cmd == "enrich":
        if not config.LLM_ENABLED:
            sys.exit("Set LLM_BASE_URL, LLM_NAME and LLM_API_KEY (e.g. in src/.env) first")
        from .enrich import enrich_all
        print(f"Enriched {enrich_all(args.workers, args.limit, args.only)} pages -> {config.ENTITIES_FILE}")
    elif args.cmd == "index":
        from .index import build
        print(json.dumps(build(), indent=2))
    elif args.cmd == "search":
        from .models import CompanyRequest
        from .search import search
        res = search(CompanyRequest(need=args.need, keywords=args.keywords, max_results=args.n))
        print(json.dumps(res.model_dump(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
