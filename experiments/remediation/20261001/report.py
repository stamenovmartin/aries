"""Generate measured progress and capability tables; never hand-edit the values."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];D=Path(__file__).parent
b=json.loads((D/'fixture-before.json').read_text());a=json.loads((D/'fixture-after.json').read_text());c=json.loads((D/'census.json').read_text())
def score(d):
 eligible=[s for r in d['cases'] if r['capability']!='research' for s in r['steps']]
 research=[s for r in d['cases'] if r['capability']=='research' for s in r['steps']]
 return {'n':len(eligible),'verdict_recorded':sum(s['met'] is True for s in eligible),'analytics_visible':sum(s['verification_status']=='verified' for s in eligible),'research_n':len(research),'research_explicit_status':sum(s['verification_status']=='unverifiable' for s in research),'unsupported_verified':sum(s['verification_status']=='verified' and s['met'] is not True for s in eligible+research)}
x,y=score(b),score(a)
assert b.get('finished_at') and a.get('finished_at') and len(b['cases'])==len(a['cases'])==21
out={'before':x,'after':y,'before_finished_at':b['finished_at'],'after_finished_at':a['finished_at'],'scope':'Same 7 capabilities x3 on installed API; 18 verifier-eligible plus3 research. Not population coverage or acoustic speech test.','closed':False}
(D/'paired-results.json').write_text(json.dumps(out,indent=2)+'\n')
rows=['# Измерен напредок — 1 октомври 2026','',f'Жива фикстура: {len(a["cases"])} цели пред и {len(b["cases"])} после; истите 7 способности × 3.','', '| Ставка | Пред (n) | После (n) | Што е сменето | Непроверено |','|---|---|---|---|---|',f'| 1.1 зачуван позитивен verdict | {x["verdict_recorded"]}/{x["n"]} | {y["verdict_recorded"]}/{y["n"]} | Независни повторни читања и постојни проверувачи | Целиот сообраќај и сите способности |',f'| 1.1 verdict видлив за аналитиката | {x["analytics_visible"]}/{x["n"]} | {y["analytics_visible"]}/{y["n"]} | Резултатот се пренесува во статусот на чекорот | Нема ретроактивно препишување историја |',f'| research експлицитен статус | {x["research_explicit_status"]}/{x["research_n"]} | {y["research_explicit_status"]}/{y["research_n"]} | unverifiable | Пред мерењето веќе постоеше посебен marker; ова не мери нова проверка на вистинитоста |',f'| verified без зачуван позитивен verdict | {x["unsupported_verified"]}/{x["n"]+x["research_n"]} | {y["unsupported_verified"]}/{y["n"]+y["research_n"]} | Строг boolean verdict | Не е доказ за сите можни патеки |','', 'Не се тврди затворање на 1.1. Services/abilities проверуваат набљудливост; disk проверува присуство на mountpoints и директориуми, не еднаквост на подвижни usage-бројки. Прекинатите мерења од паралелни рестарти се зачувани одделно.','', '## Причини за незавршени цели — првична автоматска класификација','',f'Свеж попис: {c["measured_at"]}; сите {c["goal_n"]} цели во 14 дена, без scan cap. {c["unsuccessful_n"]} failed/partial/interrupted/unconfirmed/empty. Вклучува и тест-цели; ова не е чиста стапка на успех за кориснички задачи.','', '| Причина | n |','|---|---:|']
rows += [f'| {k} | {v} |' for k,v in c['reason_counts'].items()]
rows += ['', 'Категоријата other бара преглед; нула ASR/routing не значи дека немало такви грешки. Првичната класификација беше премногу широка: „Planner stopped“ не докажува дефект на планерот. Употребената корекција прво ги зема снимените грешки на способноста. Нема доказ за подобрување по 48 часа.','', '## Способности — актуелен попис','',f'Регистар: {c["registry_n"]}; говорен каталог: {c["catalogue_n"]}. Ова се две различни површини.','', '| Регистарска способност | Проверувач |','|---|---|']
rows += [f'| {r["name"]} | {r["verifier"] or "нема"} |' for r in c['registry_capabilities']]
rows += ['', '| Говорна способност | Статички запис на проверка | Чекори (n) | Без top-level verified |','|---|---|---:|---:|']
rows += [f'| {r["capability"]} | {r["executor_records_verification_static"]} | {r["steps_n"]} | {r["unverified_steps"]} |' for r in c['capabilities']]
rows += ['', 'Статичкиот запис не докажува повик во секое извршување; деталните buckets и registry twins се во census.json. Непроверените историски чекори остануваат непрепишани.','']
text='\n'.join(rows);(D/'REPORT.md').write_text(text)
p=ROOT/'docs/ARIES_REPORT.md';s=p.read_text();start='<!-- REMEDIATION-MEASUREMENTS:START -->';end='<!-- REMEDIATION-MEASUREMENTS:END -->';block=start+'\n'+text+'\n'+end
if start in s:s=s[:s.index(start)]+block+s[s.index(end)+len(end):]
else:s+='\n\n'+block+'\n'
p.write_text(s)
print(json.dumps(out))
