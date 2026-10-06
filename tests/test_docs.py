"""The generated documentation has to match the code, or it is worse than absent.

`docs/CAPABILITIES.md` was hand-maintained and went stale the way hand-maintained
lists do: on 2026-09-30 the registry held 58 capabilities and the table listed
about twenty, missing every `screen.*`, `network.*`, `display.*`, `input.*` and
`system.service*` entry added that day. A reader trusts a documentation file, so a
wrong one costs more than none.

`./scripts/aries-capability-docs` generates it now. This test is what makes that
worth anything — a generator nobody runs is exactly as stale as the file it was
meant to replace. The suite runs it in `--check` mode, so adding a capability
without regenerating the table fails here rather than months later in someone's
reading.

The second test does not trust the script: it reads the registry and the file
independently and compares the sets. If the generator ever silently drops a row,
`--check` would still pass, because it compares the file to its own output.
"""
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, run_module
bootstrap('aries-docs')

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs' / 'CAPABILITIES.md'


async def test_the_capability_table_matches_the_registry():
    out = subprocess.run([str(ROOT / 'scripts' / 'aries-capability-docs'), '--check'],
                         capture_output=True, text=True, timeout=180, cwd=str(ROOT))
    detail = (out.stdout + out.stderr).strip().splitlines()
    check('docs/CAPABILITIES.md is current: ' + (detail[-1] if detail else 'no output'),
          out.returncode == 0)


async def test_every_registered_capability_is_in_the_file():
    """Read both sides independently, because --check only compares the file to
    the generator's own output — a generator that dropped a row would agree with
    itself forever."""
    from aries.workspace.registry import registry
    text = DOC.read_text()
    missing = sorted(name for name in registry._items if f'`{name}`' not in text)
    check('every capability appears in the table: ' + (', '.join(missing) or 'all present'), not missing)
    check('the table is not empty', text.count('\n| `') > 20)


async def test_the_generated_block_is_fenced_so_the_prose_survives():
    """The reasoning around the table is written by hand and is not derivable
    from anything, so the generator must only ever replace what is between the
    markers."""
    text = DOC.read_text()
    check('the start marker is present', '<!-- generated: ./scripts/aries-capability-docs -->' in text)
    check('the end marker is present', '<!-- end generated -->' in text)
    tail = text.split('<!-- end generated -->', 1)[1]
    check('hand-written prose still follows the table', 'Extending the registry' in tail)


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
