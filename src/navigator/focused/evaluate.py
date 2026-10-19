"""Offline classification and ranking diagnostics on labeled synthetic examples."""
import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .. import config
from .models import Document
from .ranking import RANKING_VERSION, rank, ranking_summary
from .selection import RULESET_VERSION, evaluate, validate_findings


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def wilson(successes, total):
    if not total:
        return None
    p, z = successes / total, 1.959963984540054
    center = p + z * z / (2 * total)
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    denominator = 1 + z * z / total
    return [max(0, (center - margin) / denominator), min(1, (center + margin) / denominator)]


def metrics(rows: list[dict]) -> dict:
    tp = sum(r["expected"] and r["accepted"] for r in rows)
    fp = sum(not r["expected"] and r["accepted"] for r in rows)
    fn = sum(r["expected"] and not r["accepted"] for r in rows)
    tn = sum(not r["expected"] and not r["accepted"] for r in rows)
    precision, recall = ratio(tp, tp + fp), ratio(tp, tp + fn)
    specificity = ratio(tn, tn + fp)
    mcc_denominator = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    return {"examples_count": len(rows), "true_positives": tp, "false_positives": fp,
            "false_negatives": fn, "true_negatives": tn,
            "precision": precision, "recall": recall, "f1": ratio(2 * tp, 2 * tp + fp + fn),
            "specificity": specificity, "false_positive_rate": ratio(fp, fp + tn),
            "accuracy": ratio(tp + tn, len(rows)),
            "balanced_accuracy": (recall + specificity) / 2 if recall is not None and specificity is not None else None,
            "matthews_correlation": ratio(tp * tn - fp * fn, mcc_denominator),
            "precision_interval_95": wilson(tp, tp + fp), "recall_interval_95": wilson(tp, tp + fn),
            "false_positive_ids": [r.get("id") for r in rows if r["accepted"] and not r["expected"]],
            "false_negative_ids": [r.get("id") for r in rows if not r["accepted"] and r["expected"]],
            "error_count": sum(bool(r.get("error")) for r in rows),
            "target_met": (precision is not None and precision >= .9 and recall is not None and recall >= .9
                           and specificity is not None and specificity >= .9 and not any(r.get("error") for r in rows))}


def ranking_metrics(rows: list[dict], legacy: bool = False) -> dict:
    """Compare only explicitly labeled priority groups; missing results rank last."""
    groups = defaultdict(list)
    for row in rows:
        if "relevance" in row:
            groups[row["ranking_group"]].append(row)

    def score(row):
        if not row.get("findings"):
            return (-1,)
        if legacy:
            return max((max(r["scores"].values()), sum(r["scores"].values())) for r in row["findings"])
        return max(rank(r)[:-1] for r in row["findings"])

    correct = tied = comparisons = 0
    positive_correct = positive_comparisons = 0
    ndcg, precision_at = defaultdict(list), defaultdict(list)
    mistakes = []
    for group, members in groups.items():
        for better in members:
            for worse in members:
                if better["relevance"] <= worse["relevance"]:
                    continue
                comparisons += 1
                a, b = score(better), score(worse)
                correct += a > b
                tied += a == b
                if worse["relevance"] > 0:
                    positive_comparisons += 1
                    positive_correct += a > b
                if a <= b:
                    mistakes.append({"group": group, "preferred": better["id"], "other": worse["id"],
                                     "result": "tie" if a == b else "reversed"})
        predicted = sorted((r for r in members if r.get("findings")), key=lambda r: (score(r), r["id"]), reverse=True)
        # Expected gain under all permutations of a tie, never fixture-ID order.
        gain_groups = defaultdict(list)
        for row in predicted:
            gain_groups[score(row)].append(2 ** row["relevance"] - 1)
        gains = [sum(values) / len(values) for values in gain_groups.values() for _ in values]
        ideal = sorted((r["relevance"] for r in members), reverse=True)
        for k in (3, 5, 10):
            actual_dcg = sum(gain / math.log2(i + 2) for i, gain in enumerate(gains[:k]))
            ideal_dcg = sum((2 ** grade - 1) / math.log2(i + 2) for i, grade in enumerate(ideal[:k]))
            if ideal_dcg:
                ndcg[k].append(actual_dcg / ideal_dcg)
            if predicted:
                precision_at[k].append(sum(r["expected"] for r in predicted[:k]) / min(k, len(predicted)))
    return {"groups": len(groups), "comparable_pairs": comparisons,
            "pairwise_accuracy": ratio(correct, comparisons), "pairwise_tie_rate": ratio(tied, comparisons),
            "positive_pairs": positive_comparisons,
            "positive_pairwise_accuracy": ratio(positive_correct, positive_comparisons),
            "ndcg_at": {str(k): sum(v) / len(v) for k, v in ndcg.items()},
            "precision_at_available_k": {str(k): sum(v) / len(v) for k, v in precision_at.items()},
            "ranking_errors": mistakes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=config.ROOT / "bench" / "focused_examples.json")
    parser.add_argument("--ranking-fixtures", type=Path, default=config.ROOT / "bench" / "focused_ranking_examples.json")
    parser.add_argument("--out", type=Path, default=config.DATA_DIR / "focused-evaluation.json")
    args = parser.parse_args()
    rows = []
    for path in (args.fixtures, args.ranking_fixtures):
        for example in json.loads(path.read_text(encoding="utf-8"))["examples"]:
            doc = Document("https://example.invalid/" + example["id"], example["title"], example["text"],
                           example["id"].split("-")[0], example["organization"], datetime.now(timezone.utc).isoformat())
            row = {"id": example["id"], "expected": example["accept"], "accepted": False,
                   "organization": example["organization"], "language": example.get("language", "en"),
                   "dataset": path.name}
            for key in ("relevance", "ranking_group", "label_reason"):
                if key in example:
                    row[key] = example[key]
            try:
                records, rejected = validate_findings(evaluate(doc), doc)
                row.update(accepted=bool(records), findings=records, rejected=dict(rejected))
                if rejected.get("invalid_response") or rejected.get("invalid_candidate"):
                    row["error"] = "invalid_selection_output"
            except Exception as error:
                row["error"] = type(error).__name__
            rows.append(row)
    breakdown = {}
    for field in ("organization", "language", "dataset"):
        breakdown[field] = {value: metrics([r for r in rows if r[field] == value])
                            for value in sorted({r[field] for r in rows})}
    ranking = ranking_metrics(rows)
    ranking_ok = ranking["positive_pairwise_accuracy"] is not None and ranking["positive_pairwise_accuracy"] >= .8
    result = {"dataset": "authored synthetic development cases; not a held-out or live-quality estimate",
              "classification_unit": "example document", "selection_method": "rules",
              "ruleset_version": RULESET_VERSION, "ranking_version": RANKING_VERSION,
              **metrics(rows), "breakdown": breakdown, "ranking": ranking,
              "legacy_ranking_on_same_candidates": ranking_metrics(rows, legacy=True),
              "evidence_diagnostics": ranking_summary([f for r in rows for f in r.get("findings", [])]),
              "ranking_target_met": ranking_ok, "examples": rows}
    result["target_met"] = result["target_met"] and ranking_ok
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("examples", "breakdown")}, indent=2))
    raise SystemExit(0 if result["target_met"] else 1)


if __name__ == "__main__":
    main()
