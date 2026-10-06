# ARIES publication package

**ARIES: Evidence-Verified Agentic Execution in a Local Linux Environment**  
Martin Stamenov · Македонски труд и презентација

- [Труд PDF](paper.pdf) · [offline HTML](paper.html) · [Markdown source](paper.md)
- [Презентација PDF — 18 слајдови](presentation.pdf) · [offline HTML](presentation.html) · [Markdown со Mermaid](slides.md)
- [M14 резултати и статус](m14-results.md)
- [Artifact manifest и SHA-256 digests](evidence-manifest.json)
- [Mermaid sources и rendered SVGs](diagrams/)

Отворање од коренот на repository:

```bash
xdg-open docs/publication/presentation.html
xdg-open docs/publication/paper.pdf
```

HTML презентацијата работи offline. Навигација: ← / →, PageUp / PageDown, Home / End. Ctrl+P ги печати сите слајдови. Нема CDN, analytics или external runtime dependencies во deliverables.

M14 live run `20260917T204354Z-fb8722` поминува 4/4 required scenarios, со реален local model и 36,039 native tokens. Претходните неуспешни обиди и ограничувањата се документирани во addendum.

## Rebuild

`build.py` ги користи зачуваните Mermaid SVGs и stdlib за презентацијата. За PDF export е потребен Playwright со Chromium, достапен во repository `.venv`. Paper HTML generation дополнително користи Python Markdown.

```bash
.venv/bin/python docs/publication/build.py
.venv/bin/python docs/publication/build.py --pdf
```

За целосно обновување на трудот, инсталирај Python Markdown во избрана build environment и повикај `--paper --pdf`. Во авторската сесија Markdown е во привремен directory без промена на runtime dependencies:

```bash
uv pip install --python .venv/bin/python --target /tmp/aries-publication-python markdown==3.10.3
PYTHONPATH=/tmp/aries-publication-python .venv/bin/python docs/publication/build.py --paper --pdf
```

За промена на Mermaid diagrams, обнови `.mmd` sources и рендерирај со `--mermaid-js /path/to/mermaid.min.js`. Авторската верзија користи Mermaid 10.9.3; bundle-от е build-time dependency, не е потребен за отворање на конечните HTML/PDF files. Paper Mermaid blocks и `.mmd` files треба да останат исти.

## Evidence corrections relative to the supplied draft

- 372 trials вклучуваат 60 control attempts; 52 се eligible по 8 contamination exclusions.
- A и B2 имаат ист **raw** honesty gap од 4/67 = 5.97%. Verified reporting не ја препишува историската `reported` колона во нула.
- Correct refusals на impossible tasks се дел од verified outcomes; 60/67 не е само positive action success.
- Историскиот preregistered A > B2 criterion не е исполнет.
- 11/11 и 7/7 се историски product runs, одделени од M14.
- Retrieval p = 0.125; нема statistical significance claim.
- No universal prompt-injection immunity, exactly-once guarantee, or first-in-literature novelty is claimed.

Primary literature links are provided in the paper. Local artifacts remain authoritative for ARIES-specific numbers.

## Deployment addendum — 19 September 2026

See [background validation](../BACKGROUND_VALIDATION.md) and
[personal news](../PERSONAL_NEWS.md) for the latest implementation evidence.
These are development results, separate from the historical controlled experiments:
M14 live scenarios 4/4; personalized news 8/8; full desktop demo 10/11 pending a
fresh GNOME login; 24-hour observation started but not yet complete. Local summary
quality is limited and failed checks retain original excerpts. Historical PDFs and
experiment hashes are preserved; these operational additions do not amend their
statistical findings.
