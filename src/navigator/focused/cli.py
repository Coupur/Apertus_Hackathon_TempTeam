"""English CLI for focused collection and read-only highlights export."""
import asyncio
import json
import sys
import time
from pathlib import Path

from .. import config
from .models import GROUPS, Settings
from .keywords import KEYWORD_VOCABULARY_VERSION, keyword_vocabulary


def add_commands(sub):
    vocabulary = sub.add_parser("keywords", help="list the fixed project keyword vocabulary; no database required")
    vocabulary.add_argument("--json", action="store_true", help="print the versioned vocabulary for UI consumers")
    crawl = sub.add_parser("focused-crawl", help="collect research candidates using local rules; no model required")
    crawl.add_argument("--db", type=Path, default=config.DATA_DIR / "focused.sqlite")
    crawl.add_argument("--only", nargs="+", help="inventory source IDs, such as artorg dcberne")
    crawl.add_argument("--max-fetches", type=int, default=2000, help="content requests, including redirect hops")
    crawl.add_argument("--max-findings", type=int, default=700, help="retained findings, between 1 and 700; use 500 for a smaller inventory")
    crawl.add_argument("--concurrency", type=int, default=4)
    crawl.add_argument("--delay", type=float, default=1.0, help="minimum seconds between requests to a domain")
    crawl.add_argument("--max-depth", type=int, default=8)
    crawl.add_argument("--source-check", action="store_true", help="check source homepages without selecting candidates")
    crawl.add_argument("--reevaluate", action="store_true", help="evaluate unchanged content again")
    crawl.add_argument("--complete", action="store_true",
                       help="traverse all eligible reachable pages; no fetch, depth or frontier ceiling; resume saved work")
    crawl.add_argument("--report", type=Path, help="also save the JSON run report to this file")
    crawl.add_argument("--export", type=Path, help="update a JSON shortlist alongside live reports and on completion")
    show = sub.add_parser("highlights", help="inspect the focused database or export English JSON records")
    show.add_argument("--db", type=Path, default=config.DATA_DIR / "focused.sqlite")
    show.add_argument("--organization", choices=GROUPS)
    show.add_argument("--limit", type=int, default=700)
    show.add_argument("--min-score", type=int, choices=(2, 3, 4), default=2,
                      help="minimum priority score: 2 substantive, 3 stronger evidence")
    show.add_argument("--json", action="store_true", help="print the export contract as JSON")
    show.add_argument("--explain", action="store_true", help="show criterion scores and supporting assertions")
    show.add_argument("--out", type=Path, help="write the JSON export to a file")
    show.add_argument("--keyword", action="append", default=[],
                      help="filter by an English/German subject term; repeat to require all terms")
    refresh = sub.add_parser("refresh-keywords", help="update subject keywords from stored evidence; no network")
    refresh.add_argument("--db", type=Path, default=config.DATA_DIR / "focused.sqlite")
    evaluation = sub.add_parser("refresh-evaluations", help="recompute evidence criteria in stored records; no network")
    evaluation.add_argument("--db", type=Path, default=config.DATA_DIR / "focused.sqlite")
    evaluation.add_argument("--source-snapshot", type=Path,
                            help="restore own entity assertions from a dated source JSONL before rescoring")


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def dispatch(args, parser):
    try:
        if args.cmd == "keywords":
            vocabulary = keyword_vocabulary()
            if args.json:
                print(json.dumps(vocabulary, indent=2, ensure_ascii=False))
            else:
                print(f"{vocabulary['count']} fixed project keywords ({vocabulary['version']})")
                for category, labels in vocabulary["groups"].items():
                    print(f"\n{category}:")
                    for label in labels:
                        print("  " + label)
            return
        paths = [p for key in ("out", "report", "export") if (p := getattr(args, key, None))]
        if any(p.resolve() == args.db.resolve() for p in paths):
            raise ValueError("The output file must not overwrite the focused database")
        if len({p.resolve() for p in paths}) != len(paths):
            raise ValueError("Report and export files must have different paths")
        if args.cmd == "refresh-keywords":
            from .store import refresh_keywords
            print(json.dumps(refresh_keywords(args.db)))
            return
        if args.cmd == "refresh-evaluations":
            from .store import refresh_evaluations
            print(json.dumps(refresh_evaluations(args.db, args.source_snapshot)))
            return
        if args.cmd == "highlights":
            from .keywords import matches_keyword
            from .store import read_highlights
            from .ranking import evaluation_for, ranking_summary
            if args.limit < 1:
                raise ValueError("limit must be positive")
            findings, report = read_highlights(args.db)
            for record in findings:
                record["evaluation"] = evaluation_for(record)
            findings = [r for r in findings if r["type"] in ("expert", "team") or max(r["scores"].values()) >= getattr(args, "min_score", 2)]
            if args.organization:
                findings = [r for r in findings if args.organization in r["organizations"]]
            for keyword in getattr(args, "keyword", []):
                if not keyword.strip():
                    raise ValueError("keyword must not be empty")
                findings = [r for r in findings if matches_keyword(r, keyword)]
            payload = {"schema_version": 3, "language": "en", "count": min(len(findings), args.limit),
                       "keyword_vocabulary_version": KEYWORD_VOCABULARY_VERSION,
                       "findings": findings[:args.limit], "last_run": report,
                       "exhaustive": False}
            payload["ranking"] = ranking_summary(findings[:args.limit])
            if args.out:
                write_json(args.out, payload)
                print(f"Exported {payload['count']} findings to {args.out}")
            elif args.json:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                print(f"{payload['count']} research candidates (rule-selected; not an exhaustive research inventory)")
                for record in payload["findings"]:
                    print(f"\n[{max(record['scores'].values())}/4] {record['title']} ({record['status']})")
                    print("Organizations: " + ", ".join(record["organizations"]))
                    print("Review status: " + record.get("review_status", "unknown"))
                    print(f"Evidence score: {record['evaluation']['score']:.2f}/100 (heuristic, not a probability)")
                    if getattr(args, "explain", False):
                        for name, detail in record["evaluation"]["criteria"].items():
                            print(f"  {name}: {detail['score']}/4 — {detail['reason']}")
                            if detail["quote"]:
                                print("    " + detail["quote"])
                    print("Original source name: " + record["original_name"])
                    print("Keywords: " + ", ".join(record.get("keywords", [])))
                    print(record["summary"])
                    print("Why selected: " + record["rationale"])
                    for url in record["source_urls"]:
                        print("Source: " + url)
            return
        from .crawl import run_crawl
        settings = Settings(max_fetches=args.max_fetches,
                            max_findings=args.max_findings, concurrency=args.concurrency, delay=args.delay,
                            max_depth=args.max_depth, source_check=args.source_check, reevaluate=args.reevaluate,
                            complete=getattr(args, "complete", False))
        last_progress = [0.0]

        def progress(message):
            if time.monotonic() - last_progress[0] >= 10:
                print(message, file=sys.stderr, flush=True)
                last_progress[0] = time.monotonic()

        def checkpoint(report):
            if args.report:
                write_json(args.report, report)
            if getattr(args, "export", None):
                from .store import read_highlights
                from .ranking import ranking_summary
                findings, _ = read_highlights(args.db)
                write_json(args.export, {"schema_version": 3, "language": "en", "count": len(findings),
                                         "keyword_vocabulary_version": KEYWORD_VOCABULARY_VERSION,
                                         "findings": findings, "last_run": report, "exhaustive": False,
                                         "ranking": ranking_summary(findings)})

        report = asyncio.run(run_crawl(args.db, settings, args.only, progress, checkpoint))
        checkpoint(report)
        print(json.dumps(report, indent=2, ensure_ascii=False))
    except (ValueError, OSError) as error:
        parser.error(str(error))
