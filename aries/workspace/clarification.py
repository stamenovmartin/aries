"""Bounded missing-target questions. Never guess an executable target."""
import re


def question(request, *, unresolved_reference=False):
    text = re.sub(r'\s+', ' ', request.strip()).rstrip('.!?…').casefold()
    mk = bool(re.search('[а-шА-Ш]', text))
    if unresolved_reference:
        return {
            'question': 'Кој фајл или адреса да ја отворам или прочитам?' if mk else 'Which file or URL should I open or read?',
            'choices': ['Отвори + точна патека или адреса', 'Прочитај + точна патека'] if mk else
                       ['Open + exact path or URL', 'Read file + exact path'],
        }
    if re.fullmatch(r'(?:play (?:something|anything)|пушти (?:нешто|било што)|pusti (?:nesto|neshto))', text):
        return {
            'question': 'Која песна или изведувач да пуштам?' if mk else 'Which song or artist should I play?',
            'choices': ['Пушти музика + име на песна', 'Пушти музика + име на изведувач'] if mk else
                       ['Play music + song title', 'Play music + artist name'],
        }
    if re.fullmatch(r'(?:move (?:it|that) (?:there|over there)|премести (?:го|ја|тоа) таму|premesti (?:go|ja|toa) tamu)', text):
        return {
            'question': 'Кој прозорец или фајл да преместам, и каде?' if mk else 'Which window or file should I move, and where?',
            'choices': ['Наведи прозорец и позиција', 'Наведи фајл и одредиште'] if mk else
                       ['Specify a window and position', 'Specify a file and destination'],
        }
    if re.fullmatch(r'(?:fix (?:it|that)|среди (?:го|ја|тоа)|sredi (?:go|ja|toa))', text):
        return {
            'question': 'Што точно не работи — апликација или фајл?' if mk else 'What is not working—a particular application or file?',
            'choices': ['Наведи апликација и проблем', 'Наведи фајл и проблем'] if mk else
                       ['Name the application and problem', 'Name the file and problem'],
        }
    return None


def reference_question(request, reference):
    """Ask for the missing target after verified-context resolution was attempted."""
    mk = bool(re.search('[а-шА-Ш]', request))
    kind = reference['capability']
    if kind == 'play_music':
        return question('пушти нешто' if mk else 'play something')
    if kind == 'install_app':
        return {'question': 'Која апликација да ја инсталирам?' if mk else 'Which application should I install?',
                'choices': ['Наведи име на апликацијата', 'Откажи'] if mk else ['Name the application', 'Cancel']}
    if kind in {'read_file', 'list_folder', 'trash_file', 'move_file'}:
        return {'question': 'На кој фајл или папка мислиш? Наведи ја точната патека.' if mk else 'Which file or folder do you mean? Give the exact path.',
                'choices': ['Наведи точна патека', 'Откажи'] if mk else ['Give the exact path', 'Cancel']}
    return {'question': 'На што точно се однесува барањето? Наведи име или патека.' if mk else 'What exactly does the request refer to? Give a name or path.',
            'choices': ['Наведи конкретно име или патека', 'Откажи'] if mk else ['Give the specific name or path', 'Cancel']}


def _observed_strings(value, out, depth=0):
    if depth > 8:
        return
    if isinstance(value, str):
        # Only path-like strings count, plus their final component. Free text and
        # field values such as "file" or "directory" must not ground a choice:
        # otherwise "some other file" would pass as observed.
        text = value.strip()
        if '/' in text and 3 <= len(text) <= 512 and '\n' not in text:
            out.add(text)
            name = text.rstrip('/').rsplit('/', 1)[-1]
            if len(name) >= 3:
                out.add(name)
    elif isinstance(value, dict):
        for item in value.values():
            _observed_strings(item, out, depth + 1)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _observed_strings(item, out, depth + 1)


def grounded_choices(choices, steps):
    """A planner question may only offer what the machine actually showed.

    Returns (ok, reason). A choice is grounded when it contains a path or a name
    taken from the result of a VERIFIED step of this goal. At least two choices
    must be grounded; one extra free choice ("cancel", "neither") is tolerated.
    Without this, "ask" becomes a way to invent candidates instead of guessing one.
    """
    observed = set()
    for step in steps:
        if step.get('verification_status') == 'verified':
            _observed_strings(step.get('execution_result'), observed)
    # A directory that was listed is not itself a candidate: every invented file
    # under it would otherwise "contain" its path and pass as observed.
    paths = {o for o in observed if o.startswith('/')}
    containers = {p for p in paths if any(q != p and q.startswith(p.rstrip('/') + '/') for q in paths)}
    leaves = {q for q in paths - containers}
    leaf_names = {q.rstrip('/').rsplit('/', 1)[-1] for q in leaves}
    container_names = {p.rstrip('/').rsplit('/', 1)[-1] for p in containers} - leaf_names
    observed -= containers | container_names
    if not observed:
        return False, 'no verified observation to take choices from'
    grounded = [c for c in choices if any(o in c for o in observed)]
    if len(grounded) < 2:
        return False, 'fewer than two choices name an observed path or name'
    if len(choices) - len(grounded) > 1:
        return False, 'more than one choice names nothing that was observed'
    return True, ''
