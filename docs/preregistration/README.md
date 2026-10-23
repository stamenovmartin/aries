# Preregistrations

Each file states a hypothesis or a measure, its data, its test and its criterion, and was committed before the
measurement it governs (`git log --follow <file>` shows the date). A later change is a dated **Amendment**
section in the same file, committed before the computation it changes. A result that missed its criterion stays
reported as missed.

| Family | Files | Correction |
|---|---|---|
| Follow-up (thesis) | H4b, H5, H6, H8 | Holm over the four |
| Public data | R1 | Holm inside R1 |
| Remedies on new public samples | R1b | Holm inside R1b |
| Four local models | M2 | Holm inside M2 |
| Outside any family | X1 (exploratory), HAL1 (descriptive), M1 (exploratory, IIS) | none; no test counts as confirmation |
| Not run | H4 (registered, not run), H7 (postponed), H9 (dropped, design record) | — |

Wording quoted from the literature is checked in [`CITATIONS.md`](CITATIONS.md). Where each result is:
[`../INDEX.md`](../INDEX.md) and the README section "Evaluation on public datasets".
