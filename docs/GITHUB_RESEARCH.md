# GitHub research for ARIES

Reviewed 2026-09-14. This is a targeted reading of documentation and selected implementation files, not a full security audit. No external project was installed or executed. Recommendations below are not implemented by this research.

Follow-up: the first GNOME accessibility bridge and a bounded Python project
workflow informed by OSWorld's verification pattern have since been implemented.
See [JARVIS_PROGRESS.md](JARVIS_PROGRESS.md) for their measured limits and live evidence.

Further implementation: public browser sessions, Trafilatura extraction,
resource-aware concurrent goals, gated AT-SPI actions, generated Python with
isolated tests and a bounded goal planner are described in
[ADVANCED_WORKSPACE.md](ADVANCED_WORKSPACE.md). These use the existing ARIES engine;
OSWorld and UFO were design references, not installed replacement orchestrators.

## Findings and sources

### 1. OSWorld: verify the result of desktop work

[OSWorld VS Code evaluators](https://github.com/xlang-ai/OSWorld/blob/b138d348256078fa634fc3b73567a7337c793e6b/desktop_env/evaluators/metrics/vscode.py) check settings, file contents, installed extensions and Python test results. This provides concrete examples of checking application artifacts independently of the agent's own success message. Also read the evaluator README and GIMP getters at this revision.

Apply the pattern to ARIES task definitions: initial state, requested outcome, allowed actions, independent verifier and captured evidence. For example, “create and run a Python project in VS Code” must produce the project files and expected execution output; a visible VS Code window alone is insufficient. Run evaluation tasks in disposable directories or environments. Do not apply benchmark VM configuration instructions to the user's desktop.

License metadata: Apache-2.0. Pinned revision: `b138d348256078fa634fc3b73567a7337c793e6b`.

### 2. Browser Use: observe actual page state

Read [browser sessions](https://github.com/browser-use/browser-use/blob/843819cb8131e1370948d381ede9be7f8366ddc4/browser_use/browser/session.py), [DOM service](https://github.com/browser-use/browser-use/blob/843819cb8131e1370948d381ede9be7f8366ddc4/browser_use/dom/service.py) and the README. Sessions use CDP and events; the DOM service combines document structure, accessibility information and layout data.

ARIES currently verifies opening a URL through browser window titles in `aries/operator/goals.py::_verify_open_url`. That is circumstantial evidence. A browser adapter should inspect the actual URL and expected page elements, support targeted click/fill actions, and record the resulting state. Start with a dedicated Chromium session/profile: this CDP design is not a drop-in adapter for the installed Firefox or arbitrary desktop apps. Evaluate the local package separately from its advertised cloud service.

License metadata: MIT. Pinned revision: `843819cb8131e1370948d381ede9be7f8366ddc4`.

### 3. GNOME accessibility: inspect and operate Linux applications

The [pyatspi2 README](https://github.com/GNOME/pyatspi2/blob/a0df428cfe6713be5769e1a3d3ca9942b6b4645d/README.md) explains AT-SPI inspection and explicitly recommends direct libatspi GObject introspection for new applications. Also read `pyatspi/registry.py`; its desktop getter delegates to Atspi.

A read-only local import confirmed that `/usr/bin/python3` can load `gi.repository.Atspi`. This establishes binding availability only, not access to every application's controls. ARIES currently observes processes and window information in `aries/operator/desktop.py`. Add a bounded system-Python bridge to inspect roles, names, states and supported actions, then test application-specific actions. The core virtual environment and system GTK Python have different dependencies; keep that boundary explicit. Some applications may expose incomplete accessibility information, requiring a separate API/CLI or visual adapter.

GitHub license metadata was `NOASSERTION`; inspect upstream license files before copying implementation. Pinned revision: `a0df428cfe6713be5769e1a3d3ca9942b6b4645d`.

### 4. Microsoft UFO: dependency-aware task orchestration

Read [Galaxy architecture](https://github.com/microsoft/UFO/blob/be75a7ded2ad98d97819e15ff1b39d4202ac3ac5/galaxy/README.md), [TaskConstellation](https://github.com/microsoft/UFO/blob/be75a7ded2ad98d97819e15ff1b39d4202ac3ac5/galaxy/constellation/task_constellation.py) and the host agent processor. The constellation selects ready tasks after checking dependencies and orders them by priority. UFO's native Windows automation adapters are not Linux adapters.

ARIES `aries/workspace/service.py::dispatch` holds a global lock across execution and supervision. Long-running operations can therefore delay unrelated queued goals. Extend the existing vendored engine's orchestration rather than introduce another complete orchestrator: record dependencies and resource ownership, allow independent reads/background work concurrently, and serialize actions that compete for desktop focus. Preserve cancellation, timeouts, approval boundaries and evidence per task.

License metadata: MIT. Pinned revision: `be75a7ded2ad98d97819e15ff1b39d4202ac3ac5`.

### 5. Trafilatura: cleaner article extraction

Read the README, [Python usage](https://github.com/adbar/trafilatura/blob/eb04027c54cee100c4a6f203d4c31eff5b0e3ae6/docs/usage-python.rst) and `trafilatura/core.py`. It supports extraction from already-downloaded HTML, metadata and structured output. Comments are included by default; ARIES should explicitly disable them for article reading.

Compare this with the handwritten `ArticleParser` in `aries/workspace/reader.py` using saved real-page fixtures. Retain ARIES's existing bounded, SSRF-protected fetch and image checks; pass fetched HTML into extraction. Preserve source URL, title, extraction coverage and image provenance in each independent reading window. Image references do not guarantee a downloadable image. Extraction is not AI summarization: keep grounded summaries as a separate stage and measure omitted or unsupported claims. Upstream performance claims are not measurements of ARIES.

License metadata: Apache-2.0. Pinned revision: `eb04027c54cee100c4a6f203d4c31eff5b0e3ae6`.

## Recommended implementation sequence

1. Define independent verifiers and baseline runs for the 20 end-to-end tasks. Distinguish complete, partial, failed and cancelled outcomes; retain actual artifacts and tool traces.
2. Add the Linux accessibility bridge and finish one VS Code workflow: create a project, create its environment, run code and verify output and files. Check both successful execution and recovery from a real error.
3. Add browser state and actions in a dedicated session. Verify exact destination and expected content on real sites, including navigation failures.
4. Compare article extraction on saved pages, then integrate only if measured coverage and removal of navigation/comments improve. Verify titles, summaries and available images in separate response windows.
5. Add resource-aware concurrency using the existing engine. Demonstrate that reading can progress during an installation while two competing desktop actions cannot corrupt each other's state.

For every workflow, expose progress, current action, evidence, cancellation and final verification in the monitor and its own response window. Record elapsed time and tool calls; record token usage only where the provider reports it. Repeat a fixed task set before and after changes. Existing passing tests establish a baseline, not proof of autonomous self-improvement or completion of these integrations.

The most valuable transfer from these projects is a stronger observation → action → independent verification loop. The existing ARIES interface can present that loop without replacing its independent windows.
