"""Real queue persistence distinguishes policy rejection from execution failure."""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests import test_workspace as harness
from tests._bootstrap import check, run_module
from aries.workspace import capabilities
from aries.workspace.verification import record_failure
from aries.sources.safety import SourceRejected


async def test_preparation_rejection_is_persisted():
    await harness.setup()
    for path, code in [('/etc/shadow', 'PROTECTED_PATH'),
                       ('/proc/1/environ', 'PROTECTED_PATH'),
                       ('~/.ssh/id_rsa', 'PATH_EXCLUDED'),
                       ('relative.txt', 'INVALID_ARGUMENT')]:
        executor = AsyncMock(side_effect=AssertionError('Executor must not be reached'))
        with patch.object(capabilities, 'execute', executor):
            goal = await harness.run('read file ' + path)
        step = goal['steps'][0]
        check('executor not called: ' + path, executor.await_count == 0)
        check('durable typed preparation error: ' + path,
              goal['state'] == 'failed' and step['state'] == 'failed'
              and step['error']['code'] == code and step['error']['phase'] == 'prepare')
        check('no verifier invented: ' + path,
              step['verification']['met'] is None
              and step['verification_status'] == 'not_run'
              and step['execution_status'] == 'not_run')


async def test_execution_error_does_not_claim_no_side_effects():
    await harness.setup()
    executor = AsyncMock(side_effect=RuntimeError('Error after a possible side effect'))
    with patch.object(capabilities, 'execute', executor):
        goal = await harness.run('read file ~/Documents/example.txt')
    step = goal['steps'][0]
    check('executor was reached', executor.await_count == 1)
    check('execution phase recorded', step['error']['phase'] == 'execute')
    check('unknown resulting state, not a verified refusal',
          step['verification']['met'] is None and step['error']['code'] == 'CAPABILITY_ERROR')
    check('no false assertion that nothing executed',
          'not been independently verified' in step['verification']['evidence'])


def test_missing_file_is_not_policy_rejection():
    for exc, code in [(FileNotFoundError('absent'), 'TARGET_NOT_FOUND'),
                      (SourceRejected('malformed path'), 'INVALID_ARGUMENT')]:
        step = {}
        record_failure(step, exc, phase='execute', elapsed_seconds=0)
        check('missing/malformed is distinct: ' + code, step['error']['code'] == code)


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
