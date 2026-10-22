#!/bin/sh
# Points git at the versioned hooks in scripts/hooks/ for this clone.
set -e
cd "$(dirname "$0")/.."
git config core.hooksPath scripts/hooks
echo "hooks installed: core.hooksPath=scripts/hooks"
