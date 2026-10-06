"""Conservative goal conditions derived from USER text, never model completion prose.

Capability planning is generic. Completion recognizers intentionally fail closed
for semantic goals for which this milestone has no independent oracle.
"""
import hashlib
import math
import re
from pathlib import Path
from urllib.parse import urlsplit


MEASUREMENT_QUESTIONS = (
    (r'(?:how much (?:free )?(?:disk |storage )?space (?:do I have|is (?:available|free|left)(?: on (?:the |my )?disk)?)|show (?:free )?disk space|колку (?:слободно )?(?:место|простор) (?:има|имам)(?: на дискот)?|kolku (?:slobodno )?(?:mesto|prostor) (?:ima|imam)(?: na diskot)?)',
     'system.storage', 'disk.used_pct', ('free_gib',)),
    (r'(?:how much (?:RAM|memory) (?:is (?:being )?used|am I using)|show memory usage|колку (?:меморија|рам) (?:се користи|е зафатена)|kolku (?:memorija|ram) (?:se koristi|e zafatena))',
     'system.status', 'memory.used_pct', ()),
    (r'(?:what is (?:the )?CPU usage|show CPU usage|колку е оптоварен процесорот|kolku e optovaren procesorot)',
     'system.status', 'cpu.used_pct', ()),
)


def measured_readings(data, requirement, depth=0):
    """Only the requested numeric metric, from the verifier's actual probe."""
    if depth > 8:
        return []
    found = []
    if isinstance(data, dict):
        value = data.get('value')
        if data.get('metric') == requirement['metric'] and type(value) in (int, float) \
                and math.isfinite(value):
            detail = data.get('detail') or {}
            if isinstance(detail, dict) and all(type(detail.get(k)) in (int, float)
                    and math.isfinite(detail[k]) and detail[k] >= 0
                    for k in requirement.get('reading_fields', ())):
                found.append(data)
        for item in list(data.values())[:100]:
            found.extend(measured_readings(item, requirement, depth + 1))
    elif isinstance(data, list):
        for item in data[:100]:
            found.extend(measured_readings(item, requirement, depth + 1))
    return found


def compile_goal(goal, demo_directory):
    text = goal.strip()
    # Only complete, independently recognizable read clauses may be combined.
    # Never split arbitrary prose or creation content into executable sub-goals.
    clauses=re.split(r'\s+(?:and|then)\s+(?=(?:read|check|list)\s)',text,flags=re.I)
    if 1<len(clauses)<=4 and all(re.match(r'^(?:read|check|list)\s',c,re.I) for c in clauses):
        parts=[compile_goal(c,demo_directory) for c in clauses]
        allowed={'file.read','file.exists','file.list','system.status','system.storage','system.processes'}
        if all(p['supported'] and all(r['capability'] in allowed for r in p['requirements']) for p in parts):
            return {'supported':True,'requirements':[r for p in parts for r in p['requirements']],
                    'answer':'compound_reads','parts':parts}
    for pattern, capability, metric, fields in MEASUREMENT_QUESTIONS:
        if re.fullmatch(pattern + r'[.?!]?', text, re.I):
            language = 'mk' if re.search(r'[а-яѓќѕјљњџ]|\bkolku\b', text, re.I) else 'en'
            return {'supported': True, 'requirements': [
                {'capability': capability, 'metric': metric, 'reading_fields': list(fields)}],
                'answer': 'measurements', 'language': language}
    # Anchored patterns cannot silently ignore additional user requirements.
    match = re.fullmatch(r'(?:Create|Создај|Направи|Sozdaj|Napravi) (?:a )?(?:file|датотека|datoteka) (?:called )?(.+?) (?:in the ARIES demo directory|(?:in|во|vo) (.+?)) (?:containing|со содржина|so sodrzhina):\s*([\s\S]+?)\s*(?:Then read it back|and read it back|Потоа прочитај ја|и прочитај ја|Potoa prochitaj ja|i prochitaj ja)\.?',text,re.I)
    if match:
        name, directory, content = match.groups()
        path = Path(directory or demo_directory).expanduser()/name.strip(' "\'')
        return {'supported':True,'requirements':[
            {'capability':'file.write','path':str(path),'content_sha256':hashlib.sha256(content.encode()).hexdigest()},
            {'capability':'file.read','path':str(path),'content_sha256':hashlib.sha256(content.encode()).hexdigest()}]}
    match = re.fullmatch(r'(?:Create|Write|Save|Создај|Напиши|Зачувај|Sozdaj|Napishi|Zachuvaj)(?: (?:a )?(?:file|датотека|datoteka))?\s+((?:~?/)[^\s]+)\s+(?:containing|with content|со содржина|so sodrzhina)\s*:?\s*([\s\S]+)',text,re.I)
    if match:
        path, content = match.groups()
        return {'supported':True,'requirements':[{'capability':'file.write','path':str(Path(path).expanduser()),
            'content_sha256':hashlib.sha256(content.encode()).hexdigest()}]}
    match = re.fullmatch(r'(?:Read|Прочитај|Prochitaj)\s+(?:(?:file|датотека|datoteka)\s+)?((?:~?/)[^\s]+)',text,re.I)
    if match:
        return {'supported':True,'requirements':[{'capability':'file.read','path':str(Path(match[1]).expanduser())}]}
    if re.fullmatch(r'Check disk usage and report which filesystem has the highest percentage used\.?',text,re.I):
        return {'supported':True,'requirements':[{'capability':'system.storage'}], 'answer':'highest_filesystem'}
    match = re.fullmatch(r'Open\s+(https?://\S+)\s+and report (?:the )?(?:observed )?(?:page )?title\.?',text,re.I)
    if match:
        return {'supported':True,'requirements':[{'capability':'browser.open','url':match[1]},
                                               {'capability':'browser.read','url':match[1]}], 'answer':'page_title'}
    match = re.fullmatch(r'Open YouTube and search for (.+?)\.?',text,re.I)
    if match:
        return {'supported':True,'requirements':[{'capability':'browser.search','query':match[1],'site':'youtube'}], 'answer':'search_page'}
    if re.fullmatch(r'(?:(?:Check|Show) system status|(?:Провери|Прикажи) (?:го )?статусот на системот|(?:Proveri|Prikazhi) (?:go )?statusot na sistemot)\.?',text,re.I):
        return {'supported':True,'requirements':[{'capability':'system.status'}]}
    if re.fullmatch(r'(?:(?:List|Show)(?: running)? processes|(?:Прикажи|Листај) (?:активни |активните )?процеси|(?:Prikazhi|Listaj) (?:aktivni |aktivnite )?procesi)\.?',text,re.I):
        return {'supported':True,'requirements':[{'capability':'system.processes'}]}
    match = re.fullmatch(r'(?:Open|Launch|Отвори|Пушти|Otvori|Pushti) (?:the )?(?:(?:application|апликација|апликацијата|aplikacija) )?([^/\n]+)',text,re.I)
    if match and not re.search(r'\b(and|then|search|report|save|delete|install|и|потоа|пребарај|зачувај|избриши|инсталирај|i|potoa|prebaraj|zachuvaj|izbrishi|instaliraj)\b',match[1],re.I):
        return {'supported':True,'requirements':[{'capability':'desktop.launch','app':match[1]}]}
    return {'supported':False,'requirements':[],
            'reason':'No independent completion contract for this goal yet. Useful verified steps may be reported only as partial.'}


def matches(requirement, step):
    if step['capability'] != requirement['capability']:
        return False
    args = step['args']
    for key in ('path','url','query','site','app'):
        if key in requirement:
            if key == 'path':
                if str(Path(args.get(key,'')).expanduser().absolute()) != str(Path(requirement[key]).absolute()):
                    return False
            elif args.get(key) != requirement[key]:
                # browser.read has no URL argument: verify against observed page.
                if not (key == 'url' and step['capability']=='browser.read'):
                    return False
    return True


def evidence_matches(requirement, verification):
    if not verification.get('met'):
        return False
    data = verification['data']
    if 'metric' in requirement and not measured_readings(data, requirement):
        return False
    if requirement.get('capability') == 'browser.search':
        from urllib.parse import parse_qs
        observed = urlsplit(data.get('url',''))
        youtube = requirement.get('site') == 'youtube'
        if observed.hostname != ('www.youtube.com' if youtube else 'duckduckgo.com') or (youtube and observed.path != '/results') or parse_qs(observed.query).get('search_query' if youtube else 'q') != [requirement['query']]:
            return False
    if requirement.get('content_sha256') and data.get('sha256') != requirement['content_sha256']:
        return False
    if 'path' in requirement and data.get('path') != str(Path(requirement['path']).absolute()):
        return False
    if 'url' in requirement:
        # Conservative: do not accept an unrelated redirect as goal fulfillment.
        actual, expected = urlsplit(data.get('url','')), urlsplit(requirement['url'])
        if (actual.scheme,actual.netloc,actual.path.rstrip('/'),actual.query) != (expected.scheme,expected.netloc,expected.path.rstrip('/'),expected.query):
            return False
        if not data.get('title'):
            return False
    return True


def answer(contract, evidence):
    rows = [e['data'] for e in evidence]
    if contract.get('answer')=='compound_reads':
        cursor=0;answers=[]
        for part in contract['parts']:
            count=len(part['requirements'])
            answers.append(answer(part,evidence[cursor:cursor+count]));cursor+=count
        return '\n\n'.join(answers)
    if contract.get('answer') == 'measurements':
        from aries.speech.replies import sentence
        readings = [reading for requirement, data in zip(contract['requirements'], rows)
                    for reading in measured_readings(data, requirement)]
        return sentence({'state': 'answered', 'readings': readings},
                        language=contract.get('language', 'en'))
    if contract.get('answer') == 'highest_filesystem':
        top = rows[-1]['highest']
        return f"Highest observed filesystem usage: {top['subject']} — {top['value']} {top['unit']}."
    if contract.get('answer') == 'page_title':
        return rows[-1]['title'] + ' — ' + rows[-1]['url']
    if contract.get('answer') == 'search_page':
        return 'Observed search destination: ' + rows[-1]['url']
    if rows and 'text' in rows[-1]:
        return 'Verified file: ' + rows[-1]['path'] + '\n' + rows[-1]['text'][:2000]
    return 'All supported goal conditions independently verified. See referenced evidence.'
