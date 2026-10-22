#!/usr/bin/env python3
"""Fixed-denominator analysis. Refuse partial runs and changed frozen evidence."""
import hashlib, json, random, statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE=Path(__file__).resolve().parent
HOLD={'ASK','OUT_OF_SCOPE','UNKNOWN'}
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def metric(k,n):return {'k':k,'n':n,'pct':100*k/n if n else None}
def valid(r):return not r.get('error') and r.get('source')!='fallback' and bool(r.get('intent'))
def act(r):return r.get('intent') not in HOLD
def contract_action(r):return r.get('intent')=='UNKNOWN' and r.get('tool')=='workspace' and r.get('source')=='rule'
def correct(r,sensitivity=False):
    return bool(valid(r) and ((act(r) or (sensitivity and contract_action(r)))==(r['klass']=='actionable')))
def pair_correct(r,annotation,native=False):
    pairs=annotation['native_semantic_pairs' if native else 'allowed_pairs']
    return bool(valid(r) and {'intent':r.get('intent'),'tool':r.get('tool')} in pairs)

def score(rows,labels):
    explicit=[r for r in rows if valid(r) and r['intent'] in {'ASK','OUT_OF_SCOPE'}]
    holds=[r for r in rows if r['klass']!='actionable']
    actionable=[r for r in rows if r['klass']=='actionable']
    ood=[r for r in rows if r['klass']=='out_of_scope']
    coarse=[r for r in rows if labels[r['id']]['semantic_scorable']]
    native=[r for r in rows if labels[r['id']]['native_semantic_scorable']]
    return {'n':len(rows),'binary':metric(sum(correct(r) for r in rows),len(rows)),
      'dispatch_sensitivity':metric(sum(correct(r,True) for r in rows),len(rows)),
      'semantic_coarse':metric(sum(pair_correct(r,labels[r['id']]) for r in coarse),len(coarse)),
      'semantic_native':metric(sum(pair_correct(r,labels[r['id']],True) for r in native),len(native)),
      'abstention_precision':metric(sum(r['klass']!='actionable' for r in explicit),len(explicit)),
      'abstention_recall':metric(sum(valid(r) and r['intent'] in {'ASK','OUT_OF_SCOPE'} for r in holds),len(holds)),
      'false_holds':metric(sum(valid(r) and r['intent'] in HOLD for r in actionable),len(actionable)),
      'ood_out_of_scope':metric(sum(valid(r) and r['intent']=='OUT_OF_SCOPE' for r in ood),len(ood)),
      'ood_false_action':metric(sum(valid(r) and act(r) for r in ood),len(ood)),
      'ood_errors':sum(not valid(r) for r in ood),
      'unknown':sum(valid(r) and r['intent']=='UNKNOWN' for r in rows),
      'contract_unknown_workspace':sum(valid(r) and contract_action(r) for r in rows),
      'errors':sum(not valid(r) for r in rows),'source_counts':dict(Counter(r.get('source','error') for r in rows)),
      'intent_counts':dict(Counter(r.get('intent','error') for r in rows)),
      'seconds_total':sum(r['seconds'] for r in rows),
      'local_latency_median':statistics.median([r['seconds'] for r in rows if r.get('source')=='local']) if any(r.get('source')=='local' for r in rows) else None}

def main():
    protocol=read(HERE/'protocol.json'); labels={r['id']:r for r in read(HERE/'semantic_labels.json')['rows']}
    status=read(HERE/'run-status.json'); assert status['status']=='complete'
    checks={}
    expected={'fixture':'fixture.jsonl','semantic_labels':'semantic_labels.json','source_manifest':'source-manifest.json','runner':'run_router.py'}
    for k,p in expected.items():checks[k+'_sha256']=sha(HERE/p)==protocol['hashes'][k]
    for a in ('A0','A1','A2','A3'):checks['prompt_'+a]=sha(HERE/'prompts'/f'{a}.txt')==protocol['hashes'][a]
    checks['protocol_unchanged']=sha(HERE/'protocol.json')==status['protocol_sha256']
    checks['frozen_sources']=all(sha(HERE/'frozen'/p)==h for p,h in read(HERE/'source-manifest.json')['files'].items())
    import urllib.request
    tags=json.load(urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=20))
    after=next(m for m in tags['models'] if m['name']=='qwen2.5:7b')
    checks['model_digest_unchanged']=after['digest']==protocol['model']['digest']
    arms={};all_rows=[];by_arm={}
    for arm in ('A0','A1','A2','A3'):
        pooled=[];reps=[]
        for rep in range(1,4):
            rows=[json.loads(l) for l in (HERE/'raw'/f'r{rep}-{arm}.jsonl').read_text().splitlines()]
            assert len(rows)==225 and {r['id'] for r in rows}==set(labels)
            assert all(r['rep']==rep and r['arm']==arm and r['utterance']==labels[r['id']]['utterance'] and r['klass']==labels[r['id']]['klass'] for r in rows)
            reps.append({'rep':rep,**score(rows,labels)});pooled+=rows
        by_arm[arm]=pooled;all_rows+=pooled
        summary=score(pooled,labels)
        summary.update(repetitions=reps, binary_mean_pct=statistics.mean(r['binary']['pct'] for r in reps),
          binary_min_pct=min(r['binary']['pct'] for r in reps),binary_max_pct=max(r['binary']['pct'] for r in reps),
          by_class={c:score([r for r in pooled if r['klass']==c],labels) for c in ('actionable','ambiguous','out_of_scope','unsafe')},
          by_language={l:score([r for r in pooled if r['lang']==l],labels) for l in sorted({r['lang'] for r in pooled})},
          local_only=score([r for r in pooled if r.get('source')=='local'],labels),
          local_only_note='Diagnostic on valid local outputs; infrastructure failures excluded here only. Use model_path for fixed-denominator model-attempt scores.',
          model_path=score([r for r in pooled if r.get('source')!='rule'],labels),
          rule_only=score([r for r in pooled if r.get('source')=='rule'],labels))
        arms[arm]=summary
    checks['all_2700_rows']=len(all_rows)==2700
    paths={a:{(r['rep'],r['id']):'rule' if r.get('source')=='rule' else 'model' for r in rows} for a,rows in by_arm.items()}
    checks['identical_rule_model_partition']=all(paths[a]==paths['A0'] for a in paths)
    checks['stable_rule_model_partition_across_repetitions']=all(
      paths[a][(rep,i)]==paths[a][(1,i)] for a in paths for rep in (2,3) for i in labels)
    # Paired, case-cluster bootstrap: each case contributes its mean of 3 observations.
    rates={a:{i:statistics.mean(correct(r) for r in rows if r['id']==i) for i in labels} for a,rows in by_arm.items()}
    differences=[rates['A3'][i]-rates['A1'][i] for i in labels]
    rng=random.Random(61006);samples=sorted(100*statistics.mean(rng.choices(differences,k=225)) for _ in range(2000))
    paired={'comparison':'A3-A1','mean_difference_pp':100*statistics.mean(differences),
      'case_bootstrap_95_interval_pp':[samples[49],samples[1949]],'bootstrap_samples':2000,'independent_units':225,
      'case_mean_improved':sum(d>0 for d in differences),'case_mean_worse':sum(d<0 for d in differences),
      'case_mean_equal':sum(d==0 for d in differences),
      'note':'Descriptive interval conditional on reused author fixture; not population generalization or independent n=675.'}
    criterion={
      'binary_improves':arms['A3']['binary']['pct']>arms['A1']['binary']['pct'],
      'native_semantic_noninferiority_2pp':arms['A3']['semantic_native']['pct']>=arms['A1']['semantic_native']['pct']-2,
      'ood_false_action_decreases':arms['A3']['ood_false_action']['pct']<arms['A1']['ood_false_action']['pct']}
    criterion['all_met']=all(criterion.values())
    case_details=[]
    for i,l in labels.items():
        case_details.append({'id':i,'utterance':l['utterance'],'klass':l['klass'],'label_notes':l.get('notes'),
          'binary_mean_by_arm':{a:rates[a][i] for a in rates},
          'predictions':{a:[{k:r.get(k) for k in ('rep','intent','tool','confidence','source','reason','error')} for r in rows if r['id']==i] for a,rows in by_arm.items()}})
    result={'generated_at':datetime.now(timezone.utc).isoformat(),'status':'complete','experiment':'ARIES-FINAL-20261006',
      'protocol_sha256':sha(HERE/'protocol.json'),'observations':2700,'unique_cases':225,'repetitions':3,
      'checks':checks,'arms':arms,'paired':paired,'predeclared_criterion':criterion,'model_after':after,
      'raw_sha256':{f.name:sha(f) for f in sorted((HERE/'raw').glob('*.jsonl'))},
      'annotation_denominators':{'binary':225,'semantic_coarse':82,'semantic_native':56},
      'metric_note':'Pooled counts combine three observations per case; sample size remains225. UNKNOWN nonaction is intent proxy; contract fast-path sensitivity reported separately.'}
    assert all(checks.values()),checks
    (HERE/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    (HERE/'case-analysis.json').write_text(json.dumps(case_details,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'arms':{a:{k:v[k] for k in ('binary','semantic_coarse','semantic_native','errors')} for a,v in arms.items()},'paired':paired,'criterion':criterion},indent=2))

if __name__=='__main__':main()
