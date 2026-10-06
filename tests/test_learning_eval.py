"""A paired comparison cannot silently promote a candidate or fabricate task success."""
import json,sys
from pathlib import Path
from unittest.mock import patch,AsyncMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap,check,reset_db,run_module
bootstrap('aries-learning-eval')
from agentic_core.database.base import async_session
from aries.settings import SettingsService
from aries.workspace import learning_eval,retrieval,reviews,service
from aries.workspace.models import WorkspaceGoal


def test_comparison_retains_every_case_and_known_limitation():
    r=learning_eval.compare()
    base=r['versions']['overlap-v1'];candidate=r['versions']['focused-v2']
    check('same 20 labelled inputs are evaluated for both versions',[c['id'] for c in base['cases']]==[c['id'] for c in candidate['cases']] and len(base['cases'])==20)
    check('generic Python no longer injects three unrelated histories',next(c for c in candidate['cases'] if c['id']=='generic-python')['selected']==[])
    check('useful statistics correction is still selected',next(c for c in candidate['cases'] if c['id']=='short-median')['selected']==['median'])
    check('remaining false positive is disclosed',next(c for c in candidate['cases'] if c['id']=='unrelated-summary')['passed'] is False)
    check('improvements have no hidden per-case regressions',r['improvements'] and not r['regressions'])
    check('fixture and implementation identities accompany results',len(r['fixture_sha256'])==64 and len(r['implementation_sha256'])==64)
    check('comparison never claims to promote a version',r['promoted'] is False)
    try:retrieval.rank([], 'query', 'unknown')
    except ValueError:check('unknown version is refused',True)
    else:check('unknown version is refused',False)


async def test_run_through_queue_is_read_only_and_durable():
    await reset_db()
    async with async_session() as db:
        await SettingsService(db).set('workspace.review_retrieval','overlap-v1',set_by='user')
        goal=await service.submit(db,request='proveri ucenje')
    with patch('aries.workspace.capabilities._mutate',AsyncMock(side_effect=AssertionError('No desktop writes'))) as mutate:
        await service.dispatch()
    async with async_session() as db:
        g=await db.get(WorkspaceGoal,goal['id'])
        result=json.loads(g.result_json)['steps'][0]['result']
        check('queued comparison completes and preserves case-level evidence',g.state=='done' and len(result['comparison']['versions']['focused-v2']['cases'])==20)
        check('comparison leaves active user setting unchanged',await SettingsService(db).get('workspace.review_retrieval')=='overlap-v1' and not mutate.called)
        check('read-only comparison reserves no desktop resource',not service.resources_for({'steps':[{'kind':'capability','capability':'learning_eval'}]}))


async def test_switch_and_rollback_control_actual_retrieval():
    await reset_db()
    async with async_session() as db:
        for id,request in [('median','Build Python median statistics'),('csv','Build Python CSV parser')]:
            db.add(WorkspaceGoal(id=id,request=request,state='done',result_json='{"steps":[],"cards":[]}'))
        await db.commit()
        await reviews.submit(db,'median','needs_work','Handle empty inputs')
        await reviews.submit(db,'csv','needs_work','Keep quoted commas')
        baseline=await reviews.relevant(db,'Build Python median statistics')
        await SettingsService(db).set('workspace.review_retrieval','focused-v2',set_by='user')
        candidate=await reviews.relevant(db,'Build Python median statistics')
        check('selected version changes real planner experience selection',len(baseline)==2 and len(candidate)==1 and candidate[0]['goal_id']=='median')
        check('retrieved experience identifies its producing version',candidate[0]['retrieval_version']=='focused-v2')
        await SettingsService(db).set('workspace.review_retrieval','overlap-v1',set_by='user')
        check('rollback restores baseline selection without editing histories',len(await reviews.relevant(db,'Build Python median statistics'))==2)

def test_paired_statistics_known_discordance():
    from aries.workspace.learning_eval import paired_statistics
    s = paired_statistics([False]*4 + [True]*16, [True]*20)
    check('four improvements have exact two-sided p of one eighth', s['exact_mcnemar_two_sided_p'] == .125 and s['accuracy_difference'] == .2)
    check('identical paired outcomes have p one', paired_statistics([True,False], [True,False])['exact_mcnemar_two_sided_p'] == 1.)
    check('balanced discordance has p one', paired_statistics([True,False], [False,True])['exact_mcnemar_two_sided_p'] == 1.)
    check('Wilson interval bounds contain the observed proportion', s['baseline_wilson_95'][0] < .8 < s['baseline_wilson_95'][1])

if __name__=='__main__':sys.exit(run_module(sys.modules[__name__]))
