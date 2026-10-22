# R1 labels (frozen 2026-10-22, before any ARIES or baseline run)

Ids and labels only; the request texts are never committed. Labeler A: Claude Code CLI 2.1.308 (`claude -p`,
model claude-opus-4-8 as reported by the CLI), labeler B: Codex CLI 0.154.0 (`codex exec`, model from
`~/.codex/config.toml`: "gpt-6-astra"), adjudicator: a third fresh `claude -p` session.
All sessions: empty working directory, no tools (A) / read-only sandbox (B); no transcript showed a tool call.

| set | items | kappa (labels) | raw agreement | kappa (in/out of scope) | disagreements adjudicated | final file SHA-256 |
|---|---|---|---|---|---|---|
| CLINC150 intents | 150 | 0.826 | 0.920 | 0.824 | 12 (A 3, B 9) | `e328c630959d014113ba7728f52792ece87aa7e56c8e61f31d69ef2b75d11228` |
| NL2Bash requests | 600 | 0.649 | 0.802 | 0.667 | 119 (A 76, B 43) | `83a5b9a7daa67a988c7ba59f6ac508e3335003c746ec4076a55b1fdd5d05154d` |

Final label counts are in `*-agreement.json`. CLINC: 57 intents SUPPORTED (56 of them `browser.search`, 1
`file.search`), 93 OUT_OF_SCOPE: the labelers read most answerable assistant intents (weather, date, facts) as
"a web search fulfils it". NL2Bash (600): 365 OUT_OF_SCOPE, 173 `file.search`, 30 `file.list`, 15 `file.read`,
17 other.
