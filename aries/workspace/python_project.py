"""A fixed, inspectable first development workflow; no arbitrary code execution."""
import asyncio
import json
from pathlib import Path

SOURCE = 'import json\nprint(json.dumps({"message": "Hello from ARIES", "total": sum(range(1, 11))}))\n'
EXPECTED = {"message": "Hello from ARIES", "total": 55}


async def create(path):
    from aries.workspace.capabilities import command
    from aries.operator.tools import _detach
    path.mkdir(exist_ok=False)  # Never reuse, overwrite or execute an existing project.
    (path / "main.py").write_text(SOURCE)
    (path / "README.md").write_text(
        "# ARIES Python demo\n\nCreated by the bounded Python project workflow.\n"
        "Run: `.venv/bin/python -I main.py`\nExpected total: 55.\n")
    code, _, error = await command(["/usr/bin/python3", "-I", "-m", "venv", "--without-pip", str(path / ".venv")], timeout=45)
    if code:
        raise ValueError("Environment creation failed: " + error)
    # Isolated execution excludes Python environment variables and user site code.
    code, output, error = await command([str(path / ".venv/bin/python"), "-I", str(path / "main.py")], timeout=10)
    (path / "run-result.json").write_text(json.dumps({"returncode": code, "stdout": output, "stderr": error}))
    if code or json.loads(output) != EXPECTED:
        raise ValueError("The demo did not produce its expected result")
    ok, detail = await asyncio.to_thread(_detach, ["code", "--new-window", str(path), str(path / "main.py")])
    if not ok:
        raise ValueError("Project ran, but VS Code did not launch: " + detail)


async def verify(path):
    from aries.operator.desktop import observe
    try:
        source_ok = (path / "main.py").read_text() == SOURCE
        result = json.loads((path / "run-result.json").read_text())
        output_ok = result["returncode"] == 0 and json.loads(result["stdout"]) == EXPECTED
        env_ok = (path / ".venv/pyvenv.cfg").is_file() and (path / ".venv/bin/python").exists()
    except (OSError, ValueError, KeyError, TypeError):
        return False, "Project artifacts or execution output are missing or invalid"
    if not (source_ok and output_ok and env_ok):
        return False, "Project source, environment or execution output did not match"
    for _ in range(15):
        desktop = await asyncio.to_thread(observe)
        if any(path.name.casefold() in w.title.casefold() and
               "code" in (w.wm_class + " " + w.app_id).casefold() and not w.minimised
               for w in desktop.windows or []):
            return True, "Source and environment checked; recorded execution returned total 55. VS Code window names this project (circumstantial UI evidence)."
        await asyncio.sleep(0.4)
    return None, "Project files and recorded execution passed; the VS Code project window could not be confirmed"
