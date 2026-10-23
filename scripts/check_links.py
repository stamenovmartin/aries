#!/usr/bin/env python3
"""Every relative link in the repository's Markdown files points to a file or folder that exists in git.

    scripts/check_links.py      prints each broken link; exit 1 if there is one
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINK = re.compile(r'\]\(([^)#\s]+)(#[^)]*)?\)')


def main():
    os.chdir(ROOT)
    files = [f for f in subprocess.run(['git', 'ls-files'], capture_output=True, text=True,
                                       check=True).stdout.splitlines() if os.path.lexists(f)]
    known = set(files)
    for f in files:
        parts = f.split('/')
        known.update('/'.join(parts[:i]) for i in range(1, len(parts)))
    broken = 0
    for f in files:
        if not f.endswith('.md') or f.startswith('vendor/'):
            continue
        with open(f, encoding='utf-8', errors='ignore') as fh:
            text = fh.read()
        for m in LINK.finditer(text):
            url = m.group(1)
            if url.startswith(('http://', 'https://', 'mailto:')):
                continue
            target = os.path.normpath(os.path.join(os.path.dirname(f), url)).rstrip('/')
            if target not in known:
                print(f'{f}: {url}')
                broken += 1
    print(f'{broken} broken links', file=sys.stderr)
    return 1 if broken else 0


if __name__ == '__main__':
    sys.exit(main())
