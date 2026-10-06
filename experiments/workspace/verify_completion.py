"""Live public-site, generated-code, concurrency and GUI-control acceptance.

Approval is restricted to this run's public search field and disposable GTK
button. No user files are overwritten, no installation or deletion is performed.
"""
import json
import subprocess
import time
from pathlib import Path
from experiments.workspace.live_evaluate import api

OUT=Path(__file__).resolve().parent
RUN=time.strftime('%Y%m%d-%H%M%S')
REPORT={'run':RUN,'goals':[],'checks':[]}

def save():
    (OUT/('acceptance-'+RUN+'.json')).write_text(json.dumps(REPORT,indent=2))

def submit(kind,args):
    row=api('POST','/workspace',{'capability':kind,'args':args})
    REPORT['goals'].append({'capability':kind,'id':row['id']})
    save()
    return row['id']

def wait(goal_id,seconds=600):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        goal=next(g for g in api('GET','/workspace?goal_id='+goal_id)['goals'] if g['id']==goal_id)
        if goal['state'] not in ('queued','running'):
            next(row for row in REPORT['goals'] if row['id']==goal_id)['result']=goal
            save()
            print(goal['state'],goal['request'][:90],flush=True)
            return goal
        time.sleep(.5)
    raise TimeoutError(goal_id)

def check(name,condition):
    REPORT['checks'].append({'name':name,'passed':bool(condition)})
    save()
    print(('PASS ' if condition else 'FAIL ')+name,flush=True)


def main():
    root=Path.home()/'Documents'/('ARIES-Verified-'+RUN)
    REPORT['project']=str(root)
    build=submit('build_python',{'path':str(root),'task':'Implement mean(numbers) and median(numbers) functions. Empty lists raise ValueError. Tests cover odd and even lengths, negatives, and empty lists. Add a __main__ demonstration printing both results for [1,2,3,4].'})
    browse=submit('browser_open',{'url':'https://www.python.org'})
    process=submit('processes',{})
    quick=wait(process)
    check('independent process observation completes',quick['state']=='done')
    build_now=next(g for g in api('GET','/workspace?goal_id='+build)['goals'] if g['id']==build)
    check('independent work is not blocked by code generation',build_now['state'] in ('queued','running'))
    page=wait(browse)
    check('real Python website DOM is verified',page['state']=='done')
    if page['state']=='done':
        state=page['steps'][0]['result']['browser'];session=state['session']
        check('rendered browser title and canonical URL are present',state['title']=='Welcome to Python.org' and state['url']=='https://www.python.org/')
        fill=submit('browser_fill',{'session':session,'label':'Search This Site','value':'asyncio'})
        proposal=wait(fill)
        check('field entry is bound to reviewed page',proposal['state']=='proposed' and proposal['steps'][0]['args']['expected_url']=='https://www.python.org/')
        if proposal['state']=='proposed':
            api('POST','/workspace/'+fill+'/approve',{})
            filled=wait(fill)
            check('field input is independently read back',filled['state']=='done' and filled['steps'][0]['result']['browser'].get('field_verified')=='Search This Site')
        followed=wait(submit('browser_follow',{'session':session,'label':'Documentation'}))
        check('named link reaches the real documentation destination',followed['state']=='done' and followed['steps'][0]['result']['browser']['url'].startswith('https://www.python.org/doc'))
        closed=wait(submit('browser_close',{'session':session}))
        check('owned browser session closes',closed['state']=='done')
    generated=wait(build)
    check('local model generates a tested Python project',generated['state']=='done')
    if generated['state']=='done':
        record=generated['steps'][0]['result']['coding']
        check('model usage is measured',bool(record['attempts'][-1].get('model_usage',{}).get('eval_count')))
        # Independent task-specific oracle, separate from generated tests. Run
        # generated source only inside the same OS isolation boundary.
        oracle=root/'acceptance-oracle'
        oracle.mkdir()
        (oracle/'main.py').write_bytes((root/'main.py').read_bytes())
        (oracle/'test_oracle.py').write_text('import unittest, main\nclass Oracle(unittest.TestCase):\n def test_mean(self): self.assertEqual(main.mean([1,2,3,4]),2.5)\n def test_median(self): self.assertEqual(main.median([4,1,3,2]),2.5)\n def test_negative(self): self.assertEqual(main.mean([-3,-1]),-2)\n def test_odd(self): self.assertEqual(main.median([9,1,3]),3)\n def test_empty(self):\n  with self.assertRaises(ValueError): main.mean([])\n  with self.assertRaises(ValueError): main.median([])\n')
        import asyncio
        from aries.workspace.coding import sandbox
        result=asyncio.run(sandbox(oracle));REPORT['independent_code_oracle']=result
        check('generated code passes five independently authored acceptance cases',result['returncode']==0)
    unit='aries-gui-acceptance-'+RUN
    subprocess.run(['systemd-run','--user','--collect','--quiet','--unit='+unit,'--','/usr/bin/python3',str(OUT/'gui_acceptance.py')],check=True)
    try:
        time.sleep(1)
        inspected=wait(submit('inspect_app',{'app':'aries-gui-check'}))
        nodes=inspected['steps'][0]['result'].get('observation',{}).get('nodes',[])
        target=next((n for n in nodes if n['name']=='Complete acceptance check' and 'click' in n.get('actions',[])),None)
        check('real GTK control and action are discoverable',target is not None)
        if target:
            goal=submit('ui_action',{'app':'aries-gui-check','node':target['node'],'action':'click','expected':'Acceptance complete'})
            proposed=wait(goal)
            check('GUI action freezes the exact observed control',proposed['state']=='proposed')
            if proposed['state']=='proposed':
                api('POST','/workspace/'+goal+'/approve',{})
                result=wait(goal)
                check('GUI action produces independently observed changed text',result['state']=='done')
    finally:
        subprocess.run(['systemctl','--user','stop',unit],check=False)
    agent=wait(submit('agent_task',{'task':'Open https://www.python.org, follow the Documentation link, and report the final page title.'}))
    check('agent plans multiple actions using live browser evidence',agent['state']=='done' and len(agent['steps'])>=2 and any('/doc' in s.get('result',{}).get('browser',{}).get('url','') for s in agent['steps']))
    evaluated=wait(submit('evaluation',{}))
    check('evaluation report is available through the goal UI',evaluated['state']=='done')
    save()
    print('REPORT',str(OUT/('acceptance-'+RUN+'.json')),flush=True)
    if any(not item['passed'] for item in REPORT['checks']):
        raise SystemExit(1)


if __name__=='__main__':
    main()
