"""Run the live Apertus evidence checker on frozen positive and negative controls."""
import argparse
import hashlib
import json
from pathlib import Path

from .. import config
from .cli import write_json
from .crawl import now
from .report_contract import verify_claims


def run(paths: list[Path]) -> dict:
    cases, fixtures = [], []
    for path in paths:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        checksum = path.with_suffix('.sha256')
        if checksum.exists() and checksum.read_text(encoding='utf-8').strip() != digest:
            raise ValueError('Frozen entailment fixture checksum mismatch')
        fixture = json.loads(path.read_text(encoding='utf-8'))
        fixtures.append({'path':str(path),'sha256':digest,'annotation_method':fixture['annotation_method']})
        cases.extend(fixture['cases'])
    if len({c['id'] for c in cases}) != len(cases):
        raise ValueError('Control IDs must be unique')
    rows=[]
    for case in cases:
        decision=verify_claims([{**case,'claim_id':case['id']}])[0]
        rows.append({**case,'decision':decision.model_dump(),'correct':decision.supported==case['expected']})
        print(f"{case['id']}: {'pass' if rows[-1]['correct'] else 'FAIL'}",flush=True)
    return {'checked_at':now(),'model':config.REPORT_LLM_NAME,'method':'apertus-entailment-v2',
            'fixtures':fixtures,'total':len(rows),'correct':sum(r['correct'] for r in rows),
            'false_positive_ids':[r['id'] for r in rows if r['decision']['supported'] and not r['expected']],
            'false_negative_ids':[r['id'] for r in rows if not r['decision']['supported'] and r['expected']],
            'passed':all(r['correct'] for r in rows),'cases':rows,
            'limitations':['Agent-labelled development controls, not independent human validation.',
                           'A passing sample does not guarantee the correctness of future model judgments.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures',type=Path,action='append')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    fixtures=args.fixtures or [config.ROOT/'bench/report_entailment_control.json',
                               config.ROOT/'bench/report_attribution_regressions.json',
                               config.ROOT/'bench/report_composite_regressions.json',
                               config.ROOT/'bench/report_entailment_scope.json',
                               config.ROOT/'bench/report_capability_regressions.json']
    if args.out.resolve() in {p.resolve() for p in fixtures}:
        parser.error('Output must not replace control fixtures')
    report=run(fixtures)
    write_json(args.out,report)
    print(json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=False,indent=2))
    if not report['passed']:
        raise SystemExit(1)


if __name__=='__main__': main()
