"""Execute real isolated code, including escape/timeout and repair evidence checks."""
import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, run_module
bootstrap('aries-coding')
from aries.workspace import coding


async def test_real_sandbox_isolation_and_timeout():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root/'test_isolation.py').write_text('import unittest, pathlib, socket\nclass TestIsolation(unittest.TestCase):\n def test_no_home(self): self.assertFalse(pathlib.Path("/home/stamenovmartin").exists())\n def test_readonly(self):\n  with self.assertRaises(OSError): pathlib.Path("/work/changed").write_text("no")\n def test_no_net(self):\n  with self.assertRaises(OSError): socket.create_connection(("1.1.1.1",443),timeout=1)\n')
        result = await coding.sandbox(root)
        check('OS sandbox prevents home access, network and project mutation', result['returncode'] == 0 and 'Ran 3 tests' in result['output'])
        (root/'test_isolation.py').write_text('import time\ntime.sleep(30)\n')
        try:
            await coding.sandbox(root, timeout=0.2)
        except asyncio.TimeoutError:
            check('unresponsive generated code is terminated', True)
        else:
            check('unresponsive generated code is terminated', False)


async def test_failed_candidate_is_repaired_and_both_attempts_retained():
    tests = 'import unittest, main\nclass TestMath(unittest.TestCase):\n def test_add(self): self.assertEqual(main.add(2,3),5)\n def test_negative(self): self.assertEqual(main.add(-2,2),0)\n'
    candidates = [{'code': 'def add(a,b): return a-b\n', 'tests': tests},
                  {'code': 'def add(a,b): return a+b\n', 'tests': tests}]
    with tempfile.TemporaryDirectory() as tmp, patch.object(coding, 'generate', AsyncMock(side_effect=candidates)) as generator, patch('aries.operator.tools._detach', return_value=(True,'')):
        root = Path(tmp)/'project'
        result = await coding.build(None, root, 'Add two numbers')
        check('real failing test triggers one bounded repair', len(result['attempts']) == 2 and result['attempts'][0]['returncode'] != 0 and result['attempts'][1]['returncode'] == 0)
        check('failure evidence feeds the repair request', 'AssertionError' in generator.call_args.args[2])
        check('both source candidates are retained', (root/'attempt-1/main.py').exists() and (root/'attempt-2/main.py').exists())
        check('verifier accepts unchanged tested source', (await coding.verify(root))[0])
        (root/'main.py').write_text('changed')
        check('verifier refuses changed source', not (await coding.verify(root))[0])


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
