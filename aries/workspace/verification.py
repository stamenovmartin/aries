"""Record evidence separately from executor completion. Never infer it from done."""
from copy import deepcopy


def record_failure(step, exc, *, phase, elapsed_seconds):
    """Persist a failure without inventing a verifier or absence of side effects."""
    code = getattr(exc, 'code', None)
    if not isinstance(code, str):
        code = ('TARGET_NOT_FOUND' if isinstance(exc, FileNotFoundError) else
                'PERMISSION_DENIED' if isinstance(exc, PermissionError) else
                'INVALID_ARGUMENT' if isinstance(exc, ValueError) else 'CAPABILITY_ERROR')
    error = {'code': code, 'error_type': type(exc).__name__,
             'phase': phase, 'message': str(exc)[:300]}
    step.update(state='failed', error=error,
                execution_status='not_run' if phase == 'prepare' else 'failed')
    step['result'] = {
        'state': 'failed', 'summary': str(exc)[:300], 'error': deepcopy(error),
        'elapsed_seconds': round(elapsed_seconds, 3),
        'verification': {
            'met': None,
            'evidence': ('Preparation rejected the request before the executor was called.'
                         if phase == 'prepare' else
                         'Execution raised an error; resulting state has not been independently verified.')},
    }
    record(step)


def record(step, result=None):
    result = result if isinstance(result, dict) else step.get('result', {})
    result = result if isinstance(result, dict) else {}
    verdict = result.get('verification') or step.get('verification')
    if not isinstance(verdict, dict):
        operator = result.get('operator', result)
        if isinstance(operator, dict) and operator.get('verified_success') is True:
            verdict = {'met': True, 'type': 'operator_verdict',
                       'evidence': 'Independent operator verdict preserved; see operator step evidence'}
        else:
            verdict = {'met': None, 'unverifiable': True,
                       'evidence': 'No independent verifier established this result; execution is not confirmation'}
    verdict = deepcopy(verdict)
    met = verdict.get('met')
    # Invalid truthy values cannot become verified. A missing/non-boolean verdict
    # is unknown, not a failed observation and certainly not success.
    if met is not True and met is not False:
        verdict.update(met=None, unverifiable=True)
    state = step.get('state', result.get('state'))
    if state in {'held', 'proposed', 'queued', 'running', 'pending'}:
        status = 'pending'
    elif state in {'failed', 'interrupted', 'cancelled'}:
        status = 'interrupted' if state != 'failed' else 'not_run'
    else:
        status = 'verified' if met is True else 'verification_failed' if met is False else 'unverifiable'
    step['verification'] = verdict
    step['verification_status'] = status
    if status == 'verification_failed' and state in {'done', 'verified'}:
        step['state'] = 'unconfirmed'
        if result:
            result['state'] = 'unconfirmed'
            result['summary'] = 'Independent verification did not confirm this result'
    return verdict
