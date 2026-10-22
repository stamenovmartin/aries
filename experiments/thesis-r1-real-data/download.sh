#!/usr/bin/env bash
# R1 datasets (docs/preregistration/R1-real-data-benchmarks.md). Never committed; fetched here and SHA-256 checked.
set -euo pipefail
D="${1:-$HOME/data-ext}"
mkdir -p "$D/nl2bash" "$D/clinc150"
curl -sSL -o "$D/nl2bash/all.nl" https://raw.githubusercontent.com/TellinaTool/nl2bash/master/data/bash/all.nl
curl -sSL -o "$D/nl2bash/all.cm" https://raw.githubusercontent.com/TellinaTool/nl2bash/master/data/bash/all.cm
curl -sSL -o "$D/clinc150/data_full.json" https://raw.githubusercontent.com/clinc/oos-eval/master/data/data_full.json
cd "$D" && sha256sum -c - <<'SUMS'
1db0c529c350b463919624550b8f5882a97c42ad5051c7d49fbc496bc4e8b770  nl2bash/all.nl
3a72eaced7fa14a0938354cefc42b2dcafb2d47297102f1279086e18c3abe57e  nl2bash/all.cm
36923c3705a59e08fe9c3883d8bc2dd966ef93e22cb78ac41171782a698d56e0  clinc150/data_full.json
SUMS
