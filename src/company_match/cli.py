#!/usr/bin/env python3
"""CLI for the Bern company matching layer.

Examples:
  python -m company_match init
  python -m company_match search --query "cgm diabetes"
  python -m company_match match --id ypsomed
  python -m company_match ingest --text "Company Name: Acme\\nCGM sensors..."
  python -m company_match ingest path/to/pitch.pdf https://example.com/about notes.txt
  python -m company_match ingest --file samples/two_companies.txt --save
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow `python -m company_match.cli` from repo root or src/
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from company_match.database import init_db, seed_from_json
from company_match.engine import CompanyMatchEngine
from company_match.handoff import export_handoff_from_sources, write_handoff
from company_match.ingest import ingest_and_match, preview_source


def _print_result(result, verbose: bool = True) -> None:
    print(f"\n{'=' * 60}")
    print(f"Company:     {result.company_name}")
    if result.company_id:
        print(f"ID:          {result.company_id}")
    print(f"Domain:      {result.domain_label} ({'in scope' if result.in_scope else 'OUT OF SCOPE'})")
    print(f"Priority:    {result.priority_rating} | stage={result.priority_stage} | score={result.priority_score}")
    print(f"Match rate:  {result.match_rate}%")
    print(f"Tier:        {result.tier}")
    if result.teammate_queries_early:
        print(f"Run first:   {', '.join(result.teammate_queries_early)}")
    if result.teammate_queries_later:
        print(f"Run later:   {', '.join(result.teammate_queries_later[:8])}")
    if result.handoff_note:
        print(f"Handoff:     {result.handoff_note}")
    print("\nMatch reasons:")
    for i, reason in enumerate(result.reasons, 1):
        print(f"  {i}. {reason}")
    if result.bern_units:
        print("\nBern units / groups:")
        for u in result.bern_units:
            print(f"  - {u}")
    if result.economic_hooks:
        print("\nEconomic development hooks:")
        for h in result.economic_hooks:
            print(f"  - {h}")
    if result.suggested_queries:
        print("\nSuggested navigator queries:")
        for q in result.suggested_queries:
            print(f"  - {q}")
    if verbose and result.capability_matches:
        print("\nCapability scores:")
        for c in result.capability_matches:
            print(f"  - {c.capability_name}: {c.score} ({', '.join(c.overlap_terms[:4])})")
    print("=" * 60)


def _print_ingest(batch, verbose: bool = True) -> None:
    print(f"\nIngested {batch.company_count} compan(y/ies) from {batch.source_count} source(s)")
    print("Prioritized for teammate navigator matching (early keywords first)\n")

    queue = batch.teammate_queue()
    if queue:
        print("=== Teammate queue (run in this order) ===")
        for row in queue:
            print(
                f"  #{row['queue_position']} [{row['priority_rating']}/{row['priority_stage']}] "
                f"{row['company_name']}  match={row['match_rate']}%  prio={row['priority_score']}"
            )
            if row.get("run_first"):
                print(f"       EARLY:  {', '.join(row['run_first'][:6])}")
            if row.get("run_later"):
                print(f"       LATER:  {', '.join(row['run_later'][:6])}")
        print()

    for item in batch.prioritized_items():
        ext = item.extraction
        pos = item.queue_position or "?"
        print(f"--- Queue #{pos} ---")
        print(f"Source:      {ext.source_type} :: {ext.source_ref}")
        print(f"Extracted:   {ext.company.get('name')} (confidence {ext.confidence}, method={ext.method})")
        in_scope = item.match.in_scope if item.match else ext.company.get("in_scope", True)
        print(f"Domain:      Life Science ({'in scope' if in_scope else 'OUT OF SCOPE'})")
        if item.match:
            print(
                f"Priority:    {item.match.priority_rating} | stage={item.match.priority_stage} | "
                f"score={item.match.priority_score}"
            )
            if item.match.early_keywords:
                print(f"Early KW:    {', '.join(item.match.early_keywords[:8])}")
            if item.match.teammate_queries_later:
                print(f"Later KW:    {', '.join(item.match.teammate_queries_later[:6])}")
        if ext.company.get("sector"):
            print(f"Sector:      {ext.company.get('sector')} / {ext.company.get('subsector') or '-'}")
        if ext.warnings:
            print(f"Warnings:    {'; '.join(ext.warnings)}")
        if item.errors:
            print(f"Errors:      {'; '.join(item.errors)}")
        if item.match:
            print(f"Match rate:  {item.match.match_rate}% | {item.match.tier}")
            if item.match.handoff_note:
                print(f"Handoff:     {item.match.handoff_note}")
            if verbose:
                for reason in item.match.reasons[:4]:
                    print(f"  · {reason}")
        print()


def cmd_init(_: argparse.Namespace) -> int:
    conn = init_db(seed=True)
    counts = seed_from_json(conn)
    conn.close()
    print(f"Database ready. Seeded {counts['companies']} companies, {counts['capabilities']} capabilities.")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    engine = CompanyMatchEngine()
    results = engine.search_companies(
        query=args.query or "",
        min_match_rate=args.min_rate,
        sector=args.sector,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        print(f"Found {len(results)} companies")
        for r in results:
            print(f"  {r.match_rate:5.1f}%  [{r.tier.split('—')[0].strip()}]  {r.company_name}")
            if args.verbose:
                for reason in r.reasons[:2]:
                    print(f"           · {reason}")
    engine.close()
    return 0


def cmd_match(args: argparse.Namespace) -> int:
    engine = CompanyMatchEngine()
    if args.id:
        result = engine.match_by_id(args.id)
        if not result:
            print(f"Company not found: {args.id}", file=sys.stderr)
            engine.close()
            return 1
    else:
        payload = {
            "name": args.name,
            "sector": args.sector,
            "subsector": args.subsector,
            "description": args.description,
            "keywords": args.keywords,
            "needs": args.needs,
            "hq_country": args.country,
            "hq_city": args.city,
            "canton_bern_presence": args.in_bern,
            "website": args.website,
        }
        if args.file:
            # Prefer full ingest for non-JSON files
            path = Path(args.file)
            if path.suffix.lower() == ".json":
                payload.update(json.loads(path.read_text(encoding="utf-8")))
                result = engine.match_payload(payload, persist_company=args.save)
            else:
                batch = ingest_and_match(
                    [path], engine=engine, save=args.save, use_llm=args.llm
                )
                if args.json:
                    print(json.dumps(batch.to_dict(), indent=2))
                else:
                    _print_ingest(batch, verbose=True)
                engine.close()
                return 0
        else:
            result = engine.match_payload(payload, persist_company=args.save)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        _print_result(result, verbose=True)
    engine.close()
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    texts: list[str] = []
    if args.text:
        texts.append(args.text)
    if args.stdin:
        texts.append(sys.stdin.read())

    sources: list[str | Path] = list(args.sources or [])
    if args.file:
        sources.append(args.file)

    batch = ingest_and_match(
        sources,
        text="\n\n---\n\n".join(texts) if texts else None,
        save=args.save,
        use_llm=args.llm,
        match=not args.extract_only,
        index_qdrant=getattr(args, "qdrant", False),
    )
    if getattr(args, "handoff", False):
        paths = write_handoff(batch, out_dir=args.out or None)
        print("Handoff written for teammate (no company_match needed on their side):")
        for key in ("json", "md", "readme"):
            print(f"  {key}: {paths[key]}")
    if getattr(args, "qdrant", False) and batch.qdrant_index:
        qi = batch.qdrant_index
        if qi.get("error"):
            print(f"Qdrant index error: {qi['error']}")
        else:
            print(
                f"Qdrant later-stage index: {qi.get('indexed')} points "
                f"(collection={qi.get('collection')}, embedder={qi.get('embedder')})"
            )
    if args.json:
        print(json.dumps(batch.to_dict(), indent=2))
    else:
        _print_ingest(batch, verbose=args.verbose or True)
    return 0


def cmd_qdrant_search(args: argparse.Namespace) -> int:
    from company_match.vectorstore import get_qdrant_store

    store = get_qdrant_store()
    hits = store.search(args.query, limit=args.limit)
    if args.json:
        print(json.dumps({"info": store.info(), "hits": hits}, indent=2))
    else:
        print(f"Qdrant later-stage search ({store.info()})")
        for i, h in enumerate(hits, 1):
            print(
                f"  {i}. {h['company_name']}  score={h['score']}  "
                f"prio={h.get('priority_rating')}  match={h.get('match_rate')}"
            )
            if h.get("run_first"):
                print(f"      run_first: {', '.join(h['run_first'][:5])}")
    return 0


def cmd_qdrant_info(_: argparse.Namespace) -> int:
    from company_match.vectorstore import get_qdrant_store

    print(json.dumps(get_qdrant_store().info(), indent=2))
    return 0


def cmd_handoff(args: argparse.Namespace) -> int:
    """Export JSON/Markdown your teammate can open without this package."""
    result = export_handoff_from_sources(
        args.sources or None,
        text=args.text,
        files=[args.file] if args.file else None,
        out_dir=args.out or None,
        use_llm=args.llm,
    )
    print("Handoff ready — teammate only needs these files:")
    for key, path in result["paths"].items():
        if key in {"json", "md", "readme"}:
            print(f"  {key}: {path}")
    print(f"\nCompanies in queue: {result['payload']['company_count']}")
    for row in result["payload"].get("teammate_queue") or []:
        print(
            f"  #{row['queue_position']} [{row['priority_rating']}] {row['company_name']} "
            f"→ first: {', '.join((row.get('run_first') or [])[:3]) or '-'}"
        )
    return 0


def cmd_preview(args: argparse.Namespace) -> int:
    data = preview_source(args.source)
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(f"Type:  {data['source_type']}")
        print(f"Ref:   {data['source_ref']}")
        print(f"Chars: {data['char_count']}")
        print("\nPreview:\n")
        print(data["text_preview"])
    return 0


def cmd_rank(args: argparse.Namespace) -> int:
    args.query = args.query or ""
    return cmd_search(args)


def cmd_list(args: argparse.Namespace) -> int:
    engine = CompanyMatchEngine()
    companies = engine.list_companies()
    if args.json:
        print(json.dumps(companies, indent=2))
    else:
        for c in companies:
            presence = "BE" if c.get("canton_bern_presence") else "  "
            print(f"[{presence}] {c['id']:22} {c['name']:28} {c.get('sector') or '-'}")
    engine.close()
    return 0


def cmd_bern_records(args: argparse.Namespace) -> int:
    """Validate teammate Bern records and optionally test a query against them."""
    from company_match.bern_records import load_records, match_records

    rs = load_records(args.path)
    print(f"Files: {len(rs.files)}  valid records: {len(rs.records)}  issues: {len(rs.issues)}")
    by_type: dict[str, int] = {}
    for r in rs.records:
        by_type[r["type"]] = by_type.get(r["type"], 0) + 1
    if by_type:
        print("By type: " + ", ".join(f"{k}={v}" for k, v in sorted(by_type.items())))
    for issue in rs.issues[:50]:
        print(f"  ! {Path(issue.file).name}[{issue.index}]: {issue.problem}")
    if args.query:
        terms = [t.strip() for t in args.query.split(",") if t.strip()]
        for hit in match_records(terms, rs.records, limit=args.limit):
            print(f"  {hit['score']:.2f}  {hit['name']} ({hit['type']})  {hit['source_url']}")
            print(f"        {hit['reason']}")
    return 1 if rs.issues and args.strict else 0


def cmd_llm_bench(args: argparse.Namespace) -> int:
    """Time the instant pass and the AI pass on one source (default: a sample pitch)."""
    import time

    from company_match import budget, llm_client
    from company_match.extractors import extract_from_sources

    src = args.source or str(Path(__file__).resolve().parent / "samples" / "single_pitch.txt")
    print("LLM:", llm_client.model_label(), "| warm-up:", llm_client.ensure_ollama_model_ready()
          if llm_client.resolve_provider() == "ollama" else "n/a")
    for mode, secs in (("off", 15), ("lite", 25)):
        t = time.time()
        with budget.budget(secs, llm_mode=mode):
            r = extract_from_sources([src], use_llm=False)[0]
            rep = budget.report()
        c = r.company
        print(f"\n[{mode}] {time.time() - t:.1f}s  steps={rep.get('steps_s')}  method={r.method}")
        print("  what_they_do:", (c.get("what_they_do") or "")[:200])
        print("  summary     :", (c.get("description") or "")[:200])
        for n in rep.get("notes") or []:
            print("  note:", n)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Bern life-science company matching engine")
    sub = p.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="Create/seed SQLite database")
    init_p.set_defaults(func=cmd_init)

    list_p = sub.add_parser("list", help="List companies in the database")
    list_p.add_argument("--json", action="store_true")
    list_p.set_defaults(func=cmd_list)

    search_p = sub.add_parser("search", help="Automatic search / filter companies")
    search_p.add_argument("--query", "-q", default="")
    search_p.add_argument("--sector")
    search_p.add_argument("--min-rate", type=float, default=0.0)
    search_p.add_argument("--limit", type=int, default=20)
    search_p.add_argument("--verbose", "-v", action="store_true")
    search_p.add_argument("--json", action="store_true")
    search_p.set_defaults(func=cmd_search)

    rank_p = sub.add_parser("rank", help="Rank all companies by match rate")
    rank_p.add_argument("--query", "-q", default="")
    rank_p.add_argument("--sector")
    rank_p.add_argument("--min-rate", type=float, default=0.0)
    rank_p.add_argument("--limit", type=int, default=50)
    rank_p.add_argument("--verbose", "-v", action="store_true")
    rank_p.add_argument("--json", action="store_true")
    rank_p.set_defaults(func=cmd_rank)

    match_p = sub.add_parser("match", help="Pass company information and get match rate + reasons")
    match_p.add_argument("--id", help="Match an existing company by id/name")
    match_p.add_argument("--name", help="Company name (for new/adhoc match)")
    match_p.add_argument("--sector")
    match_p.add_argument("--subsector")
    match_p.add_argument("--description")
    match_p.add_argument("--keywords", help="Comma-separated keywords")
    match_p.add_argument("--needs", help="Comma-separated needs")
    match_p.add_argument("--country")
    match_p.add_argument("--city")
    match_p.add_argument("--website")
    match_p.add_argument("--in-bern", action="store_true")
    match_p.add_argument("--file", help="JSON / text / PDF file with company information")
    match_p.add_argument("--save", action="store_true", help="Persist company into DB")
    match_p.add_argument("--llm", action="store_true", help="Optional Apertus enrichment")
    match_p.add_argument("--json", action="store_true")
    match_p.set_defaults(func=cmd_match)

    ingest_p = sub.add_parser(
        "ingest",
        help="Auto-extract from text / PDF / URL (one or many) then match",
    )
    ingest_p.add_argument(
        "sources",
        nargs="*",
        help="Paths, URLs, or omitted when using --text/--file/--stdin",
    )
    ingest_p.add_argument("--text", "-t", help="Inline plain text (single or multi-company)")
    ingest_p.add_argument("--file", "-f", help="Extra file path (txt/md/pdf/json)")
    ingest_p.add_argument("--stdin", action="store_true", help="Read text from stdin")
    ingest_p.add_argument("--save", action="store_true", help="Save extracted companies to DB")
    ingest_p.add_argument("--llm", action="store_true", help="Optional Apertus enrichment")
    ingest_p.add_argument("--extract-only", action="store_true", help="Skip matching")
    ingest_p.add_argument(
        "--handoff",
        action="store_true",
        help="Also write outbox/latest.json + latest.md for teammate",
    )
    ingest_p.add_argument(
        "--qdrant",
        action="store_true",
        help="Index results into Qdrant for later-stage vector matching",
    )
    ingest_p.add_argument("--out", help="Handoff output directory (default: outbox/)")
    ingest_p.add_argument("--verbose", "-v", action="store_true")
    ingest_p.add_argument("--json", action="store_true")
    ingest_p.set_defaults(func=cmd_ingest)

    qs = sub.add_parser("qdrant-search", help="Later-stage semantic search in Qdrant")
    qs.add_argument("query", help="Natural language / keyword query")
    qs.add_argument("--limit", type=int, default=8)
    qs.add_argument("--json", action="store_true")
    qs.set_defaults(func=cmd_qdrant_search)

    qi = sub.add_parser("qdrant-info", help="Show local Qdrant collection info")
    qi.set_defaults(func=cmd_qdrant_info)

    handoff_p = sub.add_parser(
        "handoff",
        help="Export JSON/MD for teammate — they do not need to run company_match",
    )
    handoff_p.add_argument("sources", nargs="*", help="Paths / URLs / omitted with --file/--text")
    handoff_p.add_argument("--text", "-t")
    handoff_p.add_argument("--file", "-f")
    handoff_p.add_argument("--out", help="Output directory (default: src/company_match/outbox)")
    handoff_p.add_argument("--llm", action="store_true")
    handoff_p.set_defaults(func=cmd_handoff)

    lb = sub.add_parser("llm-bench", help="Time instant vs AI pass (target: AI < 10 s)")
    lb.add_argument("source", nargs="?", help="URL / file / text (default: sample pitch)")
    lb.set_defaults(func=cmd_llm_bench)

    br = sub.add_parser(
        "bern-records",
        help="Validate teammate Bern records (data/bern_records/) and test matching",
    )
    br.add_argument("--path", help="File or folder (default: $BERN_RECORDS_PATH or data/bern_records/)")
    br.add_argument("--query", "-q", help="Comma-separated company terms, e.g. 'cgm, wearable'")
    br.add_argument("--limit", type=int, default=8)
    br.add_argument("--strict", action="store_true", help="Exit 1 if any record is invalid (CI)")
    br.set_defaults(func=cmd_bern_records)

    preview_p = sub.add_parser("preview", help="Preview raw text extracted from a source")
    preview_p.add_argument("source", help="Path, URL, or text")
    preview_p.add_argument("--json", action="store_true")
    preview_p.set_defaults(func=cmd_preview)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
