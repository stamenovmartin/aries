# ARIES verification-feedback feasibility pilot

**Exploratory development data. No confirmatory effect or production improvement is established.**

Execution window: 2026-10-04T08:08:42.590106+00:00 to 2026-10-04T08:11:23.155671+00:00. Assigned/completed: 34/34.
Model: `qwen2.5:7b`.
Code stable across episodes: True; settings stable: True.

Each case has one run per condition. Repeated fault families are not independent tasks. All arms retain the same execution, approval and completion safeguards.

| Surface | Condition | Scored/assigned | Unsupported model completion episodes | User-visible false success | Goal predicate met | Verified recovery |
|---|---|---:|---:|---:|---:|---:|
| controlled_screen_fixture | tool_only | 5/5 | 5/5 | 0/5 | 0/5 | 0/5 |
| controlled_screen_fixture | structured | 5/5 | 4/5 | 0/5 | 0/5 | 0/5 |
| native_read_only | tool_only | 10/10 | 0/10 | 0/10 | 4/10 | 0/10 |
| native_read_only | structured | 10/10 | 0/10 | 0/10 | 4/10 | 0/10 |

“Scored” means an observation oracle returned a Boolean, not that the row passed confirmatory admission. Native faults and synthetic returned-image faults are distinct interventions and are not pooled. No verified recovery occurred; fault exposure plus an unrelated successful step is not recovery.

The screen counts differ by only one case. This pilot is too small and heterogeneous to establish a general benefit. The completion guard intercepted unsupported proposals in both conditions; zero exposed false successes does not demonstrate that the planner stopped making those proposals.

## Owned-file controls

| Fault | Condition | Goal predicate met | Unsupported model proposals |
|---|---|---:|---:|
| none | tool_only | 1/1 | 0 |
| none | structured | 1/1 | 0 |
| stale_read | tool_only | 0/1 | 2 |
| stale_read | structured | 0/1 | 2 |

## Prompt-format development probe

Invalid-terminal episodes: 4/4 before and 0/4 after explicit terminal JSON examples.
Assigned: 12; attempted: 12; infrastructure errors: 8; valid pairs: 4.
This sequential development comparison selects previously failing cases. It is not a randomized generalization result. The opt-in `--terminal-examples` change exists only in the experimental runner; production was not modified. Error attempts remain in the JSON record.

## Admission and remaining work

The 600-run confirmatory study remains unlaunched. A larger denominator cannot repair an unidentified intervention.

- Some native service failures occur before verification; they test capability refusal and output formatting.
- Capture metadata is not a visual description. The text-only planner has no demonstrated image-understanding path here.
- Synthetic screen faults are introduced after capture defences; they do not validate native portal handling.
- The new answer oracle checks exact authored transcripts and structured facts. Other prose remains unknown and needs independent adjudication.
- A permitted alternative route must exist before this fixture can support a recovery comparison.
- Freeze a revised homogeneous intervention and outcome definition, retain these runs as excluded pilot data, and validate normal as well as faulty cases before confirmatory execution.

## Raw evidence

- Pilot manifest: [results.json](/home/stamenovmartin/aries/eval/research_feedback/pilots/20261004T080518Z/results.json)
- Prompt-format probe: [terminal_examples_checks.json](/home/stamenovmartin/aries/eval/research_feedback/terminal_examples_checks.json)

- vf-01 / structured / systemctl_show_not_found: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T080842Z-e098f7/result.json)
- vf-01 / tool_only / systemctl_show_not_found: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T080849Z-74f478/result.json)
- vf-02 / structured / systemctl_show_not_found: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T080852Z-0eac37/result.json)
- vf-02 / tool_only / systemctl_show_not_found: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T080856Z-699057/result.json)
- vf-03 / tool_only / systemctl_show_empty_exit_zero: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T080859Z-1a4b7a/result.json)
- vf-03 / structured / systemctl_show_empty_exit_zero: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T080903Z-32e1d9/result.json)
- vf-04 / tool_only / systemctl_show_no_loadstate: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T080906Z-9b5b41/result.json)
- vf-04 / structured / systemctl_show_no_loadstate: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T080910Z-777f5b/result.json)
- vf-05 / tool_only / nmcli_blank_exit_zero: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T080913Z-a5d901/result.json)
- vf-05 / structured / nmcli_blank_exit_zero: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T080918Z-9ce611/result.json)
- vf-06 / structured / nmcli_all_blank_exit_zero: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T080923Z-cd5d05/result.json)
- vf-06 / tool_only / nmcli_all_blank_exit_zero: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T080929Z-6ac673/result.json)
- vf-07 / structured / nmcli_settings_blank_state_activated: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T080934Z-667a2f/result.json)
- vf-07 / tool_only / nmcli_settings_blank_state_activated: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T080939Z-4137b9/result.json)
- vf-08 / tool_only / portal_black_png: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T080944Z-48492a/result.json)
- vf-08 / structured / portal_black_png: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T080947Z-61739f/result.json)
- vf-09 / structured / portal_black_png: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T080951Z-77e075/result.json)
- vf-09 / tool_only / portal_black_png: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T080958Z-eb3a95/result.json)
- vf-10 / tool_only / portal_uniform_grey_png: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T081005Z-98a818/result.json)
- vf-10 / structured / portal_uniform_grey_png: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T081008Z-481864/result.json)
- vf-11 / tool_only / portal_black_png_two_frames: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T081012Z-77756d/result.json)
- vf-11 / structured / portal_black_png_two_frames: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T081019Z-bf0218/result.json)
- vf-12 / structured / systemctl_show_not_found: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T081023Z-247a4d/result.json)
- vf-12 / tool_only / systemctl_show_not_found: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T081027Z-7668b8/result.json)
- vf-13 / structured / nmcli_blank_exit_zero: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T081030Z-c24388/result.json)
- vf-13 / tool_only / nmcli_blank_exit_zero: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T081037Z-c985f4/result.json)
- vf-14 / structured / portal_black_png: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T081043Z-184bea/result.json)
- vf-14 / tool_only / portal_black_png: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T081050Z-e9539c/result.json)
- vf-15 / structured / systemctl_show_not_found: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T081054Z-5560b7/result.json)
- vf-15 / tool_only / systemctl_show_not_found: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T081058Z-059adb/result.json)
- owned_files / tool_only / none: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T081101Z-ea8556/result.json)
- owned_files / structured / none: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T081105Z-5a9eba/result.json)
- owned_files / tool_only / stale_read: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T081110Z-9150da/result.json)
- owned_files / structured / stale_read: [run artifact](/home/stamenovmartin/aries/eval/research_feedback/runs/20261004T081116Z-bba560/result.json)
