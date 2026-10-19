"""Evaluate frozen real candidates: extraction and ranking are separate metrics."""
import argparse
import hashlib
import json
from collections import Counter
from itertools import combinations
from pathlib import Path

from .. import config
from ..extract import chunk
from .cli import write_json
from .crawl import consolidate, now
from .entities import extract_entities
from .models import Document
from .privacy import clean_text
from .ranking import evaluation_for
from .selection import evaluate, validate_findings, identity_text
from .store import identity_keys


def classify(document: Document) -> list[dict]:
    from dataclasses import replace
    records=[]
    for text in chunk(document.text[:36000],size=12000,overlap=500):
        piece=replace(document,text=text)
        accepted,_=validate_findings(evaluate(piece),piece)
        records.extend(accepted)
    works=consolidate(records)
    for w in works:
        keys=identity_keys(w)
        w["id"]=hashlib.sha256(min(keys or {document.url+":"+w["original_name"]}).encode()).hexdigest()[:24]
    return works+extract_entities(document,works)


def pair_metrics(rows, mode="all", positive_only=False):
    correct=ties=wrong=0
    for a,b in combinations(rows,2):
        if a["preferred_grade"]==b["preferred_grade"]: continue
        if mode=="within" and a["type"]!=b["type"]: continue
        if mode=="between" and a["type"]==b["type"]: continue
        if positive_only and not (a["expected_accept"] and b["expected_accept"]): continue
        better,worse=(a,b) if a["preferred_grade"]>b["preferred_grade"] else (b,a)
        diff=better["selection_score"]-worse["selection_score"]
        correct+=diff>0
        ties+=diff==0
        wrong+=diff<0
    total=correct+ties+wrong
    return dict(pairs=total,correct=correct,ties=ties,reversed=wrong,
                strict_accuracy=correct/total if total else None,
                tie_adjusted_accuracy=(correct+ties/2)/total if total else None)


def extraction_metrics(rows):
    counts=Counter((bool(r['expected_accept']),bool(r['predicted_accept'])) for r in rows)
    tp,fp,fn,tn=counts[True,True],counts[False,True],counts[True,False],counts[False,False]
    return dict(tp=tp,fp=fp,fn=fn,tn=tn,precision=tp/(tp+fp) if tp+fp else None,
                recall=tp/(tp+fn) if tp+fn else None,
                false_positive_ids=[r['id'] for r in rows if r['predicted_accept'] and not r['expected_accept']],
                false_negative_ids=[r['id'] for r in rows if r['expected_accept'] and not r['predicted_accept']])


def run(path: Path) -> dict:
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    checksum=path.with_suffix('.sha256')
    if checksum.exists() and checksum.read_text().strip()!=digest:
        raise ValueError('Frozen control-set checksum mismatch')
    dataset=json.loads(path.read_text(encoding='utf-8'))
    rows=[]
    for case in dataset['cases']:
        doc=Document(**case['document'])
        doc.text=clean_text(doc.text)
        records=classify(doc)
        target=identity_text(case['name'])
        matches=[r for r in records if
                 (case['type']=='work' and r['type'] not in ('expert','team')) or
                 (r['type']==case['type'] and (identity_text(r['original_name'])==target or
                  case['type']=='team' and target in identity_text(r['original_name'])))]
        scored=[(evaluation_for(r),r) for r in matches]
        quality,record=max(scored,key=lambda item:item[0]['score']) if scored else (None,None)
        rows.append({k:case[k] for k in ('id','type','name','expected_accept','preferred_grade','reason','evidence')} |
                    dict(predicted_accept=bool(matches),selection_score=quality['score'] if quality else 0,
                         evaluation=quality,predicted_name=record['original_name'] if record else None))
    return dict(version='unified-control-evaluation-v1',evaluated_at=now(),
                labels_sha256=digest,annotated_at=dataset['annotated_at'],
                annotation_method=dataset['annotation_method'],
                limitations=['60 source-reviewed real candidates are a development control set, not independent human validation.',
                             'Ordinal preference labels are coarse; ties are reported and not counted as strict success.',
                             'Cross-type agreement measures this sample; it does not establish universal comparability.',
                             'Missed candidates are assigned zero for end-to-end ranking; extraction is reported separately.'],
                counts=dict(Counter(r['type'] for r in rows)), extraction=extraction_metrics(rows),
                extraction_by_type={t:extraction_metrics([r for r in rows if r['type']==t]) for t in ('expert','team','work')},
                ranking={mode:pair_metrics(rows,mode) for mode in ('within','between','all')},
                positive_ranking={mode:pair_metrics(rows,mode,True) for mode in ('within','between','all')},
                ranking_by_type={t:pair_metrics([r for r in rows if r['type']==t]) for t in ('expert','team','work')},
                cases=rows)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fixtures',type=Path,default=config.ROOT/'bench/unified_control60.json')
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    if a.out.resolve()==a.fixtures.resolve(): p.error('Output must not replace frozen labels')
    report=run(a.fixtures)
    write_json(a.out,report)
    print(json.dumps({k:v for k,v in report.items() if k!='cases'},indent=2,ensure_ascii=False))


if __name__=='__main__': main()
