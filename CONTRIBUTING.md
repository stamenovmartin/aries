# Contributing

## Commits

- Commits are authored and committed as the repository owner, Martin Stamenov, with his configured git identity.
- Commit messages, pull request texts, READMEs and code comments carry no AI attribution: no `Co-Authored-By`
  trailers naming a model or vendor, no `Claude-Session:` lines, no "Generated with" lines.
- Only the owner pushes. Automated agents and assistants prepare commits locally and never run `git push`,
  `gh pr create` or `gh pr merge`.
- History is not rewritten. The hashes of preregistration and amendment commits are the evidence that hypotheses
  were registered before measurement.

Install the hook that enforces the attribution rule once per clone:

    ./scripts/install-hooks.sh

## Research integrity

- Frozen results (ARIES-FINAL-20261006 and every reported result) are never changed; new results go to new files.
- Every behaviour change is behind a flag in `aries/flags.py`. While confirmatory measurements are pending, new
  flags default to off.
- Hypotheses and benchmark comparisons are preregistered under `docs/preregistration/` and pushed before data exists.
  Changes after registration go into dated Amendment sections in new commits.
- Every reported number comes from a committed file and passes `thesis-tables/check.py`.

## Privacy

Never commit databases, `flags.env` or `.env`, copied settings, tokens, the thesis PDF or Word files, external
datasets, or externally authored item files meant to stay local. Commit their SHA-256, a manifest and a download
script instead.
