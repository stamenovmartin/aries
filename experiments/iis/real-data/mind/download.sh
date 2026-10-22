#!/usr/bin/env bash
# Fetch MIND-small (train + dev), verify SHA-256, unzip.
#
#   ./download.sh [DEST]        DEST defaults to ~/data-ext/mind
#
# Source: the Recommenders mirror on Hugging Face. The original Azure blob
# (mind201910small.blob.core.windows.net) is no longer publicly readable.
# License: Microsoft Research License Terms (research use only). The data is
# never committed to this repository.
# Citation: Wu et al., "MIND: A Large-scale Dataset for News Recommendation", ACL 2020.
set -euo pipefail

DEST="${1:-$HOME/data-ext/mind}"
BASE="https://huggingface.co/datasets/Recommenders/MIND/resolve/main"
declare -A SHA=(
  [MINDsmall_train.zip]=6ef97a271580b98ccfc4301ada55cc639423cb0576a78b8dcfcf74a4dbcc3194
  [MINDsmall_dev.zip]=d6ce515dcaa6b6d47ddf0a326eebc8a31b84735ae410285c9882ca2a06eec669
)
declare -A DIR=([MINDsmall_train.zip]=train [MINDsmall_dev.zip]=dev)

mkdir -p "$DEST"
for f in MINDsmall_train.zip MINDsmall_dev.zip; do
  if [[ ! -f "$DEST/$f" ]]; then
    echo "fetching $f"
    curl -fL --retry 3 -o "$DEST/$f.part" "$BASE/$f"
    mv "$DEST/$f.part" "$DEST/$f"
  fi
  got="$(sha256sum "$DEST/$f" | cut -d' ' -f1)"
  if [[ "$got" != "${SHA[$f]}" ]]; then
    echo "SHA-256 mismatch for $f: got $got, expected ${SHA[$f]}" >&2
    exit 1
  fi
  echo "ok  $f  $got"
  out="$DEST/${DIR[$f]}"
  if [[ ! -f "$out/behaviors.tsv" || ! -f "$out/news.tsv" ]]; then
    mkdir -p "$out"
    unzip -o -q "$DEST/$f" -d "$out"
  fi
done
echo "MIND-small ready in $DEST/{train,dev}"
