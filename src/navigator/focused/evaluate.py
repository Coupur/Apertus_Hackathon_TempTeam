"""Evaluate local selection rules on the labeled synthetic rubric examples."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .. import config
from .models import Document
from .selection import RULESET_VERSION, evaluate, validate_findings


def metrics(rows: list[dict]) -> dict:
    tp = sum(r["expected"] and r["accepted"] for r in rows)
    fp = sum(not r["expected"] and r["accepted"] for r in rows)
    fn = sum(r["expected"] and not r["accepted"] for r in rows)
    precision = tp / (tp + fp) if tp + fp else None
    return {"true_positives": tp, "false_positives": fp, "false_negatives": fn,
            "precision": precision, "recall": tp / (tp + fn) if tp + fn else None,
            "target_met": precision is not None and precision >= 0.9 and not any(r.get("error") for r in rows)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=config.ROOT / "bench" / "focused_examples.json")
    parser.add_argument("--out", type=Path, default=config.DATA_DIR / "focused-evaluation.json")
    args = parser.parse_args()
    examples = json.loads(args.fixtures.read_text(encoding="utf-8"))["examples"]
    rows = []
    for example in examples:
        doc = Document("https://example.invalid/" + example["id"], example["title"], example["text"],
                       example["id"].split("-")[0], example["organization"], datetime.now(timezone.utc).isoformat())
        row = {"id": example["id"], "expected": example["accept"], "accepted": False}
        try:
            records, rejected = validate_findings(evaluate(doc), doc)
            row.update(accepted=bool(records), findings=records, rejected=dict(rejected))
            if rejected.get("invalid_response") or rejected.get("invalid_candidate"):
                row["error"] = "invalid_selection_output"
        except Exception as error:
            row["error"] = type(error).__name__
        rows.append(row)
        print(f"{example['id']}: expected={row['expected']} accepted={row['accepted']}", flush=True)
    result = {"dataset": "manually labeled synthetic examples, not live institutional facts",
              "classification_unit": "example document",
              "selection_method": "rules", "ruleset_version": RULESET_VERSION,
              **metrics(rows), "examples": rows}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "examples"}, indent=2))
    raise SystemExit(0 if result["target_met"] else 1)


if __name__ == "__main__":
    main()
