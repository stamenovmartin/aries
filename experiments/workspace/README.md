# Workspace evaluation protocol

The current target is twenty bounded capabilities, each with a usable dashboard.
This is an engineering acceptance evaluation, not a claim that an adaptive model
outperforms a research baseline.

`live_evaluate.py` submits requests through the installed HTTP API and waits for
persisted outcomes. It uses real websites (YouTube, DuckDuckGo, kernel.org), the
installed desktop, real news feeds and disposable files in Documents. It records
both success and limitations. A proposed installation is not counted as installed;
an already-installed package is explicitly labelled as an already-satisfied state.
It never installs or upgrades a system package just to inflate the success count.
Only changes to evaluation-owned files are approved automatically.

The unit suite separately tests hostile source text, input validation, the complete
install/approval/revision-verification protocol with a simulated package manager,
changed-target rejection, cancellation, privacy, and non-overwrite semantics.
Those are controlled tests, not evidence of a live system installation.

Run after starting ARIES: `python3 experiments/workspace/live_evaluate.py`.
The live runner opens real windows, fetches public pages, creates and removes its
own files, and stores results beside itself. It does not modify existing user files.

Later user-requested response surfaces and article reading are measured separately
from the original twenty-capability run. `response-results.json` checks independent
windows and closing without cancelling work. `reading-results.json` records a real
MIT article, local AI output, full extracted input coverage and source image.
`screens/reading.png` captures that GTK response against the live API. These are
engineering acceptance checks; they do not establish model factuality or a research
advantage over a baseline.
