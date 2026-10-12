# Verifier count: 57 of 58 executed (the "56 of 58" is stale)

## How the count was established (2026-10-12)

- **Recounted mechanically** from the per-capability entries of
  `experiments/product/independent-acceptance/raw/review_verifier_integrity.json`
  (sha256 `9c03a14e831a993b34d8ccb699ab1c065b94d77770d7b46c8f8c99551e5d924c`).
  - 58 entries.
  - `evidence_kind`: **57 `executed`, 1 `source`**. The source-only entry is `desktop.launch`, which needs a live DB,
    the operator arm and a compositor.
  - `verifier_class`: INDEPENDENT 35, TRIVIAL 12, SELF_REPORT 10, PLANNER_SUPPLIED 1. This equals the published table.
- **Not re-executed.** The repository has no script that re-runs the 58 verifier executions.
  `verification_truth.py` and `verification/build_facts.py` only *read* this raw file. A fresh execution of
  all 58 verifiers would have to be written as a new harness, and would then be a new measurement.
- **Where the 56 comes from.** The free-text `method` string in the same raw file says "56 of 58 were
  EXECUTED". Its own per-entry data says 57. `verification/build_facts.py` (line 240) and `verification/facts.json` already record
  this as a correction: "Per-capability entries count 57 executed and 1 source-only. The original
  narrative count 56/58 is stale".
- **Caveat that applies to the 57.** "Executed" includes runs with substituted collaborators (stubs for
  the browser, desktop observation, systemctl show, nmcli and others). These are not 57 unmocked integration tests.

## Files and their status

| File | Says | Status |
|---|---|---|
| `README.md` (line "All 58 verifiers were classified, 57 of them with executed proof") | 57 | correct; it could add the substituted-collaborator caveat |
| `thesis/ARIES_03_Diplomska.pdf` / `.docx` ("Сите 58 верификатори беа класифицирани, 57 од нив со извршен доказ"; Figure 18 "58 верификатори, 57 со извршен доказ") | 57 | correct; not edited (protected) |
| `thesis/ARIES_Diplomska_Paket_20261006.zip`: `ARIES_01_Tehnicka.docx` and `.pdf` ("57 од 58 имаат записи за извршување") | 57 | correct; not edited (protected) |
| `verification/facts.json` and `verification/build_facts.py` | 57, with the correction recorded | correct |
| `verification/ledger_frozen.json` → `verification.classification_method` | 56 (copy of the raw narrative) | **erratum added 2026-10-12** as a new field `errata_20261012`; the original text is unchanged |
| **`experiments/product/independent-acceptance/raw/review_verifier_integrity.json`** → `method` | **56** | **stale, but must not be edited** (rule 1: raw reported result). The per-entry data in the same file is authoritative. |
| `experiments/product/independent-acceptance/acceptance.json` (lines 70–74) and `handoff.json` (lines 1336–1338, 1776) | quote both numbers | correct as written: they *document* the inconsistency and say the per-entry field is authoritative |
| `experiments/product/independent-acceptance/findings.json` (line 204) | 57 | correct |

Search scope: every `.md`, `.json`, `.py` and `.html` file in the working tree (frozen copies excluded), the two
files in `thesis/`, and every PDF, DOCX and text member of the thesis zip.
