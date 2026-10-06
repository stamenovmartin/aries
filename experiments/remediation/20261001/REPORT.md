# Измерен напредок — 1 октомври 2026

Жива фикстура: 21 цели пред и 21 после; истите 7 способности × 3.

| Ставка | Пред (n) | После (n) | Што е сменето | Непроверено |
|---|---|---|---|---|
| 1.1 зачуван позитивен verdict | 3/18 | 18/18 | Независни повторни читања и постојни проверувачи | Целиот сообраќај и сите способности |
| 1.1 verdict видлив за аналитиката | 0/18 | 18/18 | Резултатот се пренесува во статусот на чекорот | Нема ретроактивно препишување историја |
| research експлицитен статус | 0/3 | 3/3 | unverifiable | Пред мерењето веќе постоеше посебен marker; ова не мери нова проверка на вистинитоста |
| verified без зачуван позитивен verdict | 0/21 | 0/21 | Строг boolean verdict | Не е доказ за сите можни патеки |

Не се тврди затворање на 1.1. Services/abilities проверуваат набљудливост; disk проверува присуство на mountpoints и директориуми, не еднаквост на подвижни usage-бројки. Прекинатите мерења од паралелни рестарти се зачувани одделно.

## Причини за незавршени цели — првична автоматска класификација

Свеж попис: 2026-10-01T00:17:25.701804+00:00; сите 780 цели во 14 дена, без scan cap. 140 failed/partial/interrupted/unconfirmed/empty. Вклучува и тест-цели; ова не е чиста стапка на успех за кориснички задачи.

| Причина | n |
|---|---:|
| ASR | 0 |
| routing | 0 |
| planner | 29 |
| capability | 52 |
| verification | 0 |
| timeout | 4 |
| other | 55 |

Категоријата other бара преглед; нула ASR/routing не значи дека немало такви грешки. Првичната класификација беше премногу широка: „Planner stopped“ не докажува дефект на планерот. Употребената корекција прво ги зема снимените грешки на способноста. Нема доказ за подобрување по 48 часа.

## Способности — актуелен попис

Регистар: 58; говорен каталог: 54. Ова се две различни површини.

| Регистарска способност | Проверувач |
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

| Говорна способност | Статички запис на проверка | Чекори (n) | Без top-level verified |
|---|---|---:|---:|
| open_app | True | 36 | 36 |
| agent_task | False | 7 | 7 |
| inspect_app | False | 0 | 0 |
| ui_action | True | 0 | 0 |
| browser_open | True | 3 | 3 |
| browser_inspect | False | 0 | 0 |
| browser_follow | True | 0 | 0 |
| browser_fill | True | 0 | 0 |
| browser_close | True | 0 | 0 |
| python_project | True | 0 | 0 |
| build_python | True | 0 | 0 |
| open_url | True | 8 | 8 |
| open_path | True | 0 | 0 |
| search_web | True | 0 | 0 |
| research | False | 423 | 423 |
| read_article | False | 1 | 1 |
| processes | False | 0 | 0 |
| refresh_news | True | 7 | 7 |
| brief | True | 7 | 7 |
| health | True | 0 | 0 |
| system | False | 18 | 18 |
| services | True | 5 | 4 |
| service_control | True | 0 | 0 |
| disk | True | 5 | 4 |
| package_info | True | 6 | 4 |
| learning_eval | False | 9 | 9 |
| evaluation | False | 9 | 9 |
| list_apps | False | 0 | 0 |
| find_files | False | 0 | 0 |
| list_folder | True | 16 | 14 |
| read_file | True | 28 | 26 |
| create_folder | True | 10 | 10 |
| create_file | True | 10 | 10 |
| move_file | True | 0 | 0 |
| trash_file | True | 0 | 0 |
| install_app | True | 1 | 1 |
| remember | False | 0 | 0 |
| play_music | True | 41 | 41 |
| media_control | True | 0 | 0 |
| set_volume | True | 0 | 0 |
| say | True | 0 | 0 |
| abilities | True | 5 | 4 |
| can_you | False | 0 | 0 |
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

Статичкиот запис не докажува повик во секое извршување; деталните buckets и registry twins се во census.json. Непроверените историски чекори остануваат непрепишани.
