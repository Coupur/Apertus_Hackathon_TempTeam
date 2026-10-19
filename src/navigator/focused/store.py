"""Compact SQLite persistence. Rejected page bodies never enter the database."""
import hashlib
import json
import sqlite3
from pathlib import Path

from .keywords import record_keywords
from .selection import identity_text
from .ranking import assess_evidence, evaluation_for, score_record, rank
from .privacy import public_record


def finding_keywords(record: dict) -> list[str]:
    evidence=record.get("evidence", [])
    if record.get("type") in ("expert", "team"):
        evidence=evidence+[e for link in record.get("related_works", []) for e in link.get("work_evidence", [])]
    return record_keywords({**record,"evidence":evidence})


def identity_keys(record: dict) -> set[str]:
    if record.get("type") in ("expert", "team"):
        from .entities import profile_identity
        if record.get("identity_url") and record.get("identity_evidence"):
            return {record["type"] + ":profile:" + profile_identity(record["identity_url"])}
        return {record["identity_anchor"]}
    keys = {f"identifier:{i['kind']}:" + (i["value"].strip().casefold() if i["kind"] == "doi"
                                               else identity_text(i["value"])) for i in record["identifiers"]}
    keys.update("work:detail_url:" + url for url in record.get("identity_urls", []))
    # Name-only matches require a matching unit and source, not just membership of
    # the same large university. Cross-source matches use explicit identifiers.
    # Rule-authored titles describe a signal and are intentionally generic.
    names = (record["original_name"],) if record.get("matched_rules") else (record["title"], record["original_name"])
    for name in names:
        if len(identity_text(name)) >= 12:
            for source in record["source_ids"]:
                keys.add(f"name:{identity_text(name)}:{identity_text(record['unit'])}:{source}")
    return keys


class Store:
    def __init__(self, path: Path, limit: int = 700, *, defer_trim: bool = False):
        if not 1 <= limit <= 700:
            raise ValueError("The finding limit must be between 1 and 700")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.limit = limit
        self.defer_trim = defer_trim
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS findings (id TEXT PRIMARY KEY, record TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS identities (
                key TEXT PRIMARY KEY, finding_id TEXT NOT NULL REFERENCES findings(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS observations (
                finding_id TEXT NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
                source_url TEXT NOT NULL, record TEXT NOT NULL,
                PRIMARY KEY (finding_id, source_url));
            CREATE TABLE IF NOT EXISTS crawl_state (
                url TEXT PRIMARY KEY, state TEXT NOT NULL, checked_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, report TEXT NOT NULL);
        """)
        # A result and a project description can refer to the same named work.
        # Add current identity keys to databases created with type-prefixed keys.
        with self.db:
            for fid, payload in self.db.execute("SELECT id, record FROM findings").fetchall():
                for key in identity_keys(json.loads(payload)):
                    self.db.execute("INSERT OR IGNORE INTO identities VALUES (?, ?)", (key, fid))

    def close(self):
        self.db.close()

    def findings(self) -> list[dict]:
        return sorted((json.loads(row[0]) for row in self.db.execute("SELECT record FROM findings")),
                      key=rank, reverse=True)

    def state(self, url: str) -> dict:
        row = self.db.execute("SELECT state FROM crawl_state WHERE url=?", (url,)).fetchone()
        return json.loads(row[0]) if row else {}

    def save_state(self, url: str, state: dict, checked_at: str):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO crawl_state VALUES (?, ?, ?)",
                            (url, json.dumps(state), checked_at))

    def pending(self, include_failed: bool = False) -> list[tuple[str, dict]]:
        return [(url, json.loads(state)) for url, state in self.db.execute("SELECT url, state FROM crawl_state")
                if json.loads(state).get("status") in (("pending", "failed") if include_failed else ("pending",))]

    def completed_urls(self, traversal_version: str) -> set[str]:
        return {url for url, raw in self.db.execute("SELECT url, state FROM crawl_state")
                if (state := json.loads(raw)).get("status") == "checked"
                and state.get("traversal_version") == traversal_version}

    def save_pending(self, entries: dict, checked_at: str):
        with self.db:
            self.db.executemany("INSERT OR REPLACE INTO crawl_state VALUES (?, ?, ?)",
                                [(url, json.dumps(state), checked_at) for url, state in entries.items()])

    def upsert(self, incoming: dict) -> str:
        """Use maximum significance, never mention counts or recency, when merging."""
        incoming = public_record(incoming)
        if incoming.get("type") in ("expert", "team"):
            from .entities import eligible_link
            if not any(eligible_link(link) for link in incoming.get("related_works", [])):
                raise ValueError("An entity requires an explicit role in an accepted work")
        keys = identity_keys(incoming)
        if not keys:
            keys = {f"{incoming['type']}:name:{identity_text(incoming['title'])}:{incoming['unit']}:{incoming['source_ids'][0]}"}
        ids = {row[0] for key in keys for row in self.db.execute("SELECT finding_id FROM identities WHERE key=?", (key,))}
        current_keys = set(keys)
        previous = [json.loads(row[0]) for fid in ids for row in self.db.execute(
            "SELECT record FROM observations WHERE finding_id=?", (fid,))]
        stable = sorted(k for k in keys if k.startswith(("work:detail_url:", "expert:profile:", "team:profile:")))
        fid = min(ids) if ids else hashlib.sha256((stable[0] if stable else min(keys)).encode()).hexdigest()[:24]
        incoming = {**incoming, "id": fid}
        incoming["keywords"] = finding_keywords(incoming)
        score_record(incoming)
        observations = {p["source_urls"][0]: {**p, "id": fid} for p in previous}
        observations[incoming["source_urls"][0]] = incoming
        # Bound retained observations independently of the number of repeated mentions.
        selected = sorted(observations.values(), key=rank, reverse=True)[:8]
        if incoming not in selected:
            selected[-1] = incoming
        best = max(selected, key=rank)
        result = {**best, "id": fid, "fetched_at": incoming["fetched_at"]}
        for field, bound in (("organizations", 3), ("source_ids", 50), ("source_urls", 20),
                             ("external_references", 20), ("topics", 12), ("identifiers", 10), ("experts", 10),
                             ("teams", 10), ("related_works", 20), ("roles", 20), ("attributed_evidence", 30),
                             ("identity_evidence", 8), ("competencies", 24), ("identity_urls", 10)):
            unique = {}
            for rec in [best, incoming, *selected]:
                for value in rec.get(field, []):
                    unique[json.dumps(value, sort_keys=True)] = value
            result[field] = list(unique.values())[:bound]
        # Keep the strongest observation's matching evidence first; do not combine scores
        # from different observations into an artificial higher total.
        evidence = {}
        for rec in [best, incoming, *selected]:
            for e in rec["evidence"]:
                if rec is not best and rec is not incoming and e["source_url"] in incoming["source_urls"]:
                    continue
                evidence[(e["source_url"], e["quote"])] = e
        result["evidence"] = list(evidence.values())[:20]
        # Recompute from retained evidence so withdrawn observations lose tags.
        result["keywords"] = finding_keywords(result)
        score_record(result)
        if incoming["status"] != "unknown":
            result.update(status=incoming["status"], status_quote=incoming["status_quote"],
                          status_source_url=incoming["source_urls"][0])
        with self.db:
            for old in ids:
                keys.update(row[0] for row in self.db.execute("SELECT key FROM identities WHERE finding_id=?", (old,)))
                self.db.execute("DELETE FROM findings WHERE id=?", (old,))
            self.db.execute("INSERT INTO findings VALUES (?, ?)", (fid, json.dumps(result, ensure_ascii=False)))
            bounded_keys = sorted(current_keys) + sorted(keys - current_keys)
            for key in bounded_keys[:80]:
                self.db.execute("INSERT OR REPLACE INTO identities VALUES (?, ?)", (key, fid))
            for observation in selected:
                self.db.execute("INSERT INTO observations VALUES (?, ?, ?)",
                                (fid, observation["source_urls"][0], json.dumps(observation, ensure_ascii=False)))
            self._trim()
        return fid

    def reconcile_source(self, url: str, accepted_ids: set[str]):
        """Withdraw obsolete observations only after a complete, successful evaluation."""
        affected = [r[0] for r in self.db.execute("SELECT finding_id FROM observations WHERE source_url=?", (url,))
                    if r[0] not in accepted_ids]
        with self.db:
            for fid in affected:
                self.db.execute("DELETE FROM observations WHERE finding_id=? AND source_url=?", (fid, url))
                remaining = self.db.execute("SELECT record FROM observations WHERE finding_id=? LIMIT 1", (fid,)).fetchone()
                if remaining:
                    self.upsert(json.loads(remaining[0]))
                else:
                    self.db.execute("DELETE FROM findings WHERE id=?", (fid,))

    def _trim(self):
        if self.defer_trim:
            return
        for rec in self.findings()[self.limit:]:
            self.db.execute("DELETE FROM findings WHERE id=?", (rec["id"],))

    def finish(self, report: dict, state_limit: int | None):
        with self.db:
            if report.get("mode") != "source_check":
                self._trim()
            self.db.execute("INSERT INTO runs(report) VALUES (?)", (json.dumps(report, ensure_ascii=False),))
            self.db.execute("DELETE FROM runs WHERE id NOT IN (SELECT id FROM runs ORDER BY id DESC LIMIT 10)")
            if state_limit is not None:
                self.db.execute("DELETE FROM crawl_state WHERE url NOT IN (SELECT url FROM crawl_state ORDER BY checked_at DESC LIMIT ?)", (state_limit,))

    def last_report(self) -> dict | None:
        row = self.db.execute("SELECT report FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        return json.loads(row[0]) if row else None


def read_highlights(path: Path) -> tuple[list[dict], dict | None]:
    """Inspect without creating or changing a database."""
    if not path.exists():
        raise FileNotFoundError(f"No focused database found at {path}. Run focused-crawl first.")
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        records = [public_record(json.loads(r[0])) for r in db.execute("SELECT record FROM findings")]
        report = db.execute("SELECT report FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        return sorted(records, key=rank, reverse=True), json.loads(report[0]) if report else None
    finally:
        db.close()


def refresh_evaluations(path: Path, source_snapshot: Path | None = None) -> dict[str, int]:
    """Transactional rescoring, optionally restoring entity assertions from dated sources."""
    if not path.exists():
        raise FileNotFoundError(f"No focused database found at {path}. Run focused-crawl first.")
    from .entities import enrich_entity_evidence
    from .models import Document
    sources = {}
    if source_snapshot is not None:
        with source_snapshot.open(encoding='utf-8') as stream:
            for line in stream:
                document = Document(**json.loads(line))
                sources[document.url] = document
                if document.retrieval_url:
                    sources[document.retrieval_url] = document
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True, timeout=30)
    counts = {}
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            for table in ("findings", "observations"):
                changed = 0
                for rowid, payload in db.execute(f"SELECT rowid, record FROM {table}").fetchall():
                    record = json.loads(payload)
                    if record.get('type') in ('expert', 'team'):
                        for url in sorted({link['source_url'] for link in record.get('related_works', [])}):
                            if url in sources:
                                enrich_entity_evidence(record, sources[url])
                    evaluation = evaluation_for(record)
                    record["evaluation"] = evaluation
                    if "selection_score" in record:
                        record["selection_score"] = evaluation["score"]
                    if record != json.loads(payload):
                        db.execute(f"UPDATE {table} SET record=? WHERE rowid=?",
                                   (json.dumps(record, ensure_ascii=False), rowid))
                        changed += 1
                counts[table] = changed
        return counts
    finally:
        db.close()


def refresh_keywords(path: Path) -> dict[str, int]:
    """Backfill subject tags atomically without fetching, reranking or new IDs."""
    if not path.exists():
        raise FileNotFoundError(f"No focused database found at {path}. Run focused-crawl first.")
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True, timeout=30)
    counts = {}
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            for table in ("findings", "observations"):
                changed = 0
                for rowid, payload in db.execute(f"SELECT rowid, record FROM {table}").fetchall():
                    record = json.loads(payload)
                    keywords = finding_keywords(record)
                    if record.get("keywords") != keywords:
                        record["keywords"] = keywords
                        db.execute(f"UPDATE {table} SET record=? WHERE rowid=?",
                                   (json.dumps(record, ensure_ascii=False), rowid))
                        changed += 1
                counts[table] = changed
        return counts
    finally:
        db.close()
