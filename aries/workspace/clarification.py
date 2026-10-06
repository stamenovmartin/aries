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
