import sys
from pathlib import Path
from dataclasses import replace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap,check,run_module
bootstrap('aries-policy-evaluation')
from aries.workspace.policy_evaluation import Trial,compare


async def test_cheaper_failures_or_unverified_claims_do_not_qualify():
    failed=Trial('case',0,False,False,0,100,50,2,3,50.,None)
    for baseline in [failed,replace(failed,success=True)]:
        result=compare([baseline],[replace(baseline,tokens=80)],assigned=[('case',0)])
        check('savings without verified success refused',not result['admitted'])
        check('missing independent evidence explicitly reported',not result['verified_evidence_present'] and
              'no independently verified successful candidate outcome' in result['failure_reasons'])
    recovered=replace(failed,success=True,verified_success=True,tokens=80)
    check('real verified recovery can qualify',compare([failed],[recovered],assigned=[('case',0)])['admitted'])
    baseline=[replace(recovered,tokens=100),replace(failed,case_id='second')]
    candidate=[recovered,replace(failed,case_id='second',tokens=90)]
    result=compare(baseline,candidate,assigned=[('case',0),('second',0)])
    check('mixed trials retain failed attempts in denominator',result['candidate']['assigned']==2 and
          result['candidate']['verified_success']==1 and result['admitted'])


async def test_invalid_measurements_cannot_become_savings():
    base=Trial('case',0,True,True,0,100,50,2,3,50.,1.)
    for field,values in [('case_id',['',' ',None,False]),('seed',[False,0.,-1,'0']),
                         ('latency_ms',[None,False,'0',float('nan'),float('inf'),-1]),
                         ('cost_usd',[False,'0',float('nan'),float('inf'),-1])]:
        for value in values:
            try:replace(base,**{field:value});refused=False
            except ValueError:refused=True
            check('invalid '+field+' rejected: '+repr(value),refused)
    check('actual numeric zero remains valid',replace(base,cost_usd=0,latency_ms=0).cost_usd==0)
    check('unknown price is retained',replace(base,cost_usd=None).cost_usd is None)
    for assigned in [[('case',False)],[('',0)],['xy'],[('case',0,1)]]:
        try:compare([base],[base],assigned=assigned);refused=False
        except ValueError:refused=True
        check('malformed assignment cannot alias valid trial',refused)
    check('JSON array assignments supported',compare([base],[replace(base,tokens=80)],assigned=[['case',0]])['admitted'])


async def test_finite_rows_cannot_overflow_aggregate_admission():
    baseline=[Trial('case',seed,True,True,0,100,50,2,3,1e308,1e308) for seed in (0,1)]
    candidate=[replace(row,cost_usd=1.) for row in baseline]
    try:compare(baseline,candidate,assigned=[('case',0),('case',1)],metric='cost_usd');refused=False
    except ValueError:refused=True
    check('overflow cannot masquerade as infinite cost saved',refused)
    result=compare(baseline,[replace(row,tokens=80) for row in baseline],assigned=[('case',0),('case',1)])
    check('finite latency median does not overflow',result['baseline']['latency_median_ms']==1e308)


async def test_promotions_require_all_assigned_outcomes_and_quality():
    baseline=[Trial('case',0,True,True,0,100,50,2,3,50.,None)]
    better=[replace(baseline[0],tokens=80)]
    check('strict same-quality improvement admitted',compare(baseline,better,assigned=[('case',0)])['admitted'])
    for changed in [replace(better[0],success=False,verified_success=False),
                    replace(better[0],verified_success=False),replace(better[0],safety_violations=1),
                    replace(better[0],tokens=None),replace(better[0],tokens=100)]:
        check('quality safety unknown or null gain rejected',not compare(baseline,[changed],assigned=[('case',0)])['admitted'])
    check('unpriced is not free',not compare(baseline,better,assigned=[('case',0)],metric='cost_usd')['admitted'])
    try:compare(baseline,[],assigned=[('case',0)]);refused=False
    except ValueError:refused=True
    check('missing failed attempts cannot disappear from denominator',refused)
    try:compare(baseline,better*2,assigned=[('case',0)]);refused=False
    except ValueError:refused=True
    check('duplicate result rows refused',refused)


if __name__=='__main__':sys.exit(run_module(sys.modules[__name__]))
