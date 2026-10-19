"""`navigator net seed`: start the net from what we already have.

1. Register every configured source (inventory xlsx, sources_discovered.json, sources.json).
2. Mark every page the old crawler saved as fetched, so nothing is downloaded twice.
3. Read those pages in parallel: store their people and units, and queue their useful links.
4. Queue each source's homepage and seed paths.
Runs once; `net run` calls it automatically on a fresh database.
"""
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .. import config
from ..sources import load_sources
from .page import decode, process
from .scope import KIND_PRIORITY, in_scope
from .state import NEW_UNIT_BONUS, State, now_iso


def _read(job):
    path, url, _sid, _depth = job
    try:
        return process(decode(Path(path).read_bytes()), url)
    except Exception as e:  # one broken file must not stop the seed
        return {"error": f"{type(e).__name__}: {e}"}


def seed(workers: int | None = None) -> State:
    st = State()
    if st.get_meta("seeded"):
        print(f"Already seeded on {st.get_meta('seeded')} ({len(st.queued):,} URLs queued).")
        return st
    t0 = time.time()
    configured = [s for s in load_sources() if in_scope(s.host)]
    for s in configured:
        st.add_source(s.id, s.host, s.name, s.url, s.institution)
    print(f"Sources: {len(configured)} configured")

    jobs = []
    for manifest in sorted(config.RAW_DIR.glob("*/manifest.jsonl")):
        sid = manifest.parent.name
        if sid not in st.sources:
            continue
        n = 0
        for line in open(manifest, encoding="utf-8"):
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            if m.get("status") != 200 or not m.get("file"):
                continue
            final = m.get("final_url") or m["url"]
            for u in {m["url"], final}:
                st.add_fetched(u, sid, m.get("depth", 0))
            jobs.append((str(manifest.parent / m["file"]), final, sid, m.get("depth", 0)))
            n += 1
        st.update_source(sid, fetched=n)
    st.commit(force=True)
    print(f"Old crawl: {len(jobs):,} saved pages marked as fetched; reading them now "
          f"with {workers or os.cpu_count()} processes ...")

    errors = 0
    with ProcessPoolExecutor(workers) as ex:
        for i, (job, res) in enumerate(zip(jobs, ex.map(_read, jobs, chunksize=32)), 1):
            _path, url, sid, depth = job
            if "error" in res:
                errors += 1
            else:
                st.mark(url, "fetched", page_type=res["page_type"], relevance=res["relevance"])
                if res["kept"]:
                    st.bump(sid, "kept")
                st.store_records(res, url, sid)
                st.expand(url, depth, res)
            if i % 2000 == 0 or i == len(jobs):
                st.commit(force=True)
                print(f"  {i:>6,}/{len(jobs):,} pages | people {st.counts['person']:,} | units {st.counts['unit']:,}"
                      f" | queued {len(st.queued):,} | sites {len(st.sources)} | {time.time() - t0:.0f}s", flush=True)

    seeds = {s.id: s.seeds() for s in configured}
    for sid, s in st.sources.items():
        for url in seeds.get(sid, [s["url"]]):
            url = st.canonical(url, sid)
            if url not in st.fetched:
                st.enqueue(url, sid, "home", KIND_PRIORITY["home"] + NEW_UNIT_BONUS, 0, "", "", "seed")
    st.set_meta("seeded", now_iso())
    st.commit(force=True)
    for e in st.events:
        print("  " + e)
    st.events.clear()
    print(f"Seed done in {time.time() - t0:.0f}s: {len(st.sources)} sites, {len(st.queued):,} URLs queued, "
          f"{st.counts['person']:,} people, {st.counts['unit']:,} units, {errors} unreadable pages")
    return st
