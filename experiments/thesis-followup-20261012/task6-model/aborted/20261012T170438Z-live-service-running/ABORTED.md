# Aborted run — excluded from every result

- **Started:** 2026-10-12T17:04:38Z. **Stopped:** about 17:10Z with SIGINT, on the author's instruction.
- **Reached:** 4 complete cells (r1-A0, r1-A1, r1-A2, r1-A3) and r2-A1 at 78/225.

**Why it was stopped.** The live ARIES (aries.target) was running during the measurement. Ollama swapping between
llama3.1:8b and the live service's qwen2.5:7b adds latency, which can surface as technical errors that look like bad
decisions. The author decided that Task 6 is to be measured overnight with the live service stopped.

These rows were not scored or inspected. They are kept only so that no attempt disappears. The valid run is the
one in `../../raw/`, described in `../../README.md`.
