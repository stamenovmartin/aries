"""Run native analytics assertions on the GTK interpreter."""
import subprocess
import sys
from pathlib import Path

if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    sys.exit(subprocess.run(['/usr/bin/python3', str(root / 'tests/ui_analytics.py')], cwd=root).returncode)
