#!/usr/bin/env bash
# Fetch LoCoMo (locomo10.json + LICENSE) and refuse it unless the SHA-256 matches.
#
#   Maharana et al., "Evaluating Very Long-Term Conversational Memory of LLM
#   Agents", ACL 2024. https://github.com/snap-research/locomo
#   Licence: CC BY-NC 4.0 (the LICENSE file is fetched beside the data).
#
# The data is never committed. Default destination: ~/data-ext/locomo
# Usage: download.sh [DEST_DIR]
set -euo pipefail

DEST="${1:-$HOME/data-ext/locomo}"
BASE="https://raw.githubusercontent.com/snap-research/locomo/main"
EXPECTED="79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"

mkdir -p "$DEST"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

curl -fsSL --retry 3 -o "$tmp/locomo10.json" "$BASE/data/locomo10.json"
curl -fsSL --retry 3 -o "$tmp/LICENSE" "$BASE/LICENSE"

actual="$(sha256sum "$tmp/locomo10.json" | cut -d' ' -f1)"
if [ "$actual" != "$EXPECTED" ]; then
  echo "SHA-256 mismatch for locomo10.json: expected $EXPECTED, got $actual" >&2
  echo "The upstream file changed; results would not be comparable. Nothing was written." >&2
  exit 1
fi

mv "$tmp/locomo10.json" "$DEST/locomo10.json"
mv "$tmp/LICENSE" "$DEST/LICENSE"
echo "OK  $DEST/locomo10.json  sha256=$actual"
