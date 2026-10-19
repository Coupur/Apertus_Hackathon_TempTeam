"""CLI, run from src/ (or with PYTHONPATH=src):

  python -m navigator --help            (with PYTHONPATH=src)
  python -m navigator crawl [--only artorg dcberne] [--max-pages 40]  clean pages
  python -m navigator crawl-raw [--only artorg dcberne]               archive raw HTML
  python -m navigator pages                 raw HTML -> data/pages.jsonl
  python -m navigator cards                 net records + pages -> data/index/to_embed.jsonl
  python -m navigator embed                 to_embed.jsonl -> data/index/ (only new lines)
  python -m navigator ask "who works on organ-on-chip models?"
  python -m navigator bench --label NAME    score retrieval against bench/gold.jsonl -> bench/report.html
  python -m navigator retrieve "clinical validation of glucose sensors"   (or a queries/company .json)
  python -m navigator enrich
  python -m navigator sources                       list the configured websites
  python -m navigator enrich [--limit 20]           Apertus extraction -> data/entities.jsonl
  python -m navigator index                         person + unit profiles -> data/profiles.jsonl, vectors.npy
  python -m navigator search "we need a partner to validate a glucose sensor"
  python -m navigator search-legacy "clinical validation of glucose sensors"
  python -m navigator cluster                 focused finding themes via Apertus
  python -m navigator net run               targeted crawl with live console (net status in a 2nd terminal)
  python -m navigator company "Ypsomed" https://www.lindt-spruengli.com "startup that ..."   -> queries.json
  python -m navigator company-report company.json --out data/company-report.json
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

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
    c = sub.add_parser("crawl", help="crawl websites directly into data/pages.jsonl")
    c.add_argument("--only", nargs="*", help="source ids, e.g. artorg dcberne inf")
    c.add_argument("--max-pages", type=int, default=config.MAX_PAGES_PER_SOURCE)
    c.add_argument("--concurrency", type=int, default=config.CRAWL_CONCURRENCY)
    c.add_argument("--delay", type=float, default=config.CRAWL_DELAY_S)
    raw = sub.add_parser("crawl-raw", help="archive raw HTML under data/raw/ for offline page extraction")
    raw.add_argument("--only", nargs="*", help="source ids, e.g. artorg dcberne inf")
    raw.add_argument("--max-pages", type=int, default=config.MAX_PAGES_PER_SOURCE)
    raw.add_argument("--concurrency", type=int, default=config.CRAWL_CONCURRENCY)
    raw.add_argument("--delay", type=float, default=config.CRAWL_DELAY_S)
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
    e = sub.add_parser("enrich", help="Apertus extraction -> data/entities.jsonl (resumable)")
    e.add_argument("--workers", type=int, default=8)
    e.add_argument("--limit", type=int, default=None, help="at most this many pages (for a test run)")
    e.add_argument("--only", nargs="*", help="source ids")
    sub.add_parser("pages", help="raw HTML -> data/pages.jsonl (incremental)")
    em = sub.add_parser("embed", help="pages.jsonl -> data/index/ chunk vectors (only new chunks)")
    em.add_argument("--batch-size", type=int, default=64)
    r = sub.add_parser("retrieve", help="queries.json | company.json | text -> chunks above a similarity threshold")
    r.add_argument("query", nargs="+", help="a .json file or one or more query strings")
    r.add_argument("--threshold", type=float, default=None)
    r.add_argument("--top-k", type=int, default=None, help="max chunks per query")
    r.add_argument("--out", help="write matches.json here instead of printing a summary")
    sub.add_parser("cards", help="net records + pages.jsonl -> data/index/to_embed.jsonl (then run embed)")
    a = sub.add_parser("ask", help="query -> ranked people, units and pages with evidence")
    a.add_argument("query")
    a.add_argument("--k", type=int, default=5)
    a.add_argument("--json", action="store_true", help="print the full result as JSON")
    bn = sub.add_parser("bench", help="score retrieval against bench/gold.jsonl; writes bench/runs/ + report.html")
    bn.add_argument("--label", default=None, help="run name, e.g. cards-rollup (default: timestamp)")
    bn.add_argument("--gold", default=None, help="gold file (default bench/gold.jsonl)")
    bn.add_argument("--report-only", action="store_true", help="rebuild bench/report.html from saved runs")
    for prs in (a, bn):
        prs.add_argument("--kinds", nargs="+", default=["person", "unit", "page"], help="index lines to search")
        prs.add_argument("--no-rollup", action="store_true", help="don't credit page hits to people and units")
        prs.add_argument("--no-head-credit", action="store_true", help="don't pass team scores up to the named head")
        prs.add_argument("--lead-boost", type=float, default=None)
        prs.add_argument("--floor", type=float, default=None)
    sub.add_parser("index", help="profiles + embeddings -> data/profiles.jsonl, data/vectors.npy")
    cluster = sub.add_parser("cluster", help="group focused research findings into Apertus-generated themes")
    cluster.add_argument("--db", type=Path, default=config.DATA_DIR / "focused.sqlite")
    cluster.add_argument("--batch-size", type=int, default=50, help="findings per Apertus request (1-80)")
    cluster.add_argument("--json", action="store_true", help="print the full cluster result as JSON")
    s = sub.add_parser("search", help="run a company request")
    s.add_argument("need")
    s.add_argument("--keywords", nargs="*", default=[])
    s.add_argument("--n", type=int, default=5)
    legacy_search = sub.add_parser("search-legacy", help="BM25 search over the legacy page corpus")
    legacy_search.add_argument("need")
    legacy_search.add_argument("--keywords", nargs="*", default=[])
    legacy_search.add_argument("--n", type=int, default=5)
    n = sub.add_parser("net", help="targeted crawl of UniBE, ARTORG and DCB: seed | run | status | export")
    nsub = n.add_subparsers(dest="net_cmd", required=True)
    ns = nsub.add_parser("seed", help="import the old crawl and fill the queue (run does this automatically)")
    ns.add_argument("--workers", type=int, default=None)
    nr = nsub.add_parser("run", help="crawl until every site's queue is empty (resumable)")
    nr.add_argument("--hours", type=float, default=14)
    nr.add_argument("--rps", type=float, default=None, help="requests/s for all *.unibe.ch sites together (default 3)")
    nr.add_argument("--delay", type=float, default=config.CRAWL_DELAY_S, help="seconds between requests to one site")
    nr.add_argument("--inflight", type=int, default=12, help="sites fetched at the same time")
    nr.add_argument("--verbose", action="store_true", help="print every request")
    nst = nsub.add_parser("status", help="progress summary; safe to run while `net run` is crawling")
    nst.add_argument("--top", type=int, default=15)
    nsub.add_parser("export", help="records -> data/net/export/<type>.jsonl")
    co = sub.add_parser("company", help="company name | url | idea -> profile, needs and retrieval queries")
    co.add_argument("inputs", nargs="+", help='e.g. "Ypsomed", https://www.ypsomed.com or "startup that ..."')
    co.add_argument("--as", dest="kind", choices=["auto", "name", "url", "idea"], default="auto")
    co.add_argument("--max-pages", type=int, default=8, help="company pages to read")
    co.add_argument("--max-needs", type=int, default=8, help="needs Apertus may pick (rules ignore this)")
    co.add_argument("--out", help="output folder (default data/companies/<slug>/); only with one input")
    co.add_argument("--retrieve", action="store_true", help="also run the queries on the index: best chunks per "
                                                             "question, saved as matches.json")
    args = ap.parse_args()

    if args.cmd == "company-report":
        dispatch_report(args, ap)
        return

    if args.cmd == "cluster":
        import httpx
        import sqlite3
        from .clusters import cluster_findings
        from .llm import LLMUnavailable

        try:
            result = cluster_findings(args.db, args.batch_size)
        except (ValueError, OSError, sqlite3.Error, LLMUnavailable, httpx.HTTPError) as error:
            ap.error(str(error))
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(f"Clustered {result['finding_count']} findings into {result['theme_count']} themes")
            print(f"Model: {result['model']}  Generated: {result['generated_at']}")
            for theme in result["clusters"]:
                print(f"\n{theme['name']} ({theme['finding_count']})")
                print(f"  {theme['description']}")
        return

    if args.cmd in ("focused-crawl", "highlights", "refresh-keywords", "refresh-evaluations", "keywords"):
        dispatch(args, ap)
        return

    if args.cmd == "company":
        from .company import run, summary, write
        retriever = None
        for inp in args.inputs:
            res = run(inp, args.kind, args.max_pages, args.max_needs)
            out = write(res, args.out if len(args.inputs) == 1 else None)
            print(summary(res))
            print(f"\n  {len(res['queries']['queries'])} queries -> {out / 'queries.json'}  (readable: {out / 'report.md'})")
            if args.retrieve:
                from .answers import CANDIDATES_PER_QUERY, format_by_need, group_by_need
                from .retrieve import Retriever
                retriever = retriever or Retriever()  # load the index once for all companies
                m = retriever.retrieve(res["queries"], threshold=0.0, top_k=CANDIDATES_PER_QUERY)
                m["by_need"] = group_by_need(res["queries"], m)
                (out / "matches.json").write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
                print(f"\n=== Bern pages that answer each question ({out / 'matches.json'})")
                print(format_by_need(m["by_need"]))
    elif args.cmd == "net":
        if args.net_cmd == "seed":
            from .net.seed import seed
            seed(args.workers)
        elif args.net_cmd == "run":
            from .net.runner import UNIBE_RPS, run
            sys.exit(run(args.hours, args.rps or UNIBE_RPS, args.delay, args.inflight, args.verbose))
        elif args.net_cmd == "status":
            from .net.report import status
            status(args.top)
        elif args.net_cmd == "export":
            from .net.report import export
            export()
    elif args.cmd == "sources":
        for s in load_sources():
            print(f"{s.id:20} {s.url:45} {s.name}")
    elif args.cmd == "crawl":
        from .crawl import crawl_all
        sources = [s for s in load_sources() if not args.only or s.id in args.only]
        pages = crawl_all(sources, args.max_pages, args.delay, workers=args.concurrency)
        print(f"Saved {pages} pages -> {config.PAGES_FILE}")
    elif args.cmd == "crawl-raw":
        from .crawl_raw import crawl_all
        sources = [s for s in load_sources() if not args.only or s.id in args.only]
        snapshot = asyncio.run(crawl_all(sources, args.max_pages, args.concurrency, args.delay))
        print(f"Saved {snapshot['pages_saved']} raw pages under {config.RAW_DIR}")
    elif args.cmd == "enrich":
        if not config.LLM_ENABLED:
            print("LLM_BASE_URL not set: writing heuristic records only")
        from .enrich import enrich_all
        print(f"Enriched {enrich_all(args.workers, args.limit, args.only)} pages -> {config.ENTITIES_FILE}")
    elif args.cmd == "index":
        from .index import build
        print(json.dumps(build(), indent=2))
    elif args.cmd == "pages":
        from .pages import build_pages
        added, total = build_pages()
        print(f"Added {added} pages, {total} in {config.PAGES_FILE}")
    elif args.cmd == "embed":
        from .embed import build_index
        print(json.dumps(build_index(args.batch_size), indent=2))
    elif args.cmd == "retrieve":
        from .answers import CANDIDATES_PER_QUERY, format_by_need, group_by_need
        from .retrieve import DEFAULT_THRESHOLD, DEFAULT_TOP_K, Retriever, load_queries
        queries = load_queries(args.query)
        company = bool(queries.get("needs"))  # a company queries.json: answer per question, cut dynamically
        threshold = args.threshold if args.threshold is not None else (0.0 if company else DEFAULT_THRESHOLD)
        top_k = args.top_k or (CANDIDATES_PER_QUERY if company else DEFAULT_TOP_K)
        res = Retriever().retrieve(queries, threshold, top_k)
        if company:
            res["by_need"] = group_by_need(queries, res)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(res, f, indent=2, ensure_ascii=False)
            print(f"{len(res['matches'])} matches -> {args.out}")
        elif company:
            print(format_by_need(res["by_need"]))
        else:
            for q in res["queries"]:
                hits = [m for m in res["matches"] if m["qid"] == q["qid"]]
                print(f"\n[{q['qid']}] {q['text']}  ({len(hits)} chunks >= {res['threshold']})")
                for m in hits[:10]:
                    snippet = m["text"].split("\n", 1)[-1][:110].replace("\n", " ")
                    print(f"  {m['score']:.3f}  {m['source_id'][:14]:14}  {m['url']}\n         {snippet}")
    elif args.cmd == "cards":
        from .cards import build_cards
        print(json.dumps(build_cards(), indent=2))
    elif args.cmd in ("ask", "bench") and not getattr(args, "report_only", False):
        from .rank import RankConfig
        cfg = RankConfig(kinds=tuple(args.kinds), rollup=not args.no_rollup, head_credit=not args.no_head_credit)
        if args.lead_boost is not None:
            cfg.lead_boost = args.lead_boost
        if args.floor is not None:
            cfg.floor = args.floor
        if args.cmd == "ask":
            from .rank import Ranker
            res = Ranker(cfg).ask(args.query, k=args.k)
            if args.json:
                print(json.dumps(res, indent=2, ensure_ascii=False))
            else:
                print_answer(res)
        else:
            from datetime import datetime
            from .bench import GOLD_FILE, print_summary, run_bench
            label = args.label or datetime.now().strftime("run-%m%d-%H%M")
            print_summary(run_bench(label, cfg, Path(args.gold) if args.gold else GOLD_FILE))
    elif args.cmd == "bench":
        from .bench import REPORT_FILE, write_report
        write_report()
        print(f"Report: {REPORT_FILE}")
    elif args.cmd == "search":
        from .models import CompanyRequest
        from .search import search
        res = search(CompanyRequest(need=args.need, keywords=args.keywords, max_results=args.n))
        print(json.dumps(res.model_dump(), indent=2, ensure_ascii=False))
    elif args.cmd == "search-legacy":
        from .models import CompanyRequest
        from .legacy_search import search
        res = search(CompanyRequest(need=args.need, keywords=args.keywords, max_results=args.n))
        print(json.dumps(res.model_dump(), indent=2, ensure_ascii=False))


def print_answer(res: dict):
    flag = "  NO RELIABLE MATCH" if res["no_reliable_match"] else ""
    print(f"\n{res['query']}\nbest score {res['best_score']:.3f}{flag}   ({res['latency_s']}s)")
    for title, rows in (("People", res["people"]), ("Units", res["units"]), ("Pages", res["pages"])):
        if not rows:
            continue
        print(f"\n{title}")
        for r in rows:
            mark = " " if r["confident"] else "?"
            line = f" {mark}{r['score']:.3f}  {r['name']}"
            if r["kind"] == "person":
                role = " · ".join(x for x in [r.get("role"), r.get("group")] if x)
                line += f"  ({role})" if role else ""
                line += "  [lead]" if r.get("lead") else ""
                line += f"\n          {r.get('email') or ''}  {r['url']}"
                if r["via"].get("url"):
                    line += f"\n          via {r['via']['how']}: {r['via']['url']}"
            elif r["kind"] == "unit":
                line += f"  {r['url']}" + (f"\n          via {r['via']['url']}" if r["via"].get("url") else "")
            else:
                line += f"\n          {r['url']}\n          {r['snippet'][:140]}"
            print(line)


if __name__ == "__main__":
    main()
