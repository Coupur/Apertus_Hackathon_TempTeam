"""`navigator net status` and `navigator net export`.

status reads net.sqlite with plain SQL, so it can run in a second terminal while `net run` is crawling.
export writes the records to data/net/export/<type>.jsonl for the processing and search steps.
"""
import json
import sqlite3

from .state import DB_FILE, NET_DIR


def _db():
    if not DB_FILE.exists():
        raise SystemExit("No net database yet: run `python -m navigator net seed` first.")
    return sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True, timeout=30)


def status(top: int = 15):
    db = _db()
    q = lambda sql, *a: db.execute(sql, a).fetchall()
    print("URLs:    " + " | ".join(f"{s} {n:,}" for s, n in q("SELECT status, COUNT(*) FROM url GROUP BY status ORDER BY 2 DESC")))
    print("Queued:  " + " | ".join(f"{k} {n:,}" for k, n in
                                   q("SELECT kind, COUNT(*) FROM url WHERE status='queued' GROUP BY kind ORDER BY 2 DESC")))
    print("Fetched: " + " | ".join(f"{k} {n:,}" for k, n in
                                   q("SELECT page_type, COUNT(*) FROM url WHERE status='fetched' AND page_type IS NOT NULL "
                                     "GROUP BY page_type ORDER BY 2 DESC")))
    print("Sites:   " + " | ".join(f"{s} {n}" for s, n in q("SELECT status, COUNT(*) FROM source GROUP BY status ORDER BY 2 DESC"))
          + f" | discovered {q('SELECT COUNT(*) FROM source WHERE added_by != ?', 'config')[0][0]}")
    people = q("SELECT COUNT(*), SUM(json_extract(data,'$.email') != ''), "
               "SUM(json_array_length(json_extract(data,'$.expertise')) > 0), SUM(quality = 2) "
               "FROM record WHERE type='person'")[0]
    units = q("SELECT COUNT(*) FROM record WHERE type='unit'")[0][0]
    print(f"Records: {people[0] or 0:,} people ({people[1] or 0:,} with email, {people[2] or 0:,} with expertise, "
          f"{people[3] or 0:,} from a profile page) | {units:,} units")

    print(f"\nTop {top} sites by queued URLs (queued / fetched / kept / people):")
    rows = q("SELECT s.id, s.status, s.fetched, s.kept, "
             " (SELECT COUNT(*) FROM url u WHERE u.source_id = s.id AND u.status = 'queued') AS queued, "
             " (SELECT COUNT(*) FROM record r WHERE r.source_id = s.id AND r.type = 'person') AS people "
             "FROM source s ORDER BY queued DESC, s.fetched DESC LIMIT ?", top)
    for sid, st, fetched, kept, queued, ppl in rows:
        print(f"  {sid:<22} {st:<8} {queued:>6,} / {fetched:>5,} / {kept:>5,} / {ppl:>5,}")

    print("\nSites with no people yet (a unit we cannot show experts for):")
    rows = q("SELECT s.id, s.fetched, s.status FROM source s WHERE s.fetched > 0 AND NOT EXISTS "
             "(SELECT 1 FROM record r WHERE r.source_id = s.id AND r.type = 'person') ORDER BY s.fetched DESC LIMIT 25")
    print("  " + (", ".join(f"{sid} ({n}, {st})" for sid, n, st in rows) or "none"))

    rounds = NET_DIR / "rounds.jsonl"
    if rounds.exists():
        last = [json.loads(l) for l in rounds.read_text(encoding="utf-8").splitlines()[-3:]]
        print("\nLast rounds: " + " | ".join(f"#{r['round']} {r['fetched']} pages, +{r['new_people']} people "
                                             f"({r['finished'][11:16]} UTC)" for r in last))


def export() -> dict:
    db = _db()
    out_dir = NET_DIR / "export"
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for (rtype,) in db.execute("SELECT DISTINCT type FROM record"):
        with open(out_dir / f"{rtype}.jsonl", "w", encoding="utf-8") as f:
            n = 0
            for rid, sid, url, quality, data in db.execute(
                    "SELECT id, source_id, url, quality, data FROM record WHERE type=? ORDER BY id", (rtype,)):
                f.write(json.dumps({"id": rid, "type": rtype, "source_id": sid, "url": url, "quality": quality,
                                    **json.loads(data)}, ensure_ascii=False) + "\n")
                n += 1
        counts[rtype] = n
    print(f"Exported {counts} to {out_dir}")
    return counts
