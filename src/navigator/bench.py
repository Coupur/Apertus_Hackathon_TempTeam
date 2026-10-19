"""Test bench: run every gold question, find where the expected answers landed, score the run.

  bench/gold.jsonl         the questions and their known right answers (hand-checked)
  bench/runs/<label>.json  one file per run: config, summary metrics, every question's ranking
  bench/report.html        all runs side by side, rebuilt after every run

Gold line:
  {"qid", "query", "intent", "section", "types": ["person"], "no_answer": false, "status": "draft",
   "expected": [{"label": "Jane Doe", "keys": ["email:jane.doe@unibe.ch", "url:..."], "grade": 3,
                 "why": "leads the group", "source": "https://..."}]}
A result matches an expected answer if they share any key (email:, url:, unit:<source_id>).
Grades: 3 = must be in the top 3, 2 = should be in the top 10, 1 = acceptable.
"""
import html
import json
import math
import random
import time
from datetime import datetime
from pathlib import Path

from . import config, embed
from .rank import Ranker, RankConfig, norm_url

BENCH_DIR = config.ROOT / "bench"
GOLD_FILE = BENCH_DIR / "gold.jsonl"
RUNS_DIR = BENCH_DIR / "runs"
REPORT_FILE = BENCH_DIR / "report.html"
DEPTH = 50  # ranks kept per question, for candidate recall@50


def load_gold(path: Path = GOLD_FILE) -> list[dict]:
    gold = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("//"):
            g = json.loads(line)
            for e in g.get("expected", []):
                e["keys"] = [_norm_key(k) for k in e["keys"]]
            gold.append(g)
    return gold


def _norm_key(k: str) -> str:
    kind, _, v = k.partition(":")
    if kind == "url":
        return f"url:{norm_url(v)}"
    return f"{kind}:{v.strip().lower()}"


def ranking_for(question: dict, res: dict) -> list[dict]:
    """The list we score: the requested result types merged by score; pages if nothing else is on."""
    types = question.get("types") or ["person", "unit"]
    lists = {"person": res["people"], "unit": res["units"], "page": res["pages"]}
    merged = [r for t in types for r in lists.get(t, [])]
    if not merged:
        merged = res["pages"]
    return sorted(merged, key=lambda r: -r["score"])


def score_question(q: dict, ranking: list[dict]) -> dict:
    """Rank of each expected answer and the per-question metrics."""
    found = []
    for e in q.get("expected", []):
        keys = set(e["keys"])
        rank = next((i + 1 for i, r in enumerate(ranking) if keys & set(r["keys"])), None)
        found.append({"label": e.get("label", e["keys"][0]), "grade": e["grade"], "rank": rank,
                      "keys": e["keys"], "why": e.get("why", ""), "source": e.get("source", "")})
    m = {}
    if q.get("no_answer") or not found:
        return {"found": found, "metrics": m}
    leads = [f for f in found if f["grade"] == 3]
    if leads:
        m["hit@3"] = float(any(f["rank"] and f["rank"] <= 3 for f in leads))
    must = [f for f in found if f["grade"] >= 2]
    if must:
        m["recall@10"] = sum(1 for f in must if f["rank"] and f["rank"] <= 10) / len(must)
        m["cand_recall@50"] = sum(1 for f in must if f["rank"] and f["rank"] <= DEPTH) / len(must)
    first = min((f["rank"] for f in found if f["rank"]), default=None)
    m["mrr"] = 1 / first if first else 0.0
    # nDCG@10: each expected answer counts once, at the rank where it first appears
    dcg = sum((2 ** f["grade"] - 1) / math.log2(f["rank"] + 1) for f in found if f["rank"] and f["rank"] <= 10)
    ideal = sorted((f["grade"] for f in found), reverse=True)[:10]
    idcg = sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(ideal))
    m["ndcg@10"] = dcg / idcg if idcg else 0.0
    return {"found": found, "metrics": m}


def _primary_key(r: dict) -> str:
    return next((k for k in r["keys"] if k.startswith(("email:", "unit:"))), r["keys"][0])


def paraphrase_overlap(rows: list[dict]) -> float | None:
    """Mean Jaccard overlap of the top-10 results between questions that share an `intent`."""
    by_intent = {}
    for r in rows:
        if r.get("intent") and not r.get("no_answer"):
            by_intent.setdefault(r["intent"], []).append({_primary_key(x) for x in r["top"][:10]})
    vals = []
    for sets in by_intent.values():
        for i in range(len(sets)):
            for j in range(i + 1, len(sets)):
                union = sets[i] | sets[j]
                vals.append(len(sets[i] & sets[j]) / len(union) if union else 0.0)
    return sum(vals) / len(vals) if vals else None


def bootstrap(values: list[float], n: int = 1000, seed: int = 7) -> tuple[float, float]:
    if len(values) < 2:
        return (values[0], values[0]) if values else (0.0, 0.0)
    rnd = random.Random(seed)
    means = sorted(sum(rnd.choices(values, k=len(values))) / len(values) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def summarize(rows: list[dict], floor: float) -> dict:
    out = {}
    for name in ("hit@3", "recall@10", "mrr", "ndcg@10", "cand_recall@50"):
        vals = [r["metrics"][name] for r in rows if name in r["metrics"]]
        if vals:
            lo, hi = bootstrap(vals)
            out[name] = {"mean": round(sum(vals) / len(vals), 3), "ci95": [round(lo, 3), round(hi, 3)], "n": len(vals)}
    neg = [r for r in rows if r.get("no_answer")]
    pos = [r for r in rows if not r.get("no_answer")]
    if neg:
        out["no_answer_acc"] = {"mean": round(sum(r["best_score"] < floor for r in neg) / len(neg), 3), "n": len(neg)}
    if pos:
        out["false_no_match"] = {"mean": round(sum(r["best_score"] < floor for r in pos) / len(pos), 3), "n": len(pos)}
    po = paraphrase_overlap(rows)
    if po is not None:
        out["paraphrase_overlap"] = {"mean": round(po, 3)}
    lat = sorted(r["latency_s"] for r in rows)
    out["latency_median_s"] = {"mean": lat[len(lat) // 2]}
    return out


def floor_sweep(rows: list[dict]) -> list[dict]:
    """No-answer accuracy vs. wrongly refused questions for a range of floors (no rerun needed)."""
    neg = [r["best_score"] for r in rows if r.get("no_answer")]
    pos = [r["best_score"] for r in rows if not r.get("no_answer")]
    out = []
    for f in [round(0.76 + 0.01 * i, 2) for i in range(13)]:
        out.append({"floor": f, "no_answer_acc": round(sum(s < f for s in neg) / len(neg), 3) if neg else None,
                    "false_no_match": round(sum(s < f for s in pos) / len(pos), 3) if pos else None})
    return out


def run_bench(label: str, cfg: RankConfig, gold_path: Path = GOLD_FILE) -> dict:
    gold = load_gold(gold_path)
    ranker = Ranker(cfg)
    rows = []
    for q in gold:
        res = ranker.ask(q["query"], k=DEPTH)
        ranking = ranking_for(q, res)
        scored = score_question(q, ranking)
        rows.append({"qid": q["qid"], "query": q["query"], "intent": q.get("intent"), "section": q.get("section"),
                     "types": q.get("types"), "no_answer": q.get("no_answer", False), "status": q.get("status"),
                     "best_score": res["best_score"], "latency_s": res["latency_s"], **scored,
                     "top": [{k: r.get(k) for k in ("kind", "name", "role", "group", "url", "score", "keys",
                                                     "lead", "via", "evidence", "snippet")} for r in ranking[:DEPTH]]})
    meta = json.loads(embed.META_FILE.read_text(encoding="utf-8"))
    run = {"label": label, "created": datetime.now().isoformat(timespec="seconds"),
           "config": {**cfg.__dict__, "kinds": list(cfg.kinds), "model": meta["model"],
                      "index_chunks": meta["chunks"], "index_version": meta["index_version"]},
           "gold": {"file": str(gold_path), "questions": len(gold),
                    "draft": sum(1 for q in gold if q.get("status") == "draft")},
           "summary": summarize(rows, cfg.floor), "floor_sweep": floor_sweep(rows), "questions": rows}
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    (RUNS_DIR / f"{label}.json").write_text(json.dumps(run, indent=1, ensure_ascii=False), encoding="utf-8")
    write_report()
    return run


def print_summary(run: dict):
    s = run["summary"]
    print(f"\nRun '{run['label']}': {run['gold']['questions']} questions "
          f"({run['gold']['draft']} still draft), index {run['config']['index_chunks']} lines")
    for name, v in s.items():
        ci = f"  95% CI {v['ci95'][0]:.2f}-{v['ci95'][1]:.2f}" if "ci95" in v else ""
        print(f"  {name:20} {v['mean']:.3f}{ci}")
    print("\n  question                         best   result")
    for r in run["questions"]:
        if r["no_answer"]:
            verdict = "refused (correct)" if r["best_score"] < run["config"]["floor"] else "answered (should refuse)"
        else:
            verdict = "  ".join(f"{f['label'][:22]}@{f['rank'] or '-'}" for f in r["found"])
        print(f"  {r['qid'][:32]:32} {r['best_score']:.3f}  {verdict}")
    print(f"\nReport: {REPORT_FILE}")


# ---- HTML report ------------------------------------------------------------------------------

METRICS = [("hit@3", "Hit@3 (lead)"), ("recall@10", "Recall@10"), ("mrr", "MRR"), ("ndcg@10", "nDCG@10"),
           ("cand_recall@50", "Cand. recall@50"), ("no_answer_acc", "No-answer acc."),
           ("false_no_match", "False no-match"), ("paraphrase_overlap", "Paraphrase overlap")]


def _fmt(v):
    return "–" if v is None else f"{v:.2f}"


def write_report():
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in RUNS_DIR.glob("*.json")]
    runs.sort(key=lambda r: r["created"])
    if not runs:
        return
    latest = runs[-1]
    e = html.escape

    tiles = "".join(
        f"<div class='tile'><div class='tl'>{e(name)}</div><div class='tv'>{_fmt(latest['summary'].get(k, {}).get('mean'))}</div>"
        + (f"<div class='ts'>95% CI {_fmt(latest['summary'][k]['ci95'][0])}–{_fmt(latest['summary'][k]['ci95'][1])}</div>"
           if "ci95" in latest["summary"].get(k, {}) else "<div class='ts'>&nbsp;</div>") + "</div>"
        for k, name in METRICS)

    head = "".join(f"<th class='num'>{e(n)}</th>" for _, n in METRICS)
    run_rows = ""
    for r in reversed(runs):
        c = r["config"]
        what = f"{'+'.join(c['kinds'])}{', roll-up' if c['rollup'] else ''}{', lead +' + str(c['lead_boost']) if c['lead_boost'] else ''}, floor {c['floor']}"
        cells = "".join(f"<td class='num'>{_fmt(r['summary'].get(k, {}).get('mean'))}</td>" for k, _ in METRICS)
        run_rows += (f"<tr><td><b>{e(r['label'])}</b><div class='sub'>{e(r['created'].replace('T', ' '))}</div></td>"
                     f"<td>{e(what)}<div class='sub'>{c['index_chunks']} index lines</div></td>{cells}</tr>")

    sweep = "".join(f"<tr><td class='num'>{s['floor']:.2f}</td><td class='num'>{_fmt(s['no_answer_acc'])}</td>"
                    f"<td class='num'>{_fmt(s['false_no_match'])}</td></tr>" for s in latest["floor_sweep"])

    qhtml = ""
    for q in latest["questions"]:
        if q["no_answer"]:
            ok = q["best_score"] < latest["config"]["floor"]
            badge = f"<span class='pill {'ok' if ok else 'bad'}'>{'refused' if ok else 'answered'}</span>"
            exp = "<p class='sub'>No right answer exists; the system should refuse.</p>"
        else:
            m = q["metrics"]
            badge = " ".join(f"<span class='pill'>{k} {_fmt(v)}</span>" for k, v in m.items() if k != "cand_recall@50")
            exp = "<table class='exp'><tr><th>Expected</th><th class='num'>Grade</th><th class='num'>Rank</th><th>Why</th></tr>"
            for f in q["found"]:
                cls = "ok" if f["rank"] and f["rank"] <= 10 else ("warn" if f["rank"] else "bad")
                src = f" <a href='{e(f['source'])}'>source</a>" if f["source"] else ""
                exp += (f"<tr><td>{e(f['label'])}</td><td class='num'>{f['grade']}</td>"
                        f"<td class='num'><span class='pill {cls}'>{f['rank'] or 'not found'}</span></td>"
                        f"<td>{e(f['why'])}{src}</td></tr>")
            exp += "</table>"
        expected_keys = {k for f in q["found"] for k in f["keys"]}
        top = "<ol class='top'>"
        for r in q["top"][:10]:
            hit = " hit" if expected_keys & set(r["keys"]) else ""
            role = " · ".join(x for x in [r.get("role"), r.get("group")] if x)
            via = r.get("via") or {}
            via_txt = via.get("how", "")
            if via.get("url"):
                via_txt += f": <a href='{e(via['url'])}'>{e(via['url'][:70])}</a>"
            ev = "".join(f"<li><span class='sub'>{e(str(x.get('field')))}</span> “{e(str(x.get('quote'))[:120])}”</li>"
                         for x in (r.get("evidence") or [])[:3])
            snippet = f"<div class='sub'>{e((r.get('snippet') or '')[:200])}</div>" if r.get("snippet") else ""
            top += (f"<li class='res{hit}'><div><span class='score'>{r['score']:.3f}</span> "
                    f"<span class='kind'>{e(r['kind'])}</span> <a href='{e(r['url'])}'>{e(r['name'] or r['url'])}</a>"
                    f"{' <span class=pill>lead</span>' if r.get('lead') else ''}</div>"
                    f"<div class='sub'>{e(role)}</div><div class='sub'>{via_txt}</div>{snippet}"
                    + (f"<ul class='ev'>{ev}</ul>" if ev else "") + "</li>")
        top += "</ol>"
        draft = " <span class='pill warn'>draft</span>" if q.get("status") == "draft" else ""
        qhtml += (f"<details><summary><span class='qid'>{e(q['qid'])}</span> {e(q['query'])}{draft}"
                  f"<span class='right'>best {q['best_score']:.3f} {badge}</span></summary>"
                  f"<div class='qbody'>{exp}<h4>Top 10 returned</h4>{top}</div></details>")

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Retrieval Bench</title>
<style>
:root{{--bg:#fbfbfa;--fg:#1d1d1b;--muted:#6b6a66;--line:#e3e2de;--card:#fff;--ok:#1f7a4d;--okbg:#e3f3ea;
--bad:#b3261e;--badbg:#fbe6e4;--warn:#8a5a00;--warnbg:#fbf0d9;--accent:#2f5bd3;--hit:#eef3ff}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#161615;--fg:#ecebe7;--muted:#a3a29d;
--line:#2f2e2b;--card:#1e1e1c;--ok:#6fd19d;--okbg:#17321f;--bad:#f2867c;--badbg:#3a1916;--warn:#e6b85c;
--warnbg:#3a2c10;--accent:#8fb0ff;--hit:#1c2540}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:24px 16px 64px}}h1{{font-size:22px;margin:0 0 4px}}
h2{{font-size:16px;margin:32px 0 12px}}h4{{margin:16px 0 8px;font-size:13px}}a{{color:var(--accent)}}
.sub{{color:var(--muted);font-size:12px}}.tiles{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}}
.tile{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}}
.tl{{color:var(--muted);font-size:12px}}.tv{{font-size:26px;font-weight:600;font-variant-numeric:tabular-nums}}.ts{{color:var(--muted);font-size:11px}}
.scroll{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;background:var(--card)}}
th,td{{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}}th{{font-size:12px;color:var(--muted);font-weight:600}}
.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
details{{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:8px 0}}
summary{{cursor:pointer;padding:10px 14px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}}
.qid{{font-family:ui-monospace,Consolas,monospace;font-size:12px;color:var(--muted)}}.right{{margin-left:auto}}
.qbody{{padding:0 14px 14px}}.pill{{display:inline-block;border-radius:99px;padding:0 8px;font-size:12px;background:var(--line)}}
.pill.ok{{background:var(--okbg);color:var(--ok)}}.pill.bad{{background:var(--badbg);color:var(--bad)}}.pill.warn{{background:var(--warnbg);color:var(--warn)}}
ol.top{{padding-left:22px}}li.res{{padding:6px;border-radius:8px}}li.res.hit{{background:var(--hit)}}
.score{{font-variant-numeric:tabular-nums;font-weight:600}}.kind{{font-size:11px;color:var(--muted);text-transform:uppercase}}
ul.ev{{margin:4px 0 0;padding-left:18px;font-size:12px}}
</style></head><body><main>
<h1>Retrieval bench</h1>
<div class="sub">Latest run <b>{e(latest['label'])}</b> · {e(latest['created'].replace('T', ' '))} · {latest['gold']['questions']} gold questions ({latest['gold']['draft']} still draft) · model {e(latest['config']['model'])}</div>
<h2>Latest run</h2><div class="tiles">{tiles}</div>
<p class="sub">With {latest['gold']['questions']} questions, differences smaller than the 95% ranges are likely noise.</p>
<h2>Runs</h2><div class="scroll"><table><tr><th>Run</th><th>Setup</th>{head}</tr>{run_rows}</table></div>
<h2>No-answer floor (latest run)</h2>
<p class="sub">A query is refused when its best score is under the floor. Pick the floor that refuses the no-answer questions without refusing real ones.</p>
<div class="scroll"><table style="max-width:420px"><tr><th class="num">Floor</th><th class="num">No-answer refused</th><th class="num">Real questions refused</th></tr>{sweep}</table></div>
<h2>Per question (latest run)</h2>{qhtml}
</main></body></html>"""
    REPORT_FILE.write_text(page, encoding="utf-8")
