# Census measured 2026-10-03T11:35:53.512652+00:00

14-day goals: 750; unsuccessful states: 177. Future-dated goals excluded: 3.
Known frozen-fixture goals: 154; unsuccessful among them: 53.

| Recorded cause | All unsuccessful (n) | Excluding known fixture (n) |
|---|---:|---:|
| ASR | 0 | 0 |
| routing | 0 | 0 |
| planner | 25 | 25 |
| capability | 45 | 39 |
| verification | 0 | 0 |
| timeout | 5 | 5 |
| other | 102 | 55 |

Rule-based from stored failure fields; other includes insufficient evidence. No attribution of ASR errors without recorded ASR evidence. Partial/interrupted/unconfirmed/empty included; cancelled excluded.
Only this frozen60 fixture IDs identified; other synthetic trials may remain.

Unknown causes must be reviewed before declaring the leading two causes fixed.

## SQLite observation coverage

Requested window: 2026-10-01T11:35:53.512652+00:00 to 2026-10-03T11:35:53.512652+00:00.
Lock-message records: 0 / 0 available journal records.
First/last log timestamps do not prove continuous service operation. Clock changes and unavailable journal intervals prevent a 48-hour acceptance claim.
A zero denominator supplies no evidence of stability.

## Registry inventory

| Capability | Registered verifier |
|---|---|
| browser.back | verify_state |
| browser.click | verify_state |
| browser.download | verify_download |
| browser.elements | verify_elements |
| browser.forward | verify_state |
| browser.navigate | verify_state |
| browser.observe | verify_state |
| browser.open | verify_browser |
| browser.read | verify_browser |
| browser.scroll | verify_scroll |
| browser.search | verify_browser |
| browser.tabs | verify_tabs |
| browser.type | verify_type |
| browser.wait | verify_state |
| desktop.close | verify |
| desktop.focus | verify_focus |
| desktop.launch | verify_desktop |
| desktop.maximize | verify |
| desktop.minimize | verify |
| desktop.move | verify |
| desktop.observe | verify_observe |
| desktop.resize | verify |
| desktop.tile | verify |
| desktop.unmaximize | verify |
| desktop.windows | verify_observe |
| display.brightness | verify_read_brightness |
| display.set_brightness | verify_set_brightness |
| file.copy | verify_copy |
| file.edit | verify_edit |
| file.exists | verify_exists |
| file.list | verify |
| file.metadata | verify_metadata |
| file.move | verify_move |
| file.read | verify_read |
| file.rename | verify_move |
| file.search | verify |
| file.semantic_search | verify_search |
| file.write | verify_write |
| input.clipboard_read | verify_clipboard_read |
| input.clipboard_write | verify_clipboard_write |
| input.editable_targets | verify_targets |
| input.type_text | verify_type |
| network.status | verify_status |
| network.wifi_connect | verify_connect |
| network.wifi_list | verify_wifi |
| notification.send | verify_notification |
| screen.capture | verify_capture |
| screen.read | verify_read |
| screen.screenshot | verify_capture |
| system.disk | verify_disk |
| system.packages | verify_packages |
| system.processes | verify |
| system.service | verify_unit |
| system.service_control | verify_control |
| system.services | verify_services |
| system.status | verify |
| system.storage | verify |
| task.inspect | verify |

## Spoken catalogue observations

| Capability | Static verification marker | Observed steps (n) | Without top-level verified |
|---|---|---:|---:|
| open_app | True | 40 | 32 |
| agent_task | False | 7 | 7 |
| inspect_app | False | 0 | 0 |
| ui_action | True | 0 | 0 |
| browser_open | True | 0 | 0 |
| browser_inspect | False | 0 | 0 |
| browser_follow | True | 0 | 0 |
| browser_fill | True | 0 | 0 |
| browser_close | True | 0 | 0 |
| python_project | True | 0 | 0 |
| build_python | True | 0 | 0 |
| open_url | True | 10 | 10 |
| open_path | True | 0 | 0 |
| search_web | True | 0 | 0 |
| research | False | 287 | 287 |
| read_article | False | 0 | 0 |
| processes | False | 2 | 2 |
| refresh_news | True | 1 | 1 |
| brief | True | 1 | 1 |
| health | True | 2 | 1 |
| system | False | 8 | 8 |
| services | True | 10 | 4 |
| service_control | True | 0 | 0 |
| disk | True | 8 | 4 |
| package_info | True | 30 | 5 |
| learning_eval | False | 2 | 2 |
| evaluation | False | 2 | 2 |
| list_apps | False | 0 | 0 |
| find_files | False | 2 | 2 |
| list_folder | True | 38 | 12 |
| read_file | True | 170 | 76 |
| create_folder | True | 3 | 3 |
| create_file | True | 4 | 4 |
| move_file | True | 0 | 0 |
| trash_file | True | 1 | 1 |
| install_app | True | 1 | 1 |
| remember | False | 0 | 0 |
| play_music | True | 45 | 41 |
| media_control | True | 0 | 0 |
| set_volume | True | 10 | 0 |
| say | True | 0 | 0 |
| abilities | True | 12 | 4 |
| can_you | False | 2 | 2 |
| read_screen | True | 0 | 0 |
| screenshot | True | 0 | 0 |
| clipboard_read | True | 0 | 0 |
| clipboard_write | True | 0 | 0 |
| editable_fields | False | 0 | 0 |
| type_text | True | 0 | 0 |
| network_status | False | 0 | 0 |
| wifi_list | False | 0 | 0 |
| wifi_connect | True | 0 | 0 |
| brightness | False | 0 | 0 |
| set_brightness | True | 0 | 0 |

Registration/static markers do not prove a verifier was called in every execution. These registry and spoken-catalogue surfaces have different names and denominators. No whole-population verification target is declared complete.
