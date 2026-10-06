"""Generate a small standard-library Python project and test it in isolation."""
import asyncio
import ast
import hashlib
import json
import os
import signal
import time
import uuid
from pathlib import Path


async def sandbox(project, *, timeout=15):
    """No home, network, credentials, desktop bus or writable project mount."""
    runner = ("import sys, unittest; sys.path.insert(0, '/work'); "
              "s=unittest.defaultTestLoader.discover('/work', pattern='test_*.py'); "
              "n=s.countTestCases(); r=unittest.TextTestRunner(verbosity=2).run(s); "
              "sys.exit(0 if n > 0 and r.wasSuccessful() else 1)")
    argv = ["/usr/bin/prlimit", "--cpu=8", "--as=536870912", "--fsize=1048576", "--nofile=64", "--",
            "/usr/bin/bwrap", "--unshare-all", "--die-with-parent", "--new-session",
            "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib", "--ro-bind", "/lib64", "/lib64",
            "--ro-bind", str(project), "/work", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
            "--chdir", "/work", "--clearenv", "--setenv", "HOME", "/tmp", "--setenv", "PATH", "/usr/bin:/bin",
            "/usr/bin/python3", "-I", "-B", "-c", runner]
    unit = None
    if os.environ.get('INVOCATION_ID'):
        unit = 'aries-code-' + uuid.uuid4().hex[:12]
        argv = ['systemd-run', '--user', '--collect', '--quiet', '--wait', '--pipe', '--unit='+unit,
                '--property=RuntimeMaxSec=20', '--property=MemoryMax=768M', '--property=TasksMax=32', '--', *argv]
    started = time.monotonic()
    proc = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT, start_new_session=True)
    output = bytearray()
    try:
        async with asyncio.timeout(timeout):
            while chunk := await proc.stdout.read(4096):
                output.extend(chunk)
                if len(output) > 64000:
                    raise ValueError("Sandbox output exceeded 64 KB")
            await proc.wait()
    except BaseException:
        if unit:
            stopper = await asyncio.create_subprocess_exec('systemctl','--user','stop',unit,
                        stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
            try:
                await asyncio.wait_for(stopper.wait(), 3)
            except asyncio.TimeoutError:
                stopper.kill()
                await stopper.wait()
        if proc.returncode is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        await proc.wait()
        raise
    return {"returncode": proc.returncode, "output": output.decode(errors='replace'),
            "elapsed_seconds": round(time.monotonic()-started, 3), "isolation": "bubblewrap: no network or home; read-only project"}


async def generate(db, request, feedback=''):
    from aries import intelligence
    from aries.operator.plan import _provider_is_local
    from agentic_core.llm import providers
    from agentic_core.llm.structured import extract_json
    await intelligence.arm(db)
    if not _provider_is_local()[0] or not providers.available():
        raise ValueError("A configured local model is required for project generation")
    schema = {'type':'object','properties':{
              'title':{'type':'string'},
              'code':{'type':'string','description':'The complete Python implementation source code, including all function bodies. Never a filename.', 'minLength':40},
              'tests':{'type':'string','description':'The complete Python unittest source code, including imports, a TestCase class and test_ method bodies. Never a filename.', 'minLength':100},
              'explanation':{'type':'string'}},
              'required':['title','code','tests','explanation'],'additionalProperties':False}
    from aries.settings import SettingsService
    routing=None
    if await SettingsService(db).get('intelligence.router_enabled'):
        from aries.intelligence.router import route
        cache=db.info.setdefault('aries_coding_routes',{})
        key=hashlib.sha256(request.encode()).hexdigest()
        if key not in cache:cache[key]=(await route(db,request)).model_dump()
        routing=cache[key]
    response, usage = await intelligence.structured(db, [
        {"role": "system", "content": "Implement the user's Python task fully using only the standard library. Return JSON with title, code, tests, explanation. The code field MUST contain the COMPLETE IMPLEMENTATION as a string with newlines and function bodies, NOT a filename or description. The tests field MUST contain COMPLETE EXECUTABLE PYTHON SOURCE: import unittest, import main, a unittest.TestCase subclass, and at least two def test_ methods with assertions. Include an edge case. Your code field will be saved verbatim to main.py and tests to test_main.py. No input() at import time, no GUI, no network, no subprocess, no dependency installation. Code runs without access to the user's home. Do not claim successful execution; the runner will test it. If feedback is supplied, repair the implementation/tests while preserving the request."},
        {"role": "user", "content": json.dumps({"request": request, "previous_test_feedback": feedback[:6000]})}],
        schema, purpose="workspace.coding", route=routing)
    result = extract_json(response)
    if not isinstance(result, dict):
        raise ValueError("Model did not return a project object")
    result['usage'] = usage
    for field in ('code', 'tests'):
        if not isinstance(result.get(field), str) or not 1 <= len(result[field]) <= 20000:
            raise ValueError("Generated source must be between 1 and 20,000 characters")
        source = result[field].strip()
        if source.startswith(('```python\n', '```py\n', '```\n')) and source.endswith('```'):
            source = source.split('\n', 1)[1].rsplit('```', 1)[0].strip() + '\n'
        result[field] = source
        ast.parse(result[field])
    if not any(isinstance(n, ast.FunctionDef) and n.name.startswith('test_') for n in ast.walk(ast.parse(result['tests']))):
        raise ValueError("The model did not supply executable test cases")
    return result


async def build(db, path, request, *, goal_id=None):
    from aries.operator.tools import _detach
    from aries.workspace.service import progress
    path.mkdir(exist_ok=False)
    attempts, feedback, candidate = [], '', None
    for index in range(1, 3):
        await progress(goal_id, f'Generating Python project · attempt {index}/2')
        candidate = await generate(db, request, feedback)
        directory = path / ('attempt-' + str(index))
        directory.mkdir()
        (directory/'main.py').write_text(candidate['code'])
        (directory/'test_main.py').write_text(candidate['tests'])
        await progress(goal_id, f'Running generated tests in the OS sandbox · attempt {index}/2')
        report = await sandbox(directory)
        attempts.append({"attempt": index, **report, "model_usage": candidate.get('usage', {})})
        (path/'evaluation.json').write_text(json.dumps({"request": request, "attempts": attempts}, indent=2))
        if report['returncode'] == 0:
            break
        feedback = json.dumps({"code": candidate['code'], "tests": candidate['tests'], "output": report['output']})
    if not attempts or attempts[-1]['returncode'] != 0:
        raise ValueError("Generated tests still fail after two attempts; source and diagnostics were retained in " + str(path))
    for name, field in [('main.py', 'code'), ('test_main.py', 'tests')]:
        (path/name).write_text(candidate[field])
    (path/'README.md').write_text('# '+str(candidate.get('title','Python project'))[:200]+'\n\n'+request+'\n\n'+str(candidate.get('explanation',''))[:4000]+
        '\n\nValidation: generated unittest cases passed in an isolated environment. These tests are generated by the same model and do not independently prove full task correctness.\n')
    # Accessibility is scoped to this newly generated project, not global settings.
    (path/'.vscode').mkdir()
    (path/'.vscode/settings.json').write_text('{"editor.accessibilitySupport":"on"}\n')
    hashes = {name: hashlib.sha256((path/name).read_bytes()).hexdigest() for name in ('main.py','test_main.py')}
    record = {"request": request, "attempts": attempts, "source_sha256": hashes}
    (path/'evaluation.json').write_text(json.dumps(record, indent=2))
    await progress(goal_id, 'Generated tests passed · opening the project in VS Code')
    ok, detail = await asyncio.to_thread(_detach, ['code', '--new-window', str(path), str(path/'main.py')])
    record['editor_launch_accepted'] = ok
    if not ok:
        record['editor_error'] = detail
    return record


async def verify(path):
    record = json.loads((path/'evaluation.json').read_text())
    for name in ('main.py','test_main.py'):
        if hashlib.sha256((path/name).read_bytes()).hexdigest() != record['source_sha256'][name]:
            return False, "Generated files changed after the recorded run"
    if record['attempts'][-1]['returncode'] != 0:
        return False, "The generated test suite failed"
    return True, "Generated files match the tested source; generated unittest suite passed in the OS sandbox. This is not independent proof of complete task correctness."


async def editor_visible(path):
    from aries.operator.desktop import observe
    for _ in range(15):
        desktop = await asyncio.to_thread(observe)
        if any(path.name.casefold() in w.title.casefold() and
               'code' in (w.wm_class+' '+w.app_id).casefold() and not w.minimised
               for w in desktop.windows or []):
            return True
        await asyncio.sleep(.4)
    return False
