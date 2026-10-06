import runpy,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import check,run_module
v=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/aries-endurance'))['verdict']
def test_verdict():
    samples=[{'timestamp':i*300,'services_ok':True,'automations':{'ok':True}} for i in range(289)]
    check('24 hours not completed early',v(samples[:2],0,300)['state']=='running')
    check('complete sampled coverage passes',v(samples,0,86400)['state']=='passed')
    check('sleep/gaps not masked as uptime',v(samples[:1]+samples[-1:],0,86400)['state']=='failed')
    check('missing final observation interval cannot pass',v(samples[:280],0,86400)['state']=='failed')
    future_samples=samples+[{'timestamp':86401,'services_ok':True,'automations':{'ok':True}}]
    check('future observations cannot count as completed coverage',v(future_samples,0,86400)['state']=='failed')
    reversed_samples=list(samples)
    reversed_samples[100],reversed_samples[101]=reversed_samples[101],reversed_samples[100]
    check('out-of-order clock evidence cannot pass',v(reversed_samples,0,86400)['state']=='failed')
    samples[4]['services_ok']=False
    check('observed failure prevents green result',v(samples,0,86400)['state']=='failed')
if __name__=='__main__':run_module(sys.modules[__name__])
