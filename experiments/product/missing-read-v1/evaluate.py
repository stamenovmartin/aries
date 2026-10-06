"""Reuse the frozen finish-v1 file oracle; vary only terminal missing-read policy."""
import asyncio,importlib.util,json,os,tempfile
from pathlib import Path
from unittest.mock import patch
OUT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('file_fixture',OUT.parent/'finish-v1/evaluate.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)


async def main():
    before=fixture.hashes();rows=[]
    with tempfile.TemporaryDirectory(dir=Path.home(),prefix='aries-missing-read-eval-') as temp:
        for repeat in range(2):
            for case in ['single','compound','missing']:
                for enabled in ([False,True] if repeat==0 else [True,False]):
                    with patch.dict(os.environ,{'ARIES_TERMINAL_READ_FAILURE':str(int(enabled))}):
                        # Completion optimization ON in both arms: isolate this mechanism.
                        row=await fixture.trial(case,repeat,True,Path(temp))
                    row['arm']='terminal-read' if enabled else 'planner-retries';rows.append(row)
                    (OUT/'trials.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    arms={}
    for arm in ['planner-retries','terminal-read']:
        rs=[r for r in rows if r['arm']==arm]
        arms[arm]={'assigned':len(rs),'oracle_passed':sum(r['oracle_passed'] for r in rs),
            'positive_verified':sum(r['positive_verified'] for r in rs),
            'model_calls':sum(r['budget']['calls'] for r in rs),'tokens':sum(r['budget']['tokens'] for r in rs),
            'tool_verifier_calls':sum(r['budget']['tools'] for r in rs),
            'latency_ms':sum(r['latency_ms'] for r in rs),'cost_usd':None}
    failures=[r for r in rows if not r['oracle_passed']];stable=before==fixture.hashes()
    summary={'assigned':12,'completed':len(rows),'source_stable':stable,'source_hashes':before,'arms':arms,
        'failures':failures,'admitted':stable and not failures and arms['terminal-read']['tokens']<arms['planner-retries']['tokens'] and arms['terminal-read']['model_calls']<arms['planner-retries']['model_calls'],
        'scope':'Two paired repeats of three file fixtures; completion optimization enabled in both arms; no general success or cost claim'}
    (OUT/'evaluation.json').write_text(json.dumps(summary,indent=2));print(json.dumps({k:v for k,v in summary.items() if k!='source_hashes'}))
    if not summary['admitted']:raise SystemExit(1)


if __name__=='__main__':asyncio.run(main())
