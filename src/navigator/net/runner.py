"""`navigator net run`: the crawl loop, with a live console.

Each step picks the best queued URL among sites that are free right now, so the most useful pages
anywhere come first. Politeness: one request per site at a time, DELAY seconds apart, and all
*.unibe.ch sites together under UNIBE_RPS requests/s (they run on one CMS). robots.txt is obeyed.
Every page is read (page.py), its people and unit are stored and its useful links queued (state.py).

Console: a status line every 10 s and a round summary every ROUND_PAGES pages.
Files: raw pages and manifest.jsonl under data/raw/<site>/ (same format as `crawl`, so `pages` and
`embed` keep working), one line per request in data/net/net.log, data/net/progress.json, rounds.jsonl.
Exit codes: 0 = finished or time limit reached, 3 = stopped by the free-disk guard.
"""
import asyncio
import hashlib
import json
import os
import shutil
import time
from collections import Counter, defaultdict
from urllib.parse import urlsplit

import httpx

from .. import config
from ..robots import Robots
from .page import decode, process
from .scope import excluded, host_of, in_scope
from .state import NET_DIR, State, now_iso, source_id_for_host

UNIBE_RPS = float(os.getenv("UNIBE_RPS", "3"))
MIN_FREE_GB = float(os.getenv("MIN_FREE_GB", "15"))
OTHER_CAP = 40          # at most this many 'other' pages per site
ROUND_PAGES, ROUND_SECONDS = 500, 600
MAX_BYTES = 5_000_000
TICK_S = 10
KINDS = ["profile", "people", "home", "infra", "research", "project", "about", "other"]


class Runner:
    def __init__(self, state: State, hours: float, rps: float, delay: float, inflight: int, verbose: bool):
        self.st, self.rps, self.delay, self.inflight, self.verbose = state, rps, delay, inflight, verbose
        self.deadline = time.time() + hours * 3600
        self.t0 = time.time()
        self.busy: set[str] = set()
        self.next_ok = defaultdict(float)     # site -> monotonic time of its next allowed request
        self.group_next = defaultdict(float)  # rate group -> monotonic time of the next allowed request
        self.backoff = defaultdict(lambda: 300.0)
        self.robots: dict[str, Robots] = {}
        self.total = Counter()                # this run
        self.rnd = Counter()                  # this round
        self.rnd_sites = Counter()
        self.round_n, self.round_t0 = 0, time.time()
        self.people_at_tick = state.counts["person"]
        self.stop_reason, self.exit_code = None, 0
        self.manifests = {}
        self.log = open(NET_DIR / "net.log", "a", encoding="utf-8")
        self.free_gb, self._disk_checked = self._free_gb(), 0.0

    # ---------- scheduling ----------
    def _group(self, sid: str) -> str:
        host = self.st.sources[sid]["host"]
        return "unibe" if host == "unibe.ch" or host.endswith(".unibe.ch") else sid

    def _pick(self) -> str | None:
        now = time.monotonic()
        best, best_p = None, None
        for sid, s in self.st.sources.items():
            if s["status"] != "active" or sid in self.busy or self.next_ok[sid] > now:
                continue
            if self.group_next[self._group(sid)] > now:
                continue
            p = self.st.peek(sid)
            if p is None:
                self.st.update_source(sid, status="done", reason="queue empty")
                self.st.events.append(f"[site done] {sid}: queue empty after {s['fetched']} pages")
                continue
            if s["fetched"] >= s["budget"]:
                self.st.update_source(sid, status="budget", reason=f"budget {s['budget']} reached")
                self.st.events.append(f"[site done] {sid}: budget of {s['budget']} pages reached")
                continue
            if best_p is None or p > best_p:
                best, best_p = sid, p
        return best

    def _take(self, sid: str) -> str | None:
        """Pop the next URL worth a request; cheap refusals (caps, robots) cost no request."""
        s = self.st.sources[sid]
        while True:
            url = self.st.pop(sid)
            if url is None:
                return None
            if self.st.kind_of.get(url) == "other" and s["other_fetched"] >= OTHER_CAP:
                self.st.mark(url, "skipped", reason="other cap")
                self.total["skipped"] += 1
                continue
            rb = self.robots.get(sid)
            if rb is not None and not rb.can_fetch(url):
                self.st.mark(url, "robots")
                self.total["robots"] += 1
                continue
            return url

    def _any_queued(self) -> bool:
        return any(s["status"] == "active" and self.st.peek(sid) is not None for sid, s in self.st.sources.items())

    # ---------- one request ----------
    async def _load_robots(self, client, sid: str):
        try:
            r = await client.get(f"https://{self.st.netloc[sid]}/robots.txt")
            text = r.text if r.status_code == 200 else ""
        except httpx.HTTPError:
            text = ""
        self.robots[sid] = Robots(text, config.USER_AGENT)
        await asyncio.sleep(self.delay)

    def _manifest(self, sid: str):
        if sid not in self.manifests:
            d = config.RAW_DIR / sid
            (d / "pages").mkdir(parents=True, exist_ok=True)
            self.manifests[sid] = open(d / "manifest.jsonl", "a", encoding="utf-8")
        return self.manifests[sid]

    def _write_manifest(self, sid: str, rec: dict):
        f = self._manifest(sid)
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()

    async def _one(self, client, sid: str, url: str):
        info = self.st.info(url)
        kind = info["kind"] or "other"
        status_note = ""
        try:
            if sid not in self.robots:
                await self._load_robots(client, sid)
            if not self.robots[sid].can_fetch(url):
                self.st.mark(url, "robots")
                self.total["robots"] += 1
                return
            rec = {"url": url, "final_url": None, "status": None, "content_type": None, "file": None,
                   "depth": info["depth"], "bytes": 0, "fetched_at": now_iso(), "kind": kind}
            r = await client.get(url)
            final = str(r.url)
            ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
            rec.update(final_url=final, status=r.status_code, content_type=ctype, bytes=len(r.content))
            self.total["requests"] += 1
            self.rnd["requests"] += 1
            status_note = str(r.status_code)

            if r.status_code in (429, 503):
                gave_up = self.st.db.execute("SELECT 1 FROM url WHERE source_id=? AND status='error' AND http_status "
                                             "IN (429, 503) LIMIT 1", (sid,)).fetchone()
                if info["attempts"] + 1 >= 3 or gave_up:  # always "busy" (e.g. a document system): give up the site
                    self.st.mark(url, "error", http_status=r.status_code, attempts=info["attempts"] + 1)
                    self.total["errors"] += 1
                    self.st.update_source(sid, status="blocked", reason=f"HTTP {r.status_code} after retries")
                    self.st.events.append(f"[site done] {sid}: blocked, keeps answering HTTP {r.status_code}")
                    return
                self.next_ok[sid] = time.monotonic() + self.backoff[sid]
                self.st.events.append(f"[slow down] {sid}: HTTP {r.status_code}, pausing {self.backoff[sid] / 60:.0f} min")
                self.backoff[sid] *= 2
                self.st.requeue(url, sid, info["priority"], info["attempts"] + 1)
                return
            if r.status_code == 404 and info["fallback"]:
                self.st.mark(url, "dead", http_status=404)
                self.st.enqueue(info["fallback"], sid, kind, info["priority"], info["depth"], url, "", "German fallback")
                return
            fhost = host_of(final)
            if r.status_code != 200 or ctype != "text/html" or len(r.content) > MAX_BYTES:
                self.st.mark(url, "dead" if r.status_code >= 400 else "skipped", http_status=r.status_code)
                self._write_manifest(sid, rec)
                self.total["not_html"] += 1
                return
            fsid = self.st.host_to_sid.get(fhost)
            if fsid is None:
                if not in_scope(fhost) or excluded(fhost):
                    self.st.mark(url, "offsite", http_status=200)
                    self.total["offsite"] += 1
                    return
                fsid = self.st.add_source(source_id_for_host(fhost), fhost, fhost, f"https://{urlsplit(final).netloc}/",
                                          added_by="redirect", reason=f"redirect from {url}")
            if final != url and final in self.st.fetched:
                self.st.mark(url, "duplicate", http_status=200)
                self.total["duplicate"] += 1
                return

            name = hashlib.sha1(final.encode()).hexdigest()[:20] + ".html"
            (config.RAW_DIR / fsid / "pages").mkdir(parents=True, exist_ok=True)
            (config.RAW_DIR / fsid / "pages" / name).write_bytes(r.content)
            rec["file"] = f"pages/{name}"
            res = await asyncio.to_thread(process, decode(r.content), final)
            rec.update(page_type=res["page_type"], relevance=res["relevance"])
            self._write_manifest(fsid, rec)

            self.st.mark(url, "fetched", http_status=200, page_type=res["page_type"], relevance=res["relevance"],
                         fetched_at=rec["fetched_at"])
            if final != url:
                self.st.add_fetched(final, fsid, info["depth"])
            self.st.bump(fsid, "fetched")
            if kind == "other":
                self.st.bump(sid, "other_fetched")
            if res["kept"]:
                self.st.bump(fsid, "kept")
            new = self.st.store_records(res, final, fsid)
            self.st.expand(final, info["depth"], res)

            for c in (self.total, self.rnd):
                c["fetched"] += 1
                c["kept"] += res["kept"]
                c["people"] += new["person"]
                c["units"] += new["unit"]
                c["kind_" + kind] += 1
            self.rnd_sites[fsid] += 1
            status_note = f"{res['page_type']} {res['relevance']:.2f}" + (f" +{new['person']} people" if new["person"] else "")
        except httpx.HTTPError as e:
            status_note = f"error {type(e).__name__}"
            self.total["errors"] += 1
            if info["attempts"] + 1 < 3:
                self.st.requeue(url, sid, info["priority"] - 1, info["attempts"] + 1)
            else:
                self.st.mark(url, "error", attempts=info["attempts"] + 1)
        finally:
            self.busy.discard(sid)
            self.next_ok[sid] = max(self.next_ok[sid], time.monotonic() + self.delay)
            self.log.write(f"{now_iso()}\t{sid}\t{kind}\t{status_note}\t{url}\n")
            if self.verbose:
                print(f"    {sid:<16} {kind:<8} {status_note:<34} {url}", flush=True)

    # ---------- console ----------
    def _free_gb(self) -> float:
        return shutil.disk_usage(config.DATA_DIR).free / 1e9

    def _queue_by_kind(self) -> Counter:
        return Counter(self.st.kind_of.get(u, "other") for u in self.st.queued)

    def _line(self) -> str:
        el = time.time() - self.t0
        mins = max(el / 60, 1 / 60)
        q = self._queue_by_kind()
        statuses = Counter(s["status"] for s in self.st.sources.values())
        f = self.total["fetched"]
        kept = f"{100 * self.total['kept'] / f:.0f}%" if f else "-"
        people_now = self.st.counts["person"]
        delta, self.people_at_tick = people_now - self.people_at_tick, people_now
        busy = " ".join(sorted(self.busy)) or "-"
        queue = " ".join(f"{k} {q[k]:,}" for k in KINDS if q[k])
        return (f"[{int(el // 3600):02d}:{int(el % 3600 // 60):02d}:{int(el % 60):02d}] "
                f"fetched {f:,} ({f / mins:.0f}/min) kept {kept} | people {people_now:,} (+{delta}) "
                f"units {self.st.counts['unit']:,} | sites {statuses['active']} active, "
                f"{statuses['done'] + statuses['budget']} done | errors {self.total['errors']} "
                f"robots {self.total['robots']} | {self.free_gb:.0f} GB free\n"
                f"           queue {sum(q.values()):,}: {queue or '-'}\n"
                f"           now: {busy}")

    def _progress(self):
        q = self._queue_by_kind()
        snap = {"updated": now_iso(), "elapsed_s": round(time.time() - self.t0), "run": dict(self.total),
                "records": dict(self.st.counts), "queue": dict(q), "free_gb": round(self.free_gb, 1),
                "sites": dict(Counter(s["status"] for s in self.st.sources.values())), "round": self.round_n}
        (NET_DIR / "progress.json").write_text(json.dumps(snap, indent=1), encoding="utf-8")

    def _round_end(self, final: bool = False):
        if not self.rnd["fetched"] and not final:
            return
        self.round_n += 1
        dur = time.time() - self.round_t0
        f = self.rnd["fetched"]
        kinds = ", ".join(f"{k} {self.rnd['kind_' + k]}" for k in KINDS if self.rnd["kind_" + k])
        top = ", ".join(f"{s} {n}" for s, n in self.rnd_sites.most_common(8))
        summary = {"round": self.round_n, "finished": now_iso(), "seconds": round(dur), "fetched": f,
                   "kept": self.rnd["kept"], "new_people": self.rnd["people"], "new_units": self.rnd["units"],
                   "by_kind": {k: self.rnd["kind_" + k] for k in KINDS}, "top_sites": dict(self.rnd_sites.most_common(10)),
                   "records": dict(self.st.counts), "queued": len(self.st.queued)}
        with open(NET_DIR / "rounds.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(summary) + "\n")
        print(f"\n== round {self.round_n} ({'final' if final else f'{dur / 60:.1f} min'}) "
              f"{f} pages, kept {100 * self.rnd['kept'] / max(f, 1):.0f}% | new: {self.rnd['people']} people, "
              f"{self.rnd['units']} units | totals: {self.st.counts['person']:,} people, "
              f"{self.st.counts['unit']:,} units, {len(self.st.queued):,} queued\n"
              f"   fetched by kind: {kinds or '-'}\n   busiest sites: {top or '-'}\n", flush=True)
        self.rnd.clear()
        self.rnd_sites.clear()
        self.round_t0 = time.time()

    async def _ticker(self):
        while True:
            await asyncio.sleep(TICK_S)
            self.free_gb = self._free_gb()
            for e in self.st.events:
                print("  " + e, flush=True)
            self.st.events.clear()
            print(self._line(), flush=True)
            self._progress()
            if self.rnd["fetched"] >= ROUND_PAGES or time.time() - self.round_t0 >= ROUND_SECONDS:
                self._round_end()

    def _should_stop(self) -> bool:
        if time.time() >= self.deadline:
            self.stop_reason = "time limit reached"
            return True
        if self.free_gb < MIN_FREE_GB:
            self.stop_reason, self.exit_code = f"free disk below {MIN_FREE_GB:.0f} GB", 3
            return True
        return False

    # ---------- main loop ----------
    async def run(self) -> int:
        headers = {"User-Agent": config.USER_AGENT, "Accept-Language": "en,de;q=0.8"}
        limits = httpx.Limits(max_connections=self.inflight * 2, max_keepalive_connections=self.inflight)
        tasks: set[asyncio.Task] = set()
        async with httpx.AsyncClient(headers=headers, timeout=30, follow_redirects=True, limits=limits) as client:
            ticker = asyncio.create_task(self._ticker())
            try:
                while not self._should_stop():
                    launched = False
                    if len(tasks) < self.inflight:
                        sid = self._pick()
                        url = self._take(sid) if sid else None
                        if url:
                            self.busy.add(sid)
                            g = self._group(sid)
                            if g == "unibe":
                                self.group_next[g] = max(time.monotonic(), self.group_next[g]) + 1 / self.rps
                            t = asyncio.create_task(self._one(client, sid, url))
                            tasks.add(t)
                            t.add_done_callback(tasks.discard)
                            launched = True
                    if not launched:
                        if not tasks and not self._any_queued():
                            self.stop_reason = "finished: every site's queue is empty"
                            break
                        await asyncio.sleep(0.02)
                    self.st.commit()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
            finally:
                ticker.cancel()
                self.st.commit(force=True)
                for e in self.st.events:
                    print("  " + e)
                self.st.events.clear()
                self._round_end(final=True)
                self._progress()
                for f in self.manifests.values():
                    f.close()
                self.log.close()
        print(f"Stopped: {self.stop_reason}. This run fetched {self.total['fetched']:,} pages; "
              f"database: {self.st.counts['person']:,} people, {self.st.counts['unit']:,} units.")
        return self.exit_code


def run(hours: float, rps: float, delay: float, inflight: int, verbose: bool) -> int:
    from .seed import seed
    st = seed()
    statuses = Counter(s["status"] for s in st.sources.values())
    print(f"Net: {len(st.sources)} sites ({statuses['active']} active), {len(st.queued):,} URLs queued, "
          f"{st.counts['person']:,} people so far. Limits: {rps}/s for *.unibe.ch, {delay}s per site, "
          f"{hours} h. Ctrl+C stops safely; rerun to continue.\n", flush=True)
    # sites marked done/budget in an earlier run may have a raised budget or new links now
    for sid, s in st.sources.items():
        if s["status"] == "budget" and s["fetched"] < s["budget"]:
            st.update_source(sid, status="active", reason="budget raised")
    runner = Runner(st, hours, rps, delay, inflight, verbose)
    try:
        return asyncio.run(runner.run())
    except KeyboardInterrupt:
        st.commit(force=True)
        print("\nInterrupted. State saved; run `python -m navigator net run` again to continue.")
        return 130
