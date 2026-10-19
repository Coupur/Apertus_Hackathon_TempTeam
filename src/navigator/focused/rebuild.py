"""Re-read permitted sources into a separate unified SQLite database.

A freshly captured, dated JSONL source snapshot may be supplied for reproducible
evaluation. Legacy records are used only to discover URLs, never as new evidence.
"""
import argparse
import asyncio
import hashlib
import json
from collections import Counter
from pathlib import Path

import httpx

from .. import config
from .cli import write_json
from .crawl import Crawler, focused_sources, now
from .models import Document, Settings
from .privacy import clean_text
from .ranking import ranking_summary
from .store import Store, read_highlights
from .web import Boundary, Fetcher, FetchError, host


async def rebuild(from_db: Path, target: Path, limit=700, snapshot: Path | None=None) -> dict:
    if from_db.resolve() == target.resolve() or target.exists():
        raise ValueError("Rebuild needs a new database path, different from the original")
    if not from_db.exists():
        raise FileNotFoundError(from_db)
    target.parent.mkdir(parents=True,exist_ok=True)
    staging = target.with_suffix(target.suffix + ".building")
    if staging.exists():
        raise ValueError(f"A staged rebuild already exists: {staging}")
    sources = focused_sources()
    by_host = {s.host:s for s in sources}
    boundary = Boundary([s.url for s in sources])
    settings = Settings(max_findings=limit, concurrency=8, max_fetches=4000, reevaluate=True)
    store = Store(staging,limit,defer_trim=True)
    crawler = Crawler(sources,store,settings)
    failures=[]
    snapshot_sha256=None
    try:
        if snapshot:
            snapshot_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest()
            with snapshot.open(encoding="utf-8") as stream:
                for index,line in enumerate(stream,1):
                    raw=json.loads(line)
                    if not boundary.allows(raw["url"]) or not boundary.allows(raw.get("retrieval_url") or raw["url"]):
                        raise ValueError("Snapshot contains a source outside the permitted boundary")
                    source=by_host[host(raw["url"])]
                    doc=Document(**{**raw,"text":clean_text(raw["text"]),"source_id":source.id,"organization":source.institution})
                    await crawler.process(doc)
                    if index % 100 == 0:
                        print(f"Re-evaluated {index} source documents",flush=True)
        else:
            records,_=read_highlights(from_db)
            urls=sorted({u for r in records for u in r["source_urls"] if boundary.allows(u)})
            async with httpx.AsyncClient(timeout=30,follow_redirects=False) as client:
                fetcher=Fetcher(client,boundary,settings)
                for start in range(0,len(urls),8):
                    batch=urls[start:start+8]
                    responses=await asyncio.gather(*(fetcher.get(u) for u in batch),return_exceptions=True)
                    for url,response in zip(batch,responses):
                        if isinstance(response,BaseException):
                            failures.append({"url":url,"error":str(response)})
                        elif "html" in response.content_type:
                            await crawler.process(crawler.html_document(response,0))
        all_records=store.findings()
        store.defer_trim=False
        with store.db: store._trim()
        findings=store.findings()
        report={"mode":"unified_rebuild","started_at":crawler.report["started_at"],"finished_at":now(),
                "source_database":str(from_db.resolve()),"source_snapshot_sha256":snapshot_sha256,
                "documents_considered":crawler.report["documents_considered"],
                "accepted_unique_before_limit":len(all_records),"retained_findings":len(findings),
                "counts_by_type":dict(Counter(r["type"] for r in findings)),
                "rejection_reasons":dict(crawler.rejections),"selection_errors":dict(crawler.errors),
                "fetch_failures":failures,"limits":{"findings":limit},"exhaustive":False,
                "ranking":ranking_summary(findings)}
        store.finish(report,10000)
    finally:
        store.close()
    staging.replace(target)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--from-db",type=Path,default=config.DATA_DIR/"focused.sqlite")
    p.add_argument("--db",type=Path,required=True)
    p.add_argument("--max-findings",type=int,default=700)
    p.add_argument("--source-snapshot",type=Path)
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args()
    protected={x.resolve() for x in (a.from_db,a.db,a.source_snapshot) if x}
    if a.report.resolve() in protected: p.error("Report path must not overwrite an input or database")
    try: report=asyncio.run(rebuild(a.from_db,a.db,a.max_findings,a.source_snapshot))
    except (ValueError,OSError) as e: p.error(str(e))
    write_json(a.report,report)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == "__main__": main()
