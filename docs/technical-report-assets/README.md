# Technical report assets

`../ARIES_TECHNICAL_REPORT_MK.md` is the editable source. HTML and PDF are generated
by `scripts/aries-build-technical-report`, requiring Python `markdown`, `playwright`
and a Playwright Chromium installation. Existing SVGs can be reused offline.

To change Mermaid diagrams, run the builder with `--mermaid-js /path/to/mermaid.js`.
The initial build used the same local Mermaid 10.9.3 bundle as the publication package.
The exported HTML has inline SVGs and requires neither JavaScript nor a network.

Validation and the runtime snapshot used in the text are stored under
`experiments/documentation/20260919/`. Runtime evidence is a dated snapshot, not
an automatic update of the report when the endurance test finishes.
