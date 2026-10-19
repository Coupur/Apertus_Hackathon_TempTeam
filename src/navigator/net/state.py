"""The net's memory: sources, URL frontier, discovered hosts and extracted records in data/net/net.sqlite.

The crawler is the only writer. Changes are committed every few seconds, so a crash or Ctrl+C loses at
most a few seconds of work, and the next run continues from the URLs that are still queued.
Every queued URL stores why it was queued (`reason`), so we can always say why the net went somewhere.
"""
import hashlib
import heapq
import itertools
import json
import re
import sqlite3
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from .. import config
from .scope import KIND_PRIORITY, classify, excluded, host_of, in_scope, person_slug

NET_DIR = config.DATA_DIR / "net"
DB_FILE = NET_DIR / "net.sqlite"

DEFAULT_BUDGET = 1500                  # safety cap per site; sites normally stop because their queue runs dry
BUDGETS = {"www": 3000, "mediarelations": 300}
NEW_UNIT_PAGES, NEW_UNIT_BONUS = 25, 2.0  # fairness: every unit's first pages jump the queue, however small it is
DEPTH_COST = 0.25
GER_PENALTY = 3.0                       # English first; the German twin usually has another path, so we cannot map it
OTHER_MAX_DEPTH = 4                    # 'other' pages are only followed close to a unit's home
CANDIDATE_MIN_PAGES = 2                 # a new *.unibe.ch host becomes a source once 2 pages link to it

SCHEMA = """
CREATE TABLE IF NOT EXISTS source (
  id TEXT PRIMARY KEY, host TEXT UNIQUE, name TEXT, url TEXT, institution TEXT, status TEXT,
  budget INTEGER, fetched INTEGER DEFAULT 0, kept INTEGER DEFAULT 0, other_fetched INTEGER DEFAULT 0,
  added_by TEXT, reason TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS url (
  url TEXT PRIMARY KEY, source_id TEXT, status TEXT, kind TEXT, priority REAL, depth INTEGER,
  found_on TEXT, anchor TEXT, reason TEXT, fallback TEXT, attempts INTEGER DEFAULT 0,
  http_status INTEGER, page_type TEXT, relevance REAL, fetched_at TEXT);
CREATE INDEX IF NOT EXISTS url_status ON url(status, source_id);
CREATE TABLE IF NOT EXISTS candidate (host TEXT PRIMARY KEY, pages INTEGER, sample TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS record (
  id TEXT PRIMARY KEY, type TEXT, source_id TEXT, url TEXT, quality INTEGER, data TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS record_type ON record(type);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""
SOURCE_COLS = ["id", "host", "name", "url", "institution", "status", "budget", "fetched", "kept", "other_fetched"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def source_id_for_host(host: str) -> str:
    if host == "unibe.ch":
        return "www"
    if host.endswith(".unibe.ch"):
        return host.removesuffix(".unibe.ch").replace(".", "-")
    return host.split(".")[0]


def person_id(p: dict, sid: str) -> str:
    """Same person, same id: email first, then profile URL, then name within the site."""
    if p.get("email"):
        key = p["email"].lower()
    elif p.get("profile_url"):
        key = re.sub(r"^https?://(www\.)?|_(eng|ger)\.html$", "", p["profile_url"].lower())
    else:
        key = f"{p.get('name_clean', '').lower()}|{sid}"
    return "person:" + hashlib.sha1(key.encode()).hexdigest()[:12]


def _merge(old: dict, new: dict, prefer_new: bool) -> dict:
    out = dict(old)
    for k, v in new.items():
        if k == "evidence":
            seen = {(e["field"], e["quote"], e["url"]) for e in out.get("evidence", [])}
            out["evidence"] = out.get("evidence", []) + [e for e in v if (e["field"], e["quote"], e["url"]) not in seen]
        elif isinstance(v, list):
            out[k] = list(dict.fromkeys((out.get(k) or []) + v))
        elif v and (prefer_new or not out.get(k)):
            out[k] = v
    return out


class State:
    def __init__(self):
        NET_DIR.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(DB_FILE, timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)
        self._seq = itertools.count()
        self._last_commit = time.time()
        self.events: list[str] = []  # human-readable news for the console (new site, site done, ...)
        self._load()

    # ---------- loading and saving ----------
    def _load(self):
        self.sources = {r[0]: dict(zip(SOURCE_COLS, r))
                        for r in self.db.execute(f"SELECT {', '.join(SOURCE_COLS)} FROM source")}
        self.host_to_sid = {s["host"]: sid for sid, s in self.sources.items()}
        self.netloc = {sid: urlsplit(s["url"]).netloc.lower() for sid, s in self.sources.items()}
        self.known, self.fetched, self.queued, self.kind_of = set(), set(), {}, {}
        self.slugs: set[tuple[str, str]] = set()  # (host, person slug) of every known profile URL
        self.heaps = defaultdict(list)
        for url, sid, status, prio, kind in self.db.execute("SELECT url, source_id, status, priority, kind FROM url"):
            self.known.add(url)
            self._note_slug(url)
            if status == "fetched":
                self.fetched.add(url)
            elif status == "queued":
                self.queued[url], self.kind_of[url] = prio, kind
                self.heaps[sid].append((-prio, next(self._seq), url))
        for h in self.heaps.values():
            heapq.heapify(h)
        self.candidates = {h: {"pages": n, "samples": json.loads(s), "status": st, "last": None}
                           for h, n, s, st in self.db.execute("SELECT host, pages, sample, status FROM candidate")}
        self.record_ids = {r[0] for r in self.db.execute("SELECT id FROM record")}
        self.counts = Counter(t for (t,) in self.db.execute("SELECT type FROM record"))

    def _note_slug(self, url: str):
        slug = person_slug(url)
        if slug:
            self.slugs.add((host_of(url), slug))

    def commit(self, force: bool = False):
        if force or time.time() - self._last_commit > 2:
            self.db.commit()
            self._last_commit = time.time()

    def get_meta(self, key: str):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))

    # ---------- sources ----------
    def add_source(self, sid, host, name, url, institution="University of Bern", added_by="config",
                   reason="") -> str:
        if host in self.host_to_sid:
            return self.host_to_sid[host]
        base, i = sid, 2
        while sid in self.sources:
            sid, i = f"{base}-{i}", i + 1
        s = {"id": sid, "host": host, "name": name, "url": url, "institution": institution, "status": "active",
             "budget": BUDGETS.get(sid, DEFAULT_BUDGET), "fetched": 0, "kept": 0, "other_fetched": 0}
        self.db.execute(f"INSERT INTO source ({', '.join(SOURCE_COLS)}, added_by, reason, updated_at) "
                        f"VALUES ({', '.join('?' * (len(SOURCE_COLS) + 3))})",
                        (*s.values(), added_by, reason, now_iso()))
        self.sources[sid], self.host_to_sid[host] = s, sid
        self.netloc[sid] = urlsplit(url).netloc.lower()
        if added_by != "config":
            self.events.append(f"[new site] {sid} ({host}): {reason}")
        return sid

    def update_source(self, sid: str, **fields):
        self.sources[sid].update({k: v for k, v in fields.items() if k in SOURCE_COLS})
        cols = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE source SET {cols}, updated_at=? WHERE id=?", (*fields.values(), now_iso(), sid))

    def bump(self, sid: str, field: str, n: int = 1):
        self.sources[sid][field] += n
        self.db.execute(f"UPDATE source SET {field}={field}+? WHERE id=?", (n, sid))

    def canonical(self, url: str, sid: str) -> str:
        """https and the site's own host spelling (www. or not), so each page has one key."""
        p = urlsplit(url)
        return urlunsplit(("https", self.netloc[sid], p.path or "/", p.query, ""))

    # ---------- frontier ----------
    def enqueue(self, url, sid, kind, priority, depth, found_on="", anchor="", reason="", fallback=None) -> bool:
        if url in self.known:
            if url in self.queued and priority > self.queued[url] + 1e-9:  # found again from a better page
                self.queued[url] = priority
                heapq.heappush(self.heaps[sid], (-priority, next(self._seq), url))
                self.db.execute("UPDATE url SET priority=?, reason=? WHERE url=?", (priority, reason, url))
            return False
        self.known.add(url)
        self._note_slug(url)
        self.queued[url], self.kind_of[url] = priority, kind
        heapq.heappush(self.heaps[sid], (-priority, next(self._seq), url))
        self.db.execute("INSERT OR IGNORE INTO url (url, source_id, status, kind, priority, depth, found_on, anchor,"
                        " reason, fallback) VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?)",
                        (url, sid, kind, priority, depth, found_on, anchor, reason, fallback))
        if self.sources[sid]["status"] == "done":
            self.update_source(sid, status="active", reason="new links found")
        return True

    def requeue(self, url: str, sid: str, priority: float, attempts: int):
        self.queued[url] = priority
        heapq.heappush(self.heaps[sid], (-priority, next(self._seq), url))
        self.db.execute("UPDATE url SET status='queued', priority=?, attempts=? WHERE url=?", (priority, attempts, url))

    def peek(self, sid: str) -> float | None:
        h = self.heaps.get(sid)
        while h:
            negp, _, url = h[0]
            if self.queued.get(url) == -negp:
                return -negp
            heapq.heappop(h)  # stale entry: fetched already or re-queued with a higher priority
        return None

    def pop(self, sid: str) -> str | None:
        if self.peek(sid) is None:
            return None
        _, _, url = heapq.heappop(self.heaps[sid])
        del self.queued[url]  # in flight; the database still says 'queued' until mark()
        return url

    def queued_count(self, sid: str) -> int:
        return sum(1 for e in self.heaps.get(sid, ()) if self.queued.get(e[2]) == -e[0])

    def info(self, url: str) -> dict:
        row = self.db.execute("SELECT depth, kind, fallback, attempts, priority FROM url WHERE url=?", (url,)).fetchone()
        return dict(zip(["depth", "kind", "fallback", "attempts", "priority"], row or (0, "other", None, 0, 0.0)))

    def mark(self, url: str, status: str, **fields):
        fields["status"] = status
        self.db.execute(f"UPDATE url SET {', '.join(f'{k}=?' for k in fields)} WHERE url=?", (*fields.values(), url))
        if status == "fetched":
            self.fetched.add(url)

    def add_fetched(self, url: str, sid: str, depth: int = 0):
        """Record a URL as already downloaded (old crawl, or the final URL of a redirect)."""
        if url in self.fetched:
            return
        if url in self.known:
            self.queued.pop(url, None)
            self.db.execute("UPDATE url SET status='fetched' WHERE url=?", (url,))
        else:
            self.known.add(url)
            self._note_slug(url)
            self.db.execute("INSERT OR IGNORE INTO url (url, source_id, status, depth) VALUES (?, ?, 'fetched', ?)",
                            (url, sid, depth))
        self.fetched.add(url)

    # ---------- expanding: where to go next ----------
    def expand(self, page_url: str, depth: int, result: dict):
        for link, anchor, hint in result["links"]:
            self._link(link, anchor, hint, page_url, result["relevance"], result["kept"], depth, result["page_type"])

    def _link(self, link, anchor, hint, page_url, parent_rel, kept, depth, page_type):
        host = host_of(link)
        if not in_scope(host):
            return
        sid = self.host_to_sid.get(host)
        if sid is None:
            if not excluded(host):
                self._candidate(host, page_url, link)
            return
        kind = hint or classify(link, anchor)
        if kind == "skip" or (kind == "other" and (not kept or depth + 1 > OTHER_MAX_DEPTH)):
            return
        url = self.canonical(link, sid)
        if url in self.known:
            if url in self.queued:  # found again: maybe from a better page
                self.enqueue(url, sid, kind, self._priority(kind, parent_rel, depth, sid, url), depth + 1, page_url,
                             anchor, f"{kind} via {page_type}")
            return
        slug = person_slug(url)
        if slug and (host, slug) in self.slugs:
            return  # the other language version of a profile we already have or have queued
        self.enqueue(url, sid, kind, self._priority(kind, parent_rel, depth, sid, url), depth + 1, page_url, anchor,
                     f"{kind} via {page_type}")

    def _priority(self, kind: str, parent_rel: float, depth: int, sid: str, url: str) -> float:
        prio = KIND_PRIORITY[kind] + parent_rel - DEPTH_COST * (depth + 1)
        if self.sources[sid]["fetched"] < NEW_UNIT_PAGES:
            prio += NEW_UNIT_BONUS
        if url.endswith("_ger.html"):
            prio -= GER_PENALTY
        return round(prio, 3)

    def _candidate(self, host: str, page_url: str, link: str):
        c = self.candidates.setdefault(host, {"pages": 0, "samples": [], "status": "candidate", "last": None})
        if c["status"] != "candidate":
            return
        if page_url != c["last"]:
            c["pages"], c["last"] = c["pages"] + 1, page_url
        if link not in c["samples"] and len(c["samples"]) < 20:
            c["samples"].append(link)
        if c["pages"] >= CANDIDATE_MIN_PAGES:
            c["status"] = "promoted"
        self.db.execute("INSERT OR REPLACE INTO candidate VALUES (?, ?, ?, ?)",
                        (host, c["pages"], json.dumps(c["samples"]), c["status"]))
        if c["status"] != "promoted":
            return
        netloc = urlsplit(link).netloc.lower()
        sid = self.add_source(source_id_for_host(host), host, host, f"https://{netloc}/", added_by="discovered",
                              reason=f"linked from {c['pages']} pages")
        self.enqueue(f"https://{netloc}/", sid, "home", KIND_PRIORITY["home"] + NEW_UNIT_BONUS, 0, page_url, "",
                     "home of new site")
        for s in c["samples"]:
            self._link(s, "", None, page_url, 0.5, True, 0, "candidate")

    # ---------- records ----------
    def upsert_record(self, rid: str, rtype: str, sid: str, url: str, quality: int, data: dict) -> bool:
        """Insert, or merge into the existing record (a profile beats a list entry). True if new."""
        data = {**data, "seen_on": [url]}
        if rid in self.record_ids:
            oldq, old = self.db.execute("SELECT quality, data FROM record WHERE id=?", (rid,)).fetchone()
            merged = _merge(json.loads(old), data, prefer_new=quality >= oldq)
            self.db.execute("UPDATE record SET quality=?, data=?, updated_at=? WHERE id=?",
                            (max(quality, oldq), json.dumps(merged, ensure_ascii=False), now_iso(), rid))
            return False
        self.db.execute("INSERT INTO record VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (rid, rtype, sid, url, quality, json.dumps(data, ensure_ascii=False), now_iso()))
        self.record_ids.add(rid)
        self.counts[rtype] += 1
        return True

    def store_records(self, result: dict, url: str, sid: str) -> Counter:
        new = Counter()
        inst = self.sources[sid]["institution"]
        for p in result["persons"]:
            if not p.get("name"):
                continue
            if self.upsert_record(person_id(p, sid), "person", sid, url, 2 if p["kind"] == "profile" else 1,
                                  {**p, "source_id": sid, "institution": inst}):
                new["person"] += 1
        u = result["unit"]
        if u.get("name"):
            rid = "unit:" + (u["cms_client"] or sid)
            if self.upsert_record(rid, "unit", sid, url, 2 if result["page_type"] == "home" else 1,
                                  {**u, "source_id": sid, "host": self.sources[sid]["host"], "institution": inst}):
                new["unit"] += 1
        return new
