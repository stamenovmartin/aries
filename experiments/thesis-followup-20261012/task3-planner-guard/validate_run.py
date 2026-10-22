#!/usr/bin/env python3
"""Independent read-only recalculation of a completed offline planner run.

Follow-up copy of experiments/thesis-final-20261006/planner/validate_run.py; checks and
recomputation unchanged, paths redirected to the follow-up source archive and dry run (here: the guard dry run 20261012T193014.755446Z)."""
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
import argparse,hashlib,json,os,sqlite3,sys
BASE=Path(__file__).resolve().parent; PACKAGE=BASE.parent; ORIGINAL=BASE.parents[1]/'thesis-final-20261006'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def digest(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('run',type=Path);ap.add_argument('--source-root',type=Path,required=True);a=ap.parse_args();run=a.run.resolve();manifest=read(run/'run-manifest.json');summary=read(run/'summary.json');fixture=read(BASE/'fixture.json')['cases'];labels={r['id']:r for r in fixture};protocol=read(BASE/'protocol.json');rows=[json.loads(l) for l in (run/'attempts.jsonl').read_text().splitlines()]
 assert run.is_relative_to(BASE/'runs')
 os.environ['DATABASE_URL']='sqlite+aiosqlite:///:memory:';os.environ['APP_ENV']='test';os.environ['ARIES_FLAG_FILE']=str(run/'flags.env');sys.dont_write_bytecode=True
 source=a.source_root.resolve();sys.path[:0]=[str(source),str(source/'vendor'),str(source/'vendor/agentic-core')]
 from aries.workspace.agent_planner import parse
 checks=[]
 def check(n,v):checks.append({'name':n,'passed':bool(v)})
 check('complete_run_and_summary',manifest['complete'] and summary['complete'])
 check('all72_unique_prespecified_slots',len(rows)==72 and {(r['repetition'],r['case_id']) for r in rows}=={(rep,i) for rep in [1,2,3] for i in labels})
 check('order_matches_preregistered_schedule',[[r['case_id'] for r in rows if r['repetition']==rep] for rep in [1,2,3]]==read(run/'order.json'))
 check('goal_expected_pairs_match_frozen_fixture',all(r['goal']==labels[r['case_id']]['goal'] and r['expected']==labels[r['case_id']]['expected'] and r['language']==labels[r['case_id']]['language'] and r['category']==labels[r['case_id']]['category'] for r in rows))
 check('protocol_and_fixture_identical_to_frozen',all(sha(BASE/n)==sha(ORIGINAL/'planner'/n) for n in ['protocol.json','fixture.json']))
 check('run_copies_match_frozen_inputs',all(sha(run/n)==sha(BASE/n) for n in ['fixture.json','protocol.json','run_planner.py']))
 check('manifest_input_hashes_match',manifest['fixture_sha256']==sha(BASE/'fixture.json') and manifest['protocol_sha256']==sha(BASE/'protocol.json') and manifest['runner_sha256']==sha(BASE/'run_planner.py'))
 check('attempt_and_summary_hashes_match_manifest',sha(run/'attempts.jsonl')==manifest['attempts_sha256'] and sha(run/'summary.json')==manifest['summary_sha256'])
 check('followup_source_files_unchanged',all(sha(source/n)==h for n,h in read(BASE/'source-manifest.json')['files'].items()))
 check('model_matches_router_before_and_after',manifest['model_metadata']['digest']==manifest['model_after']['digest']==manifest['expected_model_digest']==read(ORIGINAL/'protocol.json')['model']['digest'])
 check('all_run_integrity_flags_true',all(summary['integrity'][k] for k in ['rows_complete','source_stable','model_stable','model_before_matches_router']))
 check('all_preflight_checks_passed',all(manifest['checks'].values()))
 check('full58_registry_and_no_topk_snapshot',len(manifest['registry'])==58 and not manifest['flags']['flags']['ARIES_CAP_TOPK']['on'] and not manifest['flags']['flags']['ARIES_STATE_SNAPSHOT']['on'])
 prompts={i:read(run/'prompts'/f'{i}.json') for i in labels}
 check('all72_recorded_prompt_hashes_match',all(r['prompt_sha256']==digest(prompts[r['case_id']]) for r in rows))
 original=BASE/'runs/20261012T193014.755446Z/prompts'
 check('all24_prompts_byte_identical_to_followup_pre_inference_dryrun',all((run/'prompts'/f'{i}.json').read_bytes()==(original/f'{i}.json').read_bytes() for i in labels))
 calculated=[];failures=[];stored_match=True
 for r in rows:
  expected=labels[r['case_id']]['expected'];scores={'schema_valid':False,'capability_correct':False,'capability_arguments_correct':False};decision=None
  if r.get('raw_output') is not None:
   try:decision=parse(r['raw_output']).model_dump()
   except Exception:decision=None
  if decision is not None:
   scores['schema_valid']=True;scores['capability_correct']=decision['action']==expected['action'] and decision['capability']==expected['capability'];scores['capability_arguments_correct']=scores['capability_correct'] and decision['arguments']==expected['arguments']
  stored_match &= decision==r['decision'] and scores==r['scores']
  calculated.append({**r,'scores':scores})
  if not scores['capability_arguments_correct']:
   failures.append({'case_id':r['case_id'],'repetition':r['repetition'],'goal':r['goal'],'expected':expected,'actual':None if decision is None else {k:decision[k] for k in ['action','capability','arguments']},'error':r['error']})
 check('raw_decisions_reparse_and_scores_recompute_identically',stored_match)
 totals={k:sum(r['scores'][k] for r in calculated) for k in ['schema_valid','capability_correct','capability_arguments_correct']}
 check('overall_counts_match_independent_recalculation',all(summary['overall'][k]=={'correct':v,'denominator':72} for k,v in totals.items()))
 check('each_repetition_has_fixed24_denominator',all(summary['per_repetition'][str(rep)][k]=={'correct':sum(r['scores'][k] for r in calculated if r['repetition']==rep),'denominator':24} for rep in [1,2,3] for k in totals))
 consistent=sum(len({digest({k:r['decision'][k] for k in ['action','capability','arguments']}) for r in calculated if r['case_id']==i and r['decision'] is not None})==1 and all(r['decision'] is not None for r in calculated if r['case_id']==i) for i in labels)
 check('consistency_count_recomputed',consistent==summary['all_three_identical_valid_cases'])
 with sqlite3.connect('file:'+str(run/'planner.sqlite3')+'?mode=ro',uri=True) as db:
  events=[{'kind':k,**json.loads(v)} for k,v in db.execute('SELECT kind,data_json FROM aries_intelligence_events')]
  goals=db.execute('SELECT COUNT(*) FROM aries_workspace_goals').fetchone()[0]
  routes=db.execute('SELECT COUNT(*) FROM aries_routing_cache').fetchone()[0]
 generations=[r for r in events if r['kind']=='generation']
 check('72_actual_recorded_local_generations',len(generations)==72 and all(r['level']=='local' and r['model']=='qwen2.5:7b' and r['task_type']=='workspace.m14-planner' for r in generations))
 check('no_workspace_goals_or_router_cache_written',goals==0 and routes==0)
 check('successful_usage_has_local_model_identity',all(r['usage']['native']['provider']=='ollama' and r['usage']['native']['model']=='qwen2.5:7b' and r['usage']['native']['execution_level']=='local' for r in rows if 'usage' in r))
 result={'verified_at':datetime.now(timezone.utc).isoformat(),'mode':'independent read-only recomputation from actual raw outputs and scratch DB','checks':checks,'passed':sum(c['passed'] for c in checks),'total':len(checks),'independent_counts':totals,'denominator':72,'unique_cases':24,'repetitions':3,'identical_valid_cases':consistent,'generation_count':len(generations),'generation_success_count':sum(bool(r.get('ok')) for r in generations),'workspace_goals':goals,'routing_cache_entries':routes,'failures':failures,'run_manifest_sha256':sha(run/'run-manifest.json'),'summary_sha256':sha(run/'summary.json'),'attempts_sha256':sha(run/'attempts.jsonl'),'validation_script_sha256':sha(__file__),'measurement_limit':'Offline exact next-action selection; no capability execution or actual task completion.'}
 (run/'independent-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'passed':result['passed'],'total':result['total'],'counts':totals,'consistency':consistent,'failed_checks':[c['name'] for c in checks if not c['passed']]},indent=2))
 if not all(c['passed'] for c in checks):raise SystemExit(1)
 final={'status':'complete','verified_at':result['verified_at'],'window_id':manifest['window_id'],'run_directory':str(run.relative_to(PACKAGE)),'summary_path':str((run/'summary.json').relative_to(PACKAGE)),'run_manifest_path':str((run/'run-manifest.json').relative_to(PACKAGE)),'independent_validation_path':str((run/'independent-validation.json').relative_to(PACKAGE)),'checks':{'passed':result['passed'],'total':result['total']},'sha256':{'summary':sha(run/'summary.json'),'run_manifest':sha(run/'run-manifest.json'),'independent_validation':sha(run/'independent-validation.json')},'counts':totals,'denominator':72,'unique_cases':24,'repetitions':3}
 (BASE/'final-run.json').write_text(json.dumps(final,ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':main()
