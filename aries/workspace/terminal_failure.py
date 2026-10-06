"""Stop an impossible single read without spending model calls repeating it."""
from aries import flags
from aries.workspace import contracts


def reason(data,step):
    if not flags.enabled('ARIES_TERMINAL_READ_FAILURE'):return None
    contract=data.get('agent',{}).get('contract',{})
    requirements=contract.get('requirements',[])
    if not contract.get('supported') or len(requirements)!=1:return None
    requirement=requirements[0]
    if requirement.get('capability')!='file.read' or not contracts.matches(requirement,step):return None
    error=step.get('error',{})
    if not (step.get('execution_status')=='failed' and step.get('started_at') and
            error.get('code')=='TARGET_NOT_FOUND' and error.get('error_type')=='FileNotFoundError' and
            error.get('retryable') is False):return None
    observation=next((e for e in data.get('evidence',[]) if e.get('evidence_id')==step.get('observation_ref')),None)
    if not observation or observation.get('source')!='file.read' or observation.get('step_id')!=step.get('step_id') \
            or observation.get('type')!='execution_error' or observation.get('verified') is not False \
            or observation.get('data')!=error:return None
    return 'The requested file was not found during the read attempt. No result was read or verified; repeated reads stopped.'
