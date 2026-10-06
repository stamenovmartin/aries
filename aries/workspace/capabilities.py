"""Twenty bounded capabilities. Arbitrary shell text is not a capability."""
import asyncio
import configparser
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
from urllib.parse import quote, urlsplit

# This catalogue drives the UI, parser, tests and evaluation inventory.
CATALOGUE = (
    ("open_app", "Open an installed application", "open Firefox"),
    ("agent_task", "Plan and execute a goal using observed results", "do task Open Python documentation and report its title"),
    ("inspect_app", "Inspect an application's accessible controls", "inspect app VS Code"),
    ("ui_action", "Activate an application control and verify the expected element", "activate app Files :: 0/1/2 :: click :: Recent"),
    ("browser_open", "Browse a real website with DOM verification", "browse https://www.python.org"),
    ("browser_inspect", "Inspect an ARIES browser session", "inspect browser session-id"),
    ("browser_follow", "Follow a named link in a browser session", "follow browser session-id :: Downloads"),
    ("browser_fill", "Fill a labelled browser field and verify it", "fill browser session-id :: Search :: asyncio"),
    ("browser_close", "Close an ARIES browser session", "close browser session-id"),
    ("python_project", "Create and run a Python demo in VS Code", "create python demo ~/Documents/ARIES-python-demo"),
    ("build_python", "Generate and test a Python project from your request", "build python ~/Documents/ARIES-statistics :: Calculate mean and median with tests"),
    ("open_url", "Open a website", "open https://www.youtube.com"),
    ("open_path", "Open a file or folder", "open ~/Documents"),
    ("search_web", "Search the web in the browser", "search web for Linux desktop automation"),
    ("research", "Research news with source links", "research artificial intelligence"),
    ("read_article", "Read and summarize a public article", "read article https://www.kernel.org/"),
    ("processes", "Show running applications and processes", "show processes"),
    ("refresh_news", "Collect news from enabled sources", "refresh news"),
    ("brief", "Build a morning briefing", "build my brief"),
    ("health", "Run a system health check", "run system health"),
    ("system", "Show live system measurements", "system status"),
    ("services", "Show background services and what is running", "show services"),
    ("service_control", "Start, stop or restart one allowed background service", "restart service aries-voice"),
    ("disk", "Show disk space and the biggest folders in your home", "disk usage"),
    ("package_info", "Check whether a program is installed and which version", "is firefox installed"),
    ("learning_eval", "Compare versions of task experience retrieval", "evaluate learning"),
    ("evaluation", "Evaluate recorded task outcomes and code repairs", "evaluate tasks"),
    ("list_apps", "List installed applications", "list apps"),
    ("find_files", "Find files by name", "find files README"),
    ("list_folder", "List a folder", "list folder ~/Documents"),
    ("read_file", "Read a text file", "read file ~/Documents/notes.txt"),
    ("create_folder", "Create a folder", "create folder ~/Documents/ARIES-demo"),
    ("create_file", "Create a text file without overwriting", 'create file ~/Documents/ARIES-demo/note.txt :: Hello from ARIES'),
    ("move_file", "Move or rename a file without overwriting", "move file ~/Documents/ARIES-demo/note.txt to ~/Documents/ARIES-demo/renamed.txt"),
    ("trash_file", "Move a file to recoverable Trash", "trash file ~/Documents/ARIES-demo/renamed.txt"),
    ("install_app", "Install an application from the Snap store", "install VS Code"),
    ("remember", "Remember an explicit personal fact", "remember My project is ARIES"),
    ("play_music", "Find a song or video and play it in your own browser", "play music Bohemian Rhapsody"),
    ("media_control", "Play, pause or skip whatever is playing", "pause music"),
    ("set_volume", "Set or change the machine's output volume", "volume 30"),
    ("say", "Answer out loud in Macedonian or English", "say Готово"),
    ("abilities", "Say what ARIES can and cannot do, and how it knows", "what can you do"),
    ("can_you", "Answer honestly whether one specific request is possible", "can you read my screen"),
    ("read_screen", "Read what is on the screen", "what is on my screen"),
    ("screenshot", "Take a screenshot of the screen", "take a screenshot"),
    ("clipboard_read", "Read what is on the clipboard", "read clipboard"),
    ("clipboard_write", "Put text on the clipboard, replacing what was there", "copy Здраво свету to clipboard"),
    ("editable_fields", "List an application's editable text controls", "editable fields in app gedit"),
    ("type_text", "Type into one reviewed editable control of an application", "type into app gedit :: 0/1/2 :: insert :: Здраво"),
    ("network_status", "Check the connection and whether the internet is actually reachable", "am I online"),
    ("wifi_list", "List visible wifi networks and which are already saved", "list wifi"),
    ("wifi_connect", "Bring up an already-saved wifi network; never accepts a password", "connect to Juninho-2.4G"),
    ("brightness", "Read the screen brightness", "brightness"),
    ("set_brightness", "Set or change the screen brightness", "brightness 40"),
)
INSTALLATION = Path(__file__).resolve().parents[2]   # ARIES's own tree; see checked_path
SENSITIVE = {"trash_file", "install_app", "move_file", "browser_fill", "ui_action", "wifi_connect", "service_control", "clipboard_write", "type_text"}
WRITES = {"open_path", "create_folder", "create_file", "move_file", "trash_file", "install_app", "python_project", "browser_open", "browser_follow", "browser_fill", "browser_close"}
WRITES.add("ui_action")
WRITES.add("build_python")
WEBSITES = {"gmail": "https://mail.google.com", "youtube": "https://www.youtube.com", "github": "https://github.com", "google": "https://www.google.com"}
INSTALLS = {"vscode": ("code", True), "pycharm": ("pycharm", True), "firefox": ("firefox", False), "vlc": ("vlc", False), "gimp": ("gimp", False)}

def catalogue():
    return [{"id": k, "title": title, "example": example,
             "confirmation": k in SENSITIVE} for k, title, example in CATALOGUE]

def _arg(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value

# Spoken service verbs, and a systemd unit name as a person says it: dots allowed
# inside, never at the end, so the full stop Whisper appends stays punctuation.
VERB = (r"(restart|start|stop|рестартирај|restartiraj|престартувај|prestartuvaj|стартувај|startuvaj|"
        r"вклучи|vklu[cč]i|vkluchi|запри|zapri|исклучи|isklu[cč]i|iskluchi|изгаси|izgasi)")
UNIT = r"[A-Za-z0-9](?:[A-Za-z0-9@:_-]|\.(?=[A-Za-z0-9])){0,120}"


def _match(text):
    text = text.strip()
    patterns = (
        ("agent_task", r"(?:do task|napravi zadaca|направи задача)\s+(.+)$", ("task",)),
        # SYSTEM ADMINISTRATION. Three shapes for service_control, and the reason
        # there are three: a bare "start X" has to stay an application. Only the
        # noun "service", an explicit unit suffix, or an aries-* name makes a
        # request unmistakably about systemd.
        ("service_control", VERB + r"\s+(?:(?:the|го|ја)\s+)?(?:service|сервис|сервисот|услуга|услугата)"
                            r"\s+(?:(?:the|го|ја)\s+)?(" + UNIT + r")[\s.!?,;:…]*$", ("action", "unit")),
        ("service_control", VERB + r"\s+(?:(?:the|го|ја)\s+)?(" + UNIT +
                            r"\.(?:service|timer|socket|target|path|mount|slice|scope))"
                            r"(?:\s+(?:service|сервис))?[\s.!?,;:…]*$", ("action", "unit")),
        ("service_control", VERB + r"\s+(?:(?:the|го|ја)\s+)?(aries(?:[A-Za-z0-9_-]|\.(?=[A-Za-z0-9])){0,60})"
                            r"(?:\s+(?:service|сервис))?[\s.!?,;:…]*$", ("action", "unit")),
        ("services", r"(?:(?:show|list|check|прикажи|прикази|излистај|провери)\s+)?"
                     r"(?:(?:running|background|системски)\s+)?"
                     r"(?:services|systemd(?:\s+units)?|сервиси(?:те)?|услуги(?:те)?)"
                     r"(?:\s+(?:status|статус))?[\s.!?,;:…]*$", ()),
        ("disk", r"(?:(?:show|check|how much|прикажи|провери|колку)\s+)?"
                 r"(?:disk(?:\s+(?:usage|space|is\s+used))?|storage|free\s+space|дискот|"
                 r"простор(?:\s+на\s+дискот)?|место(?:\s+на\s+дискот)?|искористеност\s+на\s+дискот)"
                 r"(?:\s+(?:имам|има|остана|left))?[\s.!?,;:…]*$", ()),
        # "дали е инсталиран X" and "is X installed" are questions about a package,
        # not requests to install one — install_app owns the imperative.
        ("package_info", r"(?:дали\s+)?(?:е\s+|ми\s+е\s+)?(?:го\s+|ја\s+)?(?:имам\s+)?инсталиран(?:о|а|и)?"
                         r"\s+(?:the\s+)?(" + UNIT + r")[\s?.!,;:…]*$", ("package",)),
        ("package_info", r"(?:is|does)?\s*(?:the\s+)?(" + UNIT + r")\s+"
                         r"(?:installed|инсталиран(?:о|а)?)[\s?.!,;:…]*$", ("package",)),
        ("package_info", r"(?:check package|package|which version of|what version of|"
                         r"верзија на|verzija na|која верзија на)\s+(" + UNIT + r")[\s?.!,;:…]*$", ("package",)),
        ("build_python", r"(?:build python|napravi programa)\s+(.+?)\s*::\s*(.+)$", ("path", "task")),
        # Self-knowledge. Above everything, because "можеш ли да прочиташ фајл"
        # is a question ABOUT a capability, not a request to use it, and the
        # capability patterns below would happily answer the wrong one.
        ("abilities", r"(?:what can you do|what are you able to do|what can i ask(?: you)?|"
                      r"(?:list|show)(?: me)? your (?:capabilities|abilities)|"
                      r"што можеш(?:\s+да\s+(?:правиш|направиш))?|што знаеш(?:\s+да\s+правиш)?|"
                      r"што умееш|кои се твоите способности|"
                      r"shto mozes|sto mozes|shto znaes|kolku mozes)[\s.!?,;:…]*$", ()),
        ("can_you", r"(?:can you|are you able to|do you know how to|можеш ли(?:\s+да)?|"
                    r"знаеш ли(?:\s+да)?|mozes li(?:\s+da)?|znaes li(?:\s+da)?)\s+(.+)$", ("request",)),
        # Clipboard and typing, also above read_file: "прочитај го клипбордот"
        # is otherwise taken as a request to read a FILE called клипборд.
        ("clipboard_read",
         r"(?:(?:read|show|paste|прочитај|покажи|прикажи)(?:\s+(?:me|ми|го|it))*\s+)?(?:the\s+)?"
         r"(?:clipboard|клипборд(?:от)?)[\s.!?,;:…]*$"
         r"|(?:what(?:'s| is)\s+(?:on|in)\s+(?:the\s+)?clipboard"
         r"|што\s+(?:има|е)\s+(?:на|во)\s+(?:го\s+)?клипборд(?:от)?)[\s.!?,;:…]*$", ()),
        ("clipboard_write",
         r"(?:copy|put|place|копирај|стави|зачувај)\s+(?:го\s+)?(.+?)\s+"
         r"(?:to|on|into|во|на)\s+(?:the\s+|го\s+)?(?:clipboard|клипборд(?:от)?)[\s.!?,;:…]*$", ("text",)),
        ("clipboard_write",
         r"(?:copy (?:to|into) clipboard|копирај (?:во|на) клипборд(?:от)?)\s*:?\s*(.+)$", ("text",)),
        ("editable_fields",
         r"(?:editable fields(?:\s+in)?(?:\s+app)?|fields in app|полиња(?:\s+за\s+пишување)?\s+во)"
         r"\s+(?:app\s+)?(.+)$", ("app",)),
        ("type_text",
         r"(?:type into app|type in app|впиши во апликација|напиши во апликација)\s+(.+?)\s*::\s*"
         r"([\d/]+)\s*::\s*(insert|replace)\s*::\s*(.+)$", ("app", "node", "mode", "text")),
        # Before read_file, and that ordering is the whole point: "прочитај го
        # екранот" otherwise parses as a request to read a FILE called "го
        # екранот", and "кажи што има на екранот" would be read back aloud
        # instead of answered. Neither pattern captures a group — the screen is
        # the only target there is.
        ("read_screen", r"(?:(?:кажи(?:\s+ми)?|tell\s+me)\s+)?"
                        r"(?:what(?:'s| is| are)?\s+(?:on|showing\s+on)\s+(?:my |the |this )?screen(?:\s+right\s+now)?|"
                        r"what\s+do\s+you\s+see(?:\s+on\s+(?:my|the)\s+screen)?|"
                        r"read\s+(?:my |the )?screen|read\s+what(?:'s| is)\s+on\s+(?:my |the )?screen|"
                        r"што\s+(?:има|е|пишува|се\s+гледа)\s+на\s+(?:мојот\s+|тој\s+)?екранот?|"
                        r"што\s+гледаш(?:\s+на\s+екранот?)?|прочитај\s+(?:го\s+)?екранот?|"
                        r"shto\s+ima\s+na\s+ekranot?|sto\s+ima\s+na\s+ekranot?|"
                        r"procitaj\s+(?:go\s+)?ekranot?|shto\s+gledas)[\s.!?,;:…]*$", ()),
        ("screenshot", r"(?:(?:take|grab|make|capture|get)\s+)?(?:a\s+|the\s+|my\s+)?"
                       r"(?:screen\s?shot(?:\s+of\s+(?:my|the)\s+screen)?|picture\s+of\s+(?:my|the)\s+screen|"
                       r"capture\s+(?:my\s+|the\s+|this\s+)?screen|"
                       r"(?:сликај|фотографирај|slikaj|fotografiraj)\s+(?:го\s+)?екранот?|"
                       r"(?:направи\s+)?слика\s+од\s+екранот?|"
                       r"slikaj\s+(?:go\s+)?ekranot?|(?:napravi\s+)?slika\s+od\s+ekranot?)[\s.!?,;:…]*$", ()),
        ("ui_action", r"activate app\s+(.+?)\s*::\s*([\d/]+)\s*::\s*(.+?)\s*::\s*(.+)$", ("app", "node", "action", "expected")),
        ("browser_open", r"(?:browse|otvori vo browser|отвори во browser)\s+(https?://\S+)$", ("url",)),
        ("browser_inspect", r"inspect browser\s+(\S+)$", ("session",)),
        ("browser_follow", r"follow browser\s+(\S+)\s*::\s*(.+)$", ("session", "label")),
        ("browser_fill", r"fill browser\s+(\S+)\s*::\s*(.+?)\s*::\s*(.+)$", ("session", "label", "value")),
        ("browser_close", r"close browser\s+(\S+)$", ("session",)),
        ("inspect_app", r"(?:inspect app|inspect application|proveri aplikacija|прочитај контроли)\s+(.+)$", ("app",)),
        ("python_project", r"(?:create python demo|napravi python proekt|направи python проект)\s+(.+)$", ("path",)),
        ("read_article", r"(?:read article|summarize|sumiraj|procitaj vest|прочитај вест)\s+(https?://\S+)$", ("url",)),
        ("create_file", r"(?:create file|napravi fajl|направи фајл)\s+(.+?)\s*::\s*(.*)$", ("path", "content")),
        ("move_file", r"(?:move file|rename file|premesti|премести)\s+(.+?)\s+(?:to|vo|во)\s+(.+)$", ("path", "destination")),
        ("create_folder", r"(?:create folder|mkdir|napravi folder|направи папка)\s+(.+)$", ("path",)),
        ("trash_file", r"(?:trash file|delete file|izbrisi|izbrishi|избриши)\s+(.+)$", ("path",)),
        ("read_file", r"(?:read file|procitaj(?:\s+fajl)?|прочитај(?:\s+фајл)?)\s+(.+)$", ("path",)),
        ("list_folder", r"(?:list folder|show folder|prikazi folder|прикажи папка)\s+(.+)$", ("path",)),
        ("find_files", r"(?:find files?|najdi fajl|најди фајл)\s+(.+)$", ("query",)),
        ("search_web", r"(?:search web for|search for|prebaraj|пребарај)\s+(.+)$", ("query",)),
        ("install_app", r"(?:install|download|instaliraj|simni|инсталирај|симни)\s+(.+)$", ("app",)),
        ("remember", r"(?:remember|zapamti|запамти)\s+(.+)$", ("text",)),
        # Playback and volume, in both languages. Each captures the verb that
        # was actually said, because the executor needs to know WHICH of them it
        # was — a pattern with no group produces no arguments at all.
        # Speech recognition ends utterances with punctuation ("pause."), so it
        # is allowed at the end; without that only typed commands ever matched.
        ("media_control", r"(pause|пауза|pauza|стоп|stop|паузирај|запри|next|следна|sledna|прескокни|"
                          r"previous|претходна|prethodna|resume|continue|продолжи|prodolzi)"
                          r"(?:\s+(?:music|музика|песна|песната|video|видео|song|track|ja|ја|го|it))?[\s.!?,;:…]*$", ("action",)),
        # A bare "play" / "пушти го" resumes what is loaded; "play X" is play_music below.
        ("media_control", r"(play|пушти|pusti)(?:\s+(?:it|го|ја|go|ja))?[\s.!?,;:…]*$", ("action",)),
        ("set_volume", r"(?:volume|звук|глас|jacina|јачина)\s+(?:на\s+)?(\d{1,3})\s*%?[\s.!?,;:…]*$", ("level",)),
        ("set_volume", r"(намали|namali|turn down|lower|зголеми|zgolemi|turn up|raise|засили|"
                       r"mute|тивко|unmute)(?:\s+(?:го\s+)?(?:звукот|гласот|volume|sound|音))?[\s.!?,;:…]*$", ("level",)),
        # Connectivity and screen brightness. "Connected" and "online" are
        # different questions, and network_status answers the second one.
        ("network_status", r"(?:am i (?:online|connected)|is (?:the )?internet (?:working|up|on)|"
                           r"(?:internet|network|connection) status|"
                           r"check (?:the )?(?:internet|network|connection)|"
                           r"дали сум (?:на интернет|поврзан|поврзана)|(?:дали )?има (?:ли )?интернет|"
                           r"статус на (?:мрежа(?:та)?|интернет(?:от)?)|како е интернет(?:от)?|"
                           r"провери (?:го |ја )?(?:интернетот|мрежата|врската)|"
                           r"da li sum na internet|ima li internet|proveri internet)[\s.!?,;:…]*$", ()),
        ("wifi_list", r"(?:(?:list|show|what|which)(?: me)? (?:the )?(?:available |visible |nearby )?"
                      r"wi-?fi(?: networks?)?|wi-?fi (?:networks?|list)|scan (?:for )?wi-?fi|"
                      r"what networks are (?:there|nearby|around)|"
                      r"кои (?:wi-?fi )?мрежи (?:има|ги има|се достапни)|"
                      r"(?:прикажи|покажи|излистај)(?: ми)? (?:ги )?(?:достапните |видливите )?"
                      r"(?:wi-?fi )?мрежи|скенирај (?:за )?(?:wi-?fi|мрежи)|"
                      r"koi mrezi ima|prikazi mrezi)[\s.!?,;:…]*$", ()),
        # (?!browser\b) keeps "connect browser ..." out of the wifi namespace.
        ("wifi_connect", r"(?:connect(?: me)?(?: to)?(?: the)?(?: wi-?fi)?(?: network)?|"
                         r"join(?: the)?(?: wi-?fi)?(?: network)?|"
                         r"поврзи(?: ме| се)?(?: на| со)?(?: wi-?fi)?(?: мрежата| мрежа)?|"
                         r"префрли(?: ме| се)? на|povrzi(?: me| se)?(?: na)?)"
                         r"\s+(?!browser\b)(.+?)[\s.!?,;:…]*$", ("name",)),
        ("brightness", r"(?:(?:what(?:'s| is)? (?:the )?)?(?:screen )?brightness(?: level)?|"
                       r"how bright is (?:the |my )?screen|"
                       r"колку е (?:светлината|осветленоста|светло)|(?:светлина|осветленост)|"
                       r"kolku e svetlinata)[\s.!?,;:…]*$", ()),
        ("set_brightness", r"(?:(?:set )?(?:screen )?brightness(?: to)?|"
                           r"(?:постави |стави )?(?:светлина(?:та)?|осветленост(?:а)?)(?: на)?|"
                           r"svetlina(?:ta)?(?: na)?)\s+(\d{1,3})\s*%?[\s.!?,;:…]*$", ("level",)),
        # A step, not a target. The object word is REQUIRED here so that a bare
        # "намали" / "turn down" still reaches set_volume, which owns it.
        ("set_brightness", r"(намали|namali|turn down|lower|dim|зголеми|zgolemi|turn up|raise|засили|"
                           r"избледи|посветло|потемно)(?:\s+(?:ја\s+|го\s+|the\s+|my\s+)?"
                           r"(?:светлината|осветленоста|brightness|screen))[\s.!?,;:…]*$", ("level",)),
        # Say exactly this, in whichever language it is written in. "кажи ми …"
        # is excluded on purpose: in Macedonian that is "tell me", a question,
        # and answering it by reading the question back would be a guess. It
        # belongs to the planner, and not matching here is what sends it there.
        ("say", r"(?:say|speak|repeat|кажи(?!\s+ми\b)|kazi(?!\s+mi\b)|изговори|izgovori|повтори|povtori)\s+(.+)$", ("text",)),
        ("play_music", r"(?:play music|play song|play|пушти(?:\s+(?:ја|го))?(?:\s+песната)?|pusti(?:\s+ja)?(?:\s+pesnata)?|слушни)\s+(.+)$", ("query",)),
        ("research", r"(?:dashboard|дашборд)(?:\s+(?:about|for|za|за))?\s+(.+)$", ("query",)),
        ("research", r"(?:research|investigate|istrazi|istraži|истражи|vesti za|вести за|news about)\s+(.+)$", ("query",)),
    )
    for kind, pattern, names in patterns:
        match = re.fullmatch(pattern, text, re.I | re.S)
        if match:
            return {"capability": kind, "args": dict(zip(names, (_arg(v) for v in match.groups())))}
    exact = {"list apps": "list_apps", "installed apps": "list_apps", "aplikacii": "list_apps",
             "evaluate learning": "learning_eval", "proveri ucenje": "learning_eval", "провери учење": "learning_eval",
             "evaluate tasks": "evaluation", "proveri rezultati": "evaluation", "евалуација на задачи": "evaluation",
             "апликации": "list_apps", "show processes": "processes", "procesi": "processes", "процеси": "processes", "system status": "system", "show system status": "system", "check system status": "system", "систем": "system",
             "refresh news": "refresh_news", "scan for news": "refresh_news", "osvezi vesti": "refresh_news",
             "освежи вести": "refresh_news", "build my brief": "brief", "morning brief": "brief",
             "утрински преглед": "brief", "run system health": "health", "health check": "health"}
    if text.casefold() in exact:
        return {"capability": exact[text.casefold()], "args": {}}
    # Spoken commands arrive with sentence punctuation and, in Macedonian, with a
    # short object pronoun between the verb and the thing: "вклучи ГО YouTube".
    # Neither is part of the target, and leaving either in place meant the
    # websites table was searched for "youtube." and found nothing.
    m = re.fullmatch(r"(?:open|launch|start|run|otvori|отвори|пушти|pusti|вклучи|vklu[cč]i|"
                     r"vkluchi|стартувај|startuvaj|подигни|podigni)\s+"
                     r"(?:(?:го|ја|ги|gо|go|ja|gi)\s+)?(.+)", text, re.I)
    if m:
        target = _arg(m[1]).rstrip(" .!?,;:…")
        if target.casefold() in {"downloads", "documents", "desktop"}:
            return {"capability":"open_path","args":{"path":str(Path.home()/target.capitalize())}}
        if target.startswith(("/", "~/")):
            return {"capability": "open_path", "args": {"path": target}}
        if target.casefold() in WEBSITES:
            return {"capability": "open_url", "args": {"url": WEBSITES[target.casefold()]}}
        if target.startswith(("https://", "http://")):
            return {"capability": "open_url", "args": {"url": target}}
        if re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,}(?:/[^\s]*)?", target):
            return {"capability": "open_url", "args": {"url": "https://" + target}}
        # Decline rather than guess. "open YouTube and play the Lozano song" used
        # to become open_app("youtube and play the lozano song") — a program by
        # that name has never existed, so it failed, and worse it SUCCEEDED here,
        # which stopped the request ever reaching the planner that could have
        # handled it. An application name is one or two words; anything longer,
        # or anything joined by a conjunction, is a sentence and belongs to the
        # planner. Returning None is what routes it there.
        if len(target.split()) > 2 or re.search(r"\b(?:and|then|и|па|потоа)\b", target, re.I):
            return None
        return {"capability": "open_app", "args": {"app": target}}
    return None

# A PRONOUN IS NOT AN ARGUMENT.
#
# Measured on 2026-10-03 over a 225-utterance fixture (experiments/router-ood):
# the deterministic vocabulary committed to an action for 15 of 55 underspecified
# requests, and eleven of those actions carried an argument that was nothing but a
# pronoun — "отвори го" became open_app(app='го'), an application named after the
# Macedonian accusative clitic; "пушти нешто" became a YouTube search for the word
# "something"; "install it" became install_app(app='it').
#
# This matters more than it looks, for the same reason the sentence-shaped guard
# above matters: a match here SUCCEEDS, and succeeding is what stops the request
# ever reaching a layer that could ask which one was meant. The clitic stripping
# added on 2026-09-30 removes го/ја/ги next to the verb, but the captured argument
# still keeps them, so the clitic simply moved into the slot.
#
# Only arguments that have to NAME something are checked. `content` and `task` are
# free text and "create file note.txt :: it" is a perfectly good instruction.
REFERRING_ARGUMENTS = frozenset({'app', 'path', 'query', 'target', 'unit',
                                 'package', 'url', 'section', 'service'})
PRONOUNS_AND_DETERMINERS = frozenset({
    'го', 'ја', 'ги', 'ме', 'ми', 'му', 'им', 'не', 'ве', 'се', 'си', 'нас', 'вас',
    'него', 'неа', 'нив', 'тоа', 'тој', 'таа', 'тие', 'овој', 'оваа', 'ова', 'овие',
    'оној', 'онаа', 'она', 'оние', 'другата', 'другиот', 'другото', 'другите',
    'двете', 'обата', 'сите', 'сето', 'нешто', 'ништо', 'тука', 'таму', 'овде',
    'it', 'its', 'that', 'this', 'these', 'those', 'one', 'ones', 'both', 'them',
    'something', 'anything', 'everything', 'the', 'other', 'another', 'same',
    'all', 'there', 'here', 'mine', 'thing', 'stuff',
})


# A demonstrative in front of a common noun names nothing either: "таа папка"
# is "that folder" and became open_app(app='таа папка'). Two words at most, and
# only true demonstratives — the English article is excluded on purpose, because
# "open the calculator" does name something, and anything longer is excluded
# because "пушти ја таа песна од Лозано" names a song perfectly well.
DEMONSTRATIVES = frozenset({'тој', 'таа', 'тоа', 'тие', 'овој', 'оваа', 'ова', 'овие',
                            'оној', 'онаа', 'она', 'оние', 'другата', 'другиот',
                            'другото', 'другите', 'that', 'this', 'those', 'these',
                            'other', 'another', 'same'})


def names_nothing(value):
    """True when this argument cannot identify anything on its own."""
    words = [w for w in re.findall(r"[^\W\d_]+", str(value).casefold()) if w]
    if not words:
        return False
    if all(w in PRONOUNS_AND_DETERMINERS for w in words):
        return True
    return len(words) <= 2 and words[0] in DEMONSTRATIVES


def missing_reference(text):
    """Return an unresolved named target, never an executable authorization."""
    found = _match(text)
    if found:
        for name, value in (found.get('args') or {}).items():
            if name in REFERRING_ARGUMENTS and names_nothing(value):
                return {'capability': found['capability'], 'argument': name}
    return None


def recognize(text):
    """Match a spoken request to one capability, or decline so a planner can ask.

    Declining is a feature and it is the harder half: anything this returns is
    executed without further deliberation, so a confident wrong match is worse
    than no match at all.
    """
    found = _match(text)
    if not found:
        return None
    for name, value in (found.get("args") or {}).items():
        if name in REFERRING_ARGUMENTS and names_nothing(value):
            return None
    return found


def desktop_plan(request):
    from aries.shell.intents import screen_for
    from aries.operator.plan import Plan, _step_for
    screen = screen_for(request)
    if screen:
        return Plan(request=request, source="router", steps=[_step_for("open_section", {"section":screen})])
    found = recognize(request)
    if not found:
        return None
    from aries.operator.plan import Plan, _step_for, SECTIONS
    kind, args = found["capability"], found["args"]
    if kind == "open_app" and args["app"].casefold() in SECTIONS:
        return Plan(request=request, source="router", steps=[_step_for("open_section", {"section": args["app"].casefold()})])
    if kind == "search_web":
        kind, args = "open_url", {"url": "https://duckduckgo.com/?q=" + quote(args["query"])}
    if kind not in {"open_app", "open_url"}:
        return None
    if kind in {"open_url", "read_article"}:
        from aries.workspace.service import safe_link
        if not safe_link(args["url"]):
            return Plan(request=request, source="refused", refusal="A valid HTTP or HTTPS address is required")
    return Plan(request=request, source="router", steps=[_step_for(kind, args)])

async def checked_path(db, raw, *, write=False):
    from aries.settings import SettingsService
    from aries.sources.safety import check_path, _under
    checked = check_path(raw, excluded=await SettingsService(db).get("privacy.excluded_paths"), must_exist=False)
    path = Path(checked.location)
    # Personal file writes are confined to the user's home, never the home itself.
    if write and (not _under(str(path), str(Path.home())) or path == Path.home()):
        raise ValueError("File changes must target a specific path inside your home folder")
    # Never mutate an alias or a sensitive implementation/configuration directory.
    expanded = Path(os.path.abspath(os.path.expanduser(raw)))
    if write and any(p.is_symlink() for p in (expanded, *expanded.parents)):
        raise ValueError("File changes through symbolic links are not supported")
    if write and any(part.startswith('.') for part in path.relative_to(Path.home()).parts):
        raise ValueError("Hidden configuration paths are not targets for file changes")
    # ARIES's own source is not a file capability's business. It lives under the
    # user's home, so every other guard here waves it through: measured on
    # 2026-09-29, checked_path(write=True) allowed aries/workspace/capabilities.py
    # itself. Nothing could silently rewrite running code — create_file refuses to
    # overwrite and file.edit needs approval — but new files could appear inside
    # the package unapproved, which is a hole in the fence rather than the lock.
    # Developing ARIES belongs to a reviewed flow that runs the suite before
    # registering anything, not to "create a file at this path".
    if write and _under(str(path), str(INSTALLATION)):
        raise ValueError("ARIES's own installation is not a target for file changes")
    return path

async def command(argv, timeout=30):
    proc = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except BaseException:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 3)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        raise
    return proc.returncode, out.decode(errors="replace")[:16000], err.decode(errors="replace")[:2000]

def installed_apps():
    dirs = [Path.home()/".local/share/applications", Path("/usr/local/share/applications"), Path("/usr/share/applications"), Path("/var/lib/snapd/desktop/applications")]
    out, seen = [], set()
    for directory in dirs:
        for p in sorted(directory.glob("*.desktop")):
            if p.name in seen:
                continue
            seen.add(p.name)
            cfg = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                cfg.read(p)
                entry = cfg["Desktop Entry"]
                if entry.get("Hidden", "false") == "true" or entry.get("NoDisplay", "false") == "true":
                    continue
                out.append({"title": entry.get("Name", p.stem), "text": p.name, "source": str(p), "evidence": "Installed desktop entry"})
            except (configparser.Error, KeyError):
                continue
    return out[:200]

async def prepare(db, step):
    """Resolve exact destructive targets before displaying an immutable proposal."""
    kind, args = step["capability"], dict(step["args"])
    if kind == "ui_action":
        from aries.operator.accessibility import inspect_app
        observation = await inspect_app(args["app"])
        matches = [n for n in observation.get("nodes", []) if n.get("node") == args["node"]]
        if len(matches) != 1 or args["action"] not in matches[0].get("actions", []):
            raise ValueError("Inspect this application and choose one of its current supported control actions")
        if any(n["name"] == args["expected"] for n in observation.get("nodes", [])):
            raise ValueError("The expected element is already present; choose an observable change")
        args["target"] = matches[0]
    if kind == "browser_fill":
        from aries.workspace.browser import observe
        # Bind the proposal to the page the user actually reviewed.
        state = await observe(args["session"])
        args["expected_url"] = state["url"]
    if kind in {"python_project", "build_python"} and not shutil.which("code"):
        raise ValueError("Install VS Code before creating this development project")
    if "path" in args:
        path = await checked_path(db, args["path"], write=kind in WRITES)
        args["path"] = str(path)
        if kind in {"python_project", "build_python"} and (path.exists() or not path.parent.is_dir()):
            raise ValueError("Choose a new project folder inside an existing directory")
        if kind in {"move_file", "trash_file"}:
            stat = path.stat()
            if not path.is_file():
                raise ValueError("Move and Trash currently accept individual regular files, not folders")
            args["identity"] = [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns]
    if "destination" in args:
        args["destination"] = str(await checked_path(db, args["destination"], write=True))
        if Path(args["destination"]).exists():
            raise ValueError("The destination already exists; nothing will be overwritten")
    if kind == "install_app":
        app = args["app"].casefold().strip()
        if app in {"vs code", "visual studio code", "code"}:
            app = "vscode"
        if app not in INSTALLS:
            raise ValueError("Supported installations: " + ", ".join(INSTALLS))
        package, classic = INSTALLS[app]
        if not shutil.which("snap") or not shutil.which("pkexec"):
            raise ValueError("Installation needs Snap and the system authentication service")
        code, info, error = await command(["snap", "info", package], timeout=25)
        if code:
            raise ValueError("Package could not be checked in the store: " + error)
        revision = re.search(r"latest/stable:\s+\S+\s+\S+\s+\((\d+)\)", info)
        if not revision:
            raise ValueError("No stable package revision is available")
        args.update(package=package, classic=classic, revision=revision[1], store_info=info[:6000])
        installed, _ = await verify("install_app", args)
        args["already_installed"] = installed
    return {**step, "args": args}

async def _mutate(payload, ctx):
    from agentic_core.database.base import async_session
    kind, args = payload["capability"], payload["args"]
    async with async_session() as db:
        path = await checked_path(db, args["path"], write=True) if "path" in args else None
        if kind in SENSITIVE:
            # This internal context is supplied only after the durable proposal was approved.
            if not ctx.get("workspace_approved"):
                raise ValueError("This exact change needs a dashboard approval")
        if kind.startswith("browser_"):
            from aries.workspace import browser
            if kind == "browser_open":
                state = await browser.open_page(args["url"], str(ctx.get("workspace_goal_id") or ""))
            elif kind == "browser_follow":
                state = await browser.follow(args["session"], args["label"])
            elif kind == "browser_fill":
                if (await browser.observe(args["session"]))["url"] != args["expected_url"]:
                    raise ValueError("The browser navigated after review; submit a new request")
                state = await browser.fill(args["session"], args["label"], args["value"])
            else:
                state = await browser.close(args["session"])
            return {"success": True, "browser": state}
        if kind == "ui_action":
            from aries.operator.accessibility import inspect_app
            state = await inspect_app(args["app"], activation={"target": args["target"], "action": args["action"]})
            return {"success": bool(state.get("invoked")), "uncertain": not state.get("invoked"),
                    "details": "Control action issued; independent observation follows" if state.get("invoked") else "Control invocation could not be confirmed"}
        if kind in {"move_file", "trash_file"}:
            stat = path.stat()
            if [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns] != args.get("identity"):
                raise ValueError("The file changed after the proposal. Submit a new request")
        if kind == "build_python":
            from aries.workspace.coding import build
            record = await build(db, path, args["task"], goal_id=ctx.get('workspace_goal_id'))
            return {"success": True, "coding": record}
        elif kind == "python_project":
            from aries.workspace.python_project import create
            await create(path)
        elif kind == "create_folder":
            path.mkdir(parents=False, exist_ok=False)
        elif kind == "create_file":
            if len(args["content"].encode()) > 100000:
                raise ValueError("Text files are limited to 100 KB")
            # Exclusive creation, with no symlink following or overwrite.
            from aries.workspace.filesystem import open_nofollow
            fd = open_nofollow(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            with os.fdopen(fd, "w") as handle:
                handle.write(args["content"])
        elif kind == "move_file":
            destination = await checked_path(db, args["destination"], write=True)
            # Link/unlink is atomic no-clobber on one filesystem; cross-device moves refuse.
            os.link(path, destination, follow_symlinks=False)
            path.unlink()
        elif kind == "trash_file":
            code, _, error = await command(["gio", "trash", "--", str(path)])
            if code:
                raise ValueError(error)
        elif kind == "install_app":
            # A system authentication dialog is owned by polkit, never by ARIES.
            argv = ["pkexec", "/usr/bin/snap", "install", args["package"], "--revision", args["revision"]]
            if args["classic"]:
                argv.append("--classic")
            if os.environ.get("INVOCATION_ID"):
                argv = ["systemd-run", "--user", "--collect", "--quiet", "--wait", "--pipe",
                        "--property=RuntimeMaxSec=1200", "--", *argv]
            try:
                code, output, error = await command(argv, timeout=1200)
            except asyncio.TimeoutError:
                return {"success": False, "uncertain": True, "details": "Installer exceeded twenty minutes. Installation may still be running; verify its state before retrying."}
            if code:
                raise ValueError(error or output or "Installation was not completed")
        elif kind == "open_path":
            if not path.exists():
                raise ValueError("That path does not exist")
            code, _, error = await command(["gio", "open", str(path)], timeout=15)
            if code:
                raise ValueError(error)
        else:
            raise ValueError("Unknown file operation")
    return {"success": True, "details": "Action issued; verification follows"}

async def verify(kind, args):
    """Read back the actual target, independently of the executor's result."""
    path = Path(args["path"]) if "path" in args else None
    if kind == "build_python":
        from aries.workspace.coding import verify as verify_coding
        return await verify_coding(path)
    if kind == "ui_action":
        from aries.operator.accessibility import inspect_app
        for _ in range(4):
            observed = await inspect_app(args["app"])
            if any(n["name"] == args["expected"] for n in observed.get("nodes", [])):
                return True, "A fresh accessibility observation contains the requested new element: " + args["expected"]
            await asyncio.sleep(0.3)
        return None, "Action was invoked, but the expected new element was not independently observed"
    if kind == "python_project":
        from aries.workspace.python_project import verify as verify_project
        return await verify_project(path)
    if kind == "create_folder":
        return path.is_dir(), "Folder exists on disk"
    if kind == "create_file":
        expected = args["content"].encode()
        exists = False
        if path.is_file() and path.stat().st_size == len(expected):
            with path.open('rb') as stream:
                exists = stream.read(len(expected) + 1) == expected
        return exists, "File bytes match the requested text"
    if kind == "move_file":
        destination = Path(args["destination"])
        stat = destination.stat() if destination.exists() else None
        return bool(not path.exists() and stat and [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns] == args["identity"]), "Destination has the same file identity; original path is absent"
    if kind == "trash_file":
        # Home-file trash is on the home filesystem; check its restore metadata.
        from urllib.parse import unquote
        info = Path.home()/".local/share/Trash/info"
        matches = []
        for p in info.glob("*.trashinfo"):
            try:
                metadata = configparser.ConfigParser(interpolation=None)
                metadata.read(p)
                original = unquote(metadata["Trash Info"]["Path"])
                trashed = info.parent/"files"/p.name.removesuffix(".trashinfo")
                if original == str(path) and trashed.is_file():
                    stat = trashed.stat()
                    if [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns] == args["identity"]:
                        matches.append(p)
            except (OSError, KeyError, configparser.Error):
                continue
        return bool(not path.exists() and matches), "Original is absent and a recoverable Trash record exists"
    if kind == "install_app":
        code, output, _ = await command(["snap", "list", args["package"]], timeout=10)
        lines = [line.split() for line in output.splitlines()[1:]]
        installed = any(len(line) >= 3 and line[0] == args["package"] and line[2] == args["revision"] for line in lines)
        return code == 0 and installed, "Snap's installed-package database contains the approved package revision"
    if kind == "open_path":
        from aries.operator import desktop
        from urllib.parse import unquote
        for attempt in range(12):
            if path.is_dir():
                code, locations, _ = await command(["gdbus", "call", "--session", "--dest", "org.gnome.Nautilus", "--object-path", "/org/freedesktop/FileManager1", "--method", "org.freedesktop.DBus.Properties.Get", "org.freedesktop.FileManager1", "OpenLocations"], timeout=3)
                if code == 0 and path.as_uri() in locations:
                    return True, "Nautilus independently reports the exact folder URI as open"
            else:
                observed = await asyncio.to_thread(desktop.observe)
                if observed.windows is not None and any(path.name.casefold() in w.title.casefold() for w in observed.windows):
                    return True, "Circumstantial evidence: an application window names the requested file; its full path cannot be proven"
            await asyncio.sleep(0.4)
        return None, "The desktop accepted the open request, but its destination could not be independently confirmed"
    return False, "No verifier"

async def execute(db, step, *, approved=False):
    kind, args = step["capability"], step["args"]
    cards = []
    if kind == 'open_url':
        from aries.settings import SettingsService
        if await SettingsService(db).get('workspace.controlled_browser'):
            return await execute(db, {**step, 'capability':'browser_open'}, approved=approved)
    if kind == "play_music":
        from aries.workspace import media
        found, why = await asyncio.to_thread(media.resolve, args["query"])
        if found is None:
            return {"state": "failed", "summary": why}
        # Resolve without a browser, then hand the exact address to the ordinary
        # open_url path. That is what lets the video play in the person's OWN
        # browser — logged in, with DRM — while still letting ARIES know which
        # video it chose. Driving a controlled browser instead would let ARIES
        # click, but YouTube will not play video inside an automated one.
        card = {"title": found["title"], "text": (found["uploader"] + " · " if found["uploader"] else "") + found["url"],
                "evidence": "Resolved by yt-dlp search, metadata only"}
        await asyncio.to_thread(media.ensure_youtube_autoplay)
        # Already open? Bring that window forward instead of opening another —
        # a repeated request must not become a pile of identical windows.
        from aries.operator import desktop
        seen = await asyncio.to_thread(desktop.observe)
        existing = seen.windows_matching(found["title"], "youtube")
        if existing:
            ok, why = await asyncio.to_thread(desktop.focus_window, existing[0])
            if ok:
                return {"state": "done", "summary": "Already open: " + found["title"], "cards": [card],
                        "verification": {"met": True, "evidence": why}}
        outcome = await execute(db, {**step, "capability": "open_url", "args": {"url": found["url"]},
                                     "request": "open " + found["url"]}, approved=approved)
        outcome["cards"] = [card, *(outcome.get("cards") or [])]
        if outcome.get("state") == "done":
            outcome["summary"] = "Playing " + found["title"]
        return outcome

    if kind == "media_control":
        from aries.workspace import media
        said = str(args.get("action", "")).casefold()
        action = ("pause" if said in {"pause", "пауза", "pauza", "стоп", "stop", "паузирај", "запри"} else
                  "next" if said in {"next", "следна", "sledna", "прескокни"} else
                  "previous" if said in {"previous", "претходна", "prethodna"} else
                  "play" if said in {"resume", "continue", "продолжи", "prodolzi", "play", "пушти", "pusti"}
                  else "playpause")
        out = await asyncio.to_thread(media.control, action)
        if not out.get("ok"):
            return {"state": "failed", "summary": out.get("detail", "no player responded")}
        return {"state": "done" if out.get("verified") else "unconfirmed",
                "summary": f"{action} on {out['player']} — {out['was']} to {out['now']}",
                "verification": {"met": bool(out.get("verified")),
                                 "evidence": "PlaybackStatus re-read after the request"},
                "cards": [{"title": out["player"], "text": out["now"], "evidence": "MPRIS PlaybackStatus"}]}

    if kind == "set_volume":
        from aries.workspace import media
        said = str(args.get("level", "")).strip().casefold()
        if said.isdigit():
            out = await asyncio.to_thread(media.volume, level=int(said) / 100)
        elif said in {"mute", "тивко"}:
            out = await asyncio.to_thread(media.mute, True)
        elif said == "unmute":
            out = await asyncio.to_thread(media.mute, False)
        else:
            # A spoken "turn it down" is a step, not a target. A tenth of full
            # scale is roughly one press of a volume key, which is what the
            # request actually means.
            down = said in {"намали", "namali", "turn down", "lower"}
            out = await asyncio.to_thread(media.volume, delta=-0.10 if down else 0.10)
        if not out.get("ok"):
            return {"state": "failed", "summary": out.get("detail", "volume unavailable")}
        if "muted" in out:
            return {"state": "done" if out.get("verified") else "unconfirmed",
                    "summary": "Muted" if out["muted"] else "Unmuted",
                    "verification": {"met": bool(out.get("verified")), "evidence": "wpctl re-read"}}
        return {"state": "done" if out.get("verified") else "unconfirmed",
                "summary": f"Volume {out['was']:.2f} to {out['volume']:.2f}",
                "verification": {"met": bool(out.get("verified")), "evidence": "wpctl re-read after set"},
                "cards": [{"title": "Output volume", "text": f"{out['volume']*100:.0f}%", "evidence": "PipeWire"}]}

    if kind in {"abilities", "can_you"}:
        from aries.workspace import introspection
        if kind == "can_you":
            # The real parser answers this, so the answer and the behaviour
            # cannot disagree. A question it cannot place is reported as going to
            # the planner, which is true, rather than as a refusal.
            verdict = await asyncio.to_thread(introspection.can, args["request"])
            spoken = {"yes": "Yes", "maybe": "Probably, as a task", "unclear": "I did not catch that"}
            return {"state": "done", "summary": f"{spoken[verdict['answer']]} \u2014 {verdict['detail']}",
                    "cards": [{"title": verdict.get("title") or "Not one single capability",
                               "text": verdict["detail"],
                               "evidence": "Answered by running the same parser the command bar uses"}]}
        seen = await asyncio.to_thread(introspection.report)
        cards = [{"title": group["area"],
                  "text": ", ".join(c["title"] for c in group["capabilities"]),
                  "evidence": f"{len(group['capabilities'])} capabilities, read from the catalogue"}
                 for group in seen["abilities"]["spoken"]]
        cards += [{"title": "Cannot: " + limit["limit"], "text": limit["why"],
                   "evidence": limit["kind"] + "; " + limit["changeable"]} for limit in seen["limits"]]
        cards += [{"title": "Ready: " + name, "text": state["detail"],
                   "evidence": "live check at the moment you asked"} for name, state in seen["readiness"].items()]
        return {"state": "done", "summary": seen["summary"], "cards": cards,
                "verification": {"met": True,
                                 "evidence": "every item derived from the live catalogue, registry and "
                                             "subsystem checks, not from a written list"}}

    if kind in {"clipboard_read", "clipboard_write", "editable_fields", "type_text"}:
        from aries.workspace import input_capabilities as text_input
        if kind == "clipboard_read":
            return await text_input.voice_clipboard_read()
        if kind == "clipboard_write":
            return await text_input.voice_clipboard_write(args["text"])
        if kind == "editable_fields":
            observed = await text_input.editable_targets({"app": args["app"]}, {})
            return {"state": "done" if observed["targets"] else "unconfirmed",
                    "summary": ("%d editable control(s) found; typing needs one of these node paths"
                                % len(observed["targets"])) if observed["targets"] else
                               "No editable text control is exposed by that application; a terminal never is",
                    "cards": [{"title": t["name"] or t["role"],
                               "text": "node %s \u00b7 %s \u00b7 %s \u00b7 typeable: %s"
                                       % (t["node"], t["window"] or args["app"], t["role"], t["typeable"]),
                               "evidence": "Read-only AT-SPI EditableText survey; not a command",
                               "ui_control": {"app": args["app"], "node": t["node"]}}
                              for t in observed["targets"]],
                    "observation": observed}
        return await text_input.voice_type_text(args["app"], args["node"], args["mode"], args["text"])

    if kind in {"screenshot", "read_screen"}:
        from aries.workspace import screen_capabilities as screen
        try:
            if kind == "screenshot":
                shot, text = await asyncio.to_thread(screen.capture), ""
            else:
                seen = await asyncio.to_thread(screen.read)
                shot, text = seen["capture"], seen["text"]
        except (screen.ScreenError, OSError) as exc:
            # A blanked screen and a black frame both land here, with the reason.
            return {"state": "failed", "summary": str(exc)}
        measured = shot["content"]
        return {"state": "done",
                "summary": ("%d characters read from the screen" % len(text)) if text else
                           ("Screenshot %dx%d" % (shot["width"], shot["height"])),
                "cards": [{"title": "On screen now" if text else "Screen capture",
                           "text": text[:12000] if text else shot["path"],
                           "path": shot["path"], "source": shot["source"],
                           "evidence": "%dx%d, %d KB, decoded and measured: deviation %.1f over %d sampled colours"
                                       % (shot["width"], shot["height"], shot["bytes"] // 1024,
                                          measured["intensity_deviation"], measured["distinct_colours_sampled"])}],
                "verification": {"met": not measured["uniform"],
                                 "evidence": "the stored PNG was re-decoded; a uniform frame would have been refused"}}

    if kind == "network_status":
        from aries.workspace import network_capabilities as net
        state = await asyncio.to_thread(net.status)
        primary = state["primary"] or {}
        where = primary.get("ssid") or primary.get("connection") or primary.get("device") or "nothing"
        # Connected and online are different sentences. The person asked the second.
        reach = ("the internet is reachable" if state["internet_reachable"]
                 else "there is a link but the internet is NOT reachable" if state["link_up"]
                 else "there is no usable link")
        if state["nm_connectivity"] == "portal":
            reach = "a captive portal is intercepting this connection"
        addresses = state["addresses"]["ipv4"] + state["addresses"]["ipv6"]
        return {"state": "done", "summary": f"{where}: {reach}",
                "cards": [{"title": "Connection", "text": f"{where} \u00b7 {reach}",
                           "evidence": state["probes"]["scope"], "source": primary.get("device", "")},
                          {"title": "Addresses", "text": ", ".join(r["address"] for r in addresses) or "none",
                           "evidence": "ip -j addr"},
                          {"title": "Gateway and DNS",
                           "text": f"{state['gateway'] or 'no default route'} \u00b7 DNS "
                                   + (", ".join(state["dns"].get("servers") or []) or "unknown"),
                           "evidence": state["dns"].get("source", "")}]}

    if kind == "wifi_list":
        from aries.workspace import network_capabilities as net
        try:
            out = await asyncio.to_thread(net.wifi_list)
        except net.NetworkCapabilityError as exc:
            return {"state": "failed", "summary": str(exc)}
        return {"state": "done",
                "summary": f"{out['count']} networks visible, "
                           f"{sum(1 for r in out['networks'] if r['saved'])} already saved",
                "cards": [{"title": (r["ssid"] or "hidden network") + (" \u00b7 saved" if r["saved"] else ""),
                           "text": f"{r['signal']}% \u00b7 {r['security']} \u00b7 {r['frequency']}",
                           "evidence": out["scan"], "source": r["bssid"]} for r in out["networks"][:12]]}

    if kind == "wifi_connect":
        from aries.workspace import network_capabilities as net
        # Only ever an already-saved profile, activated by UUID. There is no
        # passphrase anywhere in this path: a new network is joined in GNOME's own
        # dialog, which is where a wifi password belongs.
        try:
            out = await asyncio.to_thread(net.wifi_connect, args["name"])
        except net.NetworkCapabilityError as exc:
            return {"state": "failed", "summary": str(exc)}
        if not out["accepted"]:
            return {"state": "failed", "summary": out["accept_detail"] or "NetworkManager refused the request"}
        name = out["profile"].get("ssid") or out["profile"]["name"]
        return {"state": "done" if out["verified"] else "unconfirmed",
                "summary": f"{name}: {out['was']} to {out['now']}",
                "verification": {"met": out["verified"],
                                 "evidence": "connection state re-read after activation, not the nmcli exit code"},
                "cards": [{"title": name, "text": out["now"], "evidence": "nmcli connection show",
                           "source": out["profile"]["uuid"]}]}

    if kind == "brightness":
        from aries.workspace import network_capabilities as net
        out = await asyncio.to_thread(net.brightness, None)
        if not out["controllable"]:
            # An observed absence, not a failure to observe. Name what was tried.
            return {"state": "done", "summary": "This machine has no screen brightness control",
                    "cards": [{"title": s["mechanism"], "text": s.get("unavailable") or "available",
                               "evidence": "probed directly"} for s in out["sources"]]}
        return {"state": "done", "summary": f"Brightness {out['brightness']}%",
                "cards": [{"title": "Screen brightness", "text": f"{out['brightness']}%",
                           "evidence": next(s["mechanism"] for s in out["sources"] if s["available"])}]}

    if kind == "set_brightness":
        from aries.workspace import network_capabilities as net
        said = str(args.get("level", "")).strip().casefold()
        current = await asyncio.to_thread(net.brightness, None)
        if said.isdigit():
            target = int(said)
        elif current["brightness"] is None:
            return {"state": "failed", "summary": current["detail"] or "no brightness control on this machine"}
        else:
            # A spoken "dim it" is a step, not a target: ten points, one key press.
            down = said in {"\u043d\u0430\u043c\u0430\u043b\u0438", "namali", "turn down", "lower", "dim",
                            "\u043f\u043e\u0442\u0435\u043c\u043d\u043e", "\u0438\u0437\u0431\u043b\u0435\u0434\u0438"}
            target = current["brightness"] + (-10 if down else 10)
        try:
            out = await asyncio.to_thread(net.brightness, max(1, min(100, target)))
        except net.NetworkCapabilityError as exc:
            return {"state": "failed", "summary": str(exc)}
        if not out["ok"]:
            return {"state": "failed", "summary": out["detail"] or "the brightness request failed"}
        return {"state": "done" if out["verified"] else "unconfirmed",
                "summary": f"Brightness {out['was']}% to {out['brightness']}%",
                "verification": {"met": out["verified"], "evidence": out["mechanism"] + " re-read after set"},
                "cards": [{"title": "Screen brightness", "text": f"{out['brightness']}%",
                           "evidence": out["mechanism"]}]}

    if kind == "say":
        from aries import speech
        # blocking: a capability result is meant to say what happened, and only
        # a finished utterance knows whether PipeWire actually played it. The
        # voice daemon uses the non-blocking form instead — it has a microphone
        # waiting and cannot afford to sit through its own sentence.
        out = await asyncio.to_thread(speech.speak, args["text"], blocking=True)
        if not out.get("ok"):
            return {"state": "failed", "summary": out.get("detail") or "no voice is available"}
        heard = f"{out['audio_seconds']:.1f} s" if out.get("audio_seconds") else "the answer"
        return {"state": "done" if out.get("verified") else "unconfirmed",
                "summary": ("Said: " if out["state"] == "spoken" else "Started saying: ") + out["text"],
                "verification": {"met": bool(out.get("verified")), "evidence": out["detail"]},
                "cards": [{"title": out["engine"],
                           "text": f"{out['language']} · {heard} · first sound after {out['first_audio_ms']:.0f} ms"
                                   + (f" · fell back from {out['fell_back_from']}" if out.get("fell_back_from") else ""),
                           "evidence": "Synthesized locally and played through PipeWire"
                                       if not out["engine"].startswith("edge") else
                                       "Synthesized by Microsoft's speech service and played through PipeWire"}]}

    if kind in {"services", "disk", "package_info", "service_control"}:
        from aries.workspace import system_capabilities as sysadm
        ctx = {"db": db}

        def gb(n):
            return f"{n / 1_000_000_000:.1f} GB"

        if kind == "services":
            out = await sysadm.services({"scope": "both", "kind": "service"}, ctx)
            verdict = await sysadm.verify_services({"scope": "both", "kind": "service"}, out, ctx)
            summary = f"{out['count']} services across the {' and '.join(out['scopes'])} manager(s)"
            if out["count"] > 60:
                summary += " \u00b7 showing the first 60, failed and ARIES units first"
            if out["failed"]:
                summary += " \u00b7 failed: " + ", ".join(out["failed"][:5])
            for scope, why in out["unavailable"].items():
                summary += f" \u00b7 the {scope} manager could not answer: {why}"
            return {"state": "unconfirmed" if verdict["met"] is not True else "partial" if out["truncated"] or out["unavailable"] else "done", "summary": summary,
                    "verification": verdict,
                    "cards": [{"title": u["unit"],
                               "text": f"{u['active_state']}/{u['sub_state']}"
                                       + (f" \u00b7 since {u['since'][:19]}Z" if u["since"] else "")
                                       + (f" \u00b7 pid {u['main_pid']}" if u["main_pid"] else ""),
                               "evidence": f"systemctl show, {u['scope']} manager",
                               "source": u["unit_file"] or u["scope"]} for u in out["units"][:60]]}
        if kind == "disk":
            out = await sysadm.disk({}, ctx)
            verdict = await sysadm.verify_disk({}, out, ctx)
            home = out["home"]
            bound = "; truncated, so this is a lower bound" if home["truncated"] else ""
            return {"state": "unconfirmed" if verdict["met"] is not True else "partial" if home["truncated"] else "done",
                    "verification": verdict,
                    "summary": f"{out['fullest']['mountpoint']} is {out['fullest']['used_pct']}% full \u00b7 "
                               f"your home folder holds {gb(home['total_bytes'])} in {home['files']} files",
                    "cards": [{"title": f["mountpoint"],
                               "text": f"{f['used_pct']}% used \u00b7 {gb(f['available_bytes'])} free of "
                                       f"{gb(f['total_bytes'])} \u00b7 {f['filesystem']}",
                               "evidence": "os.statvfs; the root reserve is excluded", "source": f["device"]}
                              for f in out["filesystems"] if "used_pct" in f]
                             + [{"title": Path(d["path"]).name or d["path"], "text": gb(d["bytes"]), "path": d["path"],
                                 "evidence": "Bounded walk of allocated blocks" + bound} for d in home["largest"]]}
        if kind == "package_info":
            out = await sysadm.packages({"package": args["package"]}, ctx)
            verdict = await sysadm.verify_packages({"package": args["package"]}, out, ctx)
            return {"state": "done" if verdict["met"] is True else "unconfirmed",
                    "verification": verdict,
                    "summary": (out["package"] + " is installed: "
                                + ", ".join(f"{e['version']} via {e['source']}" for e in out["entries"]))
                               if out["installed"] else
                               f"{out['package']} is not installed (checked {', '.join(out['queried'])})",
                    "cards": [{"title": f"{e['name']} \u00b7 {e['source']}", "text": e["version"] + " \u00b7 " + e["status"],
                               "evidence": "dpkg-query" if e["source"] == "dpkg" else "snap list"}
                              for e in out["entries"]]}
        if not approved:
            return {"state": "held", "summary": "Changing a background service needs your approval first"}
        said = str(args.get("action", "")).casefold()
        action = ("stop" if said in {"stop", "\u0437\u0430\u043f\u0440\u0438", "zapri",
                                     "\u0438\u0441\u043a\u043b\u0443\u0447\u0438", "iskluci", "iskluči",
                                     "iskluchi", "\u0438\u0437\u0433\u0430\u0441\u0438", "izgasi"} else
                  "start" if said in {"start", "\u0441\u0442\u0430\u0440\u0442\u0443\u0432\u0430\u0458",
                                      "startuvaj", "\u0432\u043a\u043b\u0443\u0447\u0438", "vkluci",
                                      "vkluči", "vkluchi"} else "restart")
        request = {"unit": args["unit"], "action": action, "scope": "user"}
        try:
            result = await sysadm.control(request, ctx)
        except sysadm.SystemCapabilityError as exc:
            return {"state": "failed", "summary": str(exc)}
        verdict = await sysadm.verify_control(request, result, ctx)
        after, why = verdict["data"]["after"], verdict["data"]["why"]
        return {"state": "done" if verdict["met"] else "unconfirmed",
                "summary": f"{action} {result['unit']} \u2014 {result['before']['active_state']} to "
                           f"{after['active_state']}/{after['sub_state']}; {why}",
                "verification": {"met": verdict["met"], "evidence": verdict["data"]["evidence"]},
                "cards": [{"title": result["unit"], "text": f"{after['active_state']}/{after['sub_state']}",
                           "evidence": why}]}

    if kind == "learning_eval":
        from aries.workspace.learning_eval import report
        return await report(db)
    if kind == "evaluation":
        from aries.workspace.evaluation import report
        return await report(db)
    if kind == "browser_inspect":
        from aries.workspace import browser
        state = await browser.observe(args["session"])
        return {"state": "done", "summary": "Browser DOM observed", "cards": browser.cards(state), "browser": state}
    if kind == "inspect_app":
        from aries.operator.accessibility import inspect_app
        observed = await inspect_app(args["app"])
        cards = [{"title": n["name"] or n["role"], "text": n["role"] + (" · Node " + n["node"] if n.get("node") else "") + (" · Actions: " + ', '.join(n["actions"]) if n.get("actions") else ""),
                  "evidence": "Read-only AT-SPI application control; not a command",
                  "ui_control": {"app": args["app"], "node": n.get("node"), "actions": n.get("actions", [])}}
                 for n in observed.get("nodes", [])]
        complete = observed.get("available") and observed.get("controls", 0) and not observed.get("truncated") and not observed.get("errors")
        return {"state": "done" if complete else "partial" if cards else "unconfirmed",
                "summary": (f"Observed {len(cards)} accessibility nodes, including {observed.get('controls', 0)} inner elements" +
                            ("; bounded or incomplete snapshot" if not complete else "")) if cards else
                           "No accessible controls confirmed for this application; it may be closed or not expose accessibility",
                "cards": cards, "observation": observed}
    if kind == "read_article":
        from aries.workspace.reader import article
        card = await article(db, args['url'], step['request'])
        return {'state':'done','summary':'Article read and summarized by the local model','cards':[card]}
    if kind == "install_app" and args.get("already_installed"):

        met, evidence = await verify(kind, args)
        if met:
            return {"state": "done", "summary": "Already installed at the requested stable revision",
                    "verification": {"met": True, "evidence": evidence},
                    "cards": [{"title": args["app"], "text": "Already installed · revision " + args["revision"], "evidence": evidence}]}
    if kind in WRITES:
        from aries.operator.service import _arm
        from aries.settings import SettingsService
        from agentic_core.tools.calling import call_tool
        settings = SettingsService(db)
        enabled = bool(await settings.get("operator.enabled"))
        if not enabled:
            return {"state": "held", "summary": "Desktop and file actions are switched off in Operator settings"}
        _arm(enabled, max_actions_per_hour=await settings.get("operator.max_actions_per_hour"), extra_tools=TOOL_NAMES)
        result = await call_tool(db, "workspace." + kind, {"capability": kind, "args": args}, ctx={"workspace_approved": approved, "workspace_goal_id": step.get('goal_id')}, approved_proposal_id=step.get("proposal_id"), actor="workspace")
        if not result.get("success") or result.get("dry_run"):
            return {"state": "held" if result.get("gate") or result.get("dry_run") else "unconfirmed" if result.get("uncertain") else "failed", "summary": result.get("details", "Action failed"), "report": result}
        if kind.startswith("browser_"):
            from aries.workspace import browser
            state = result["browser"]
            return {"state": "done", "summary": "Browser session closed" if state.get("closed") else "Destination and rendered document verified",
                    "browser": state, "cards": browser.cards(state),
                    "verification": {"met": True, "evidence": "Observed browser context state after the requested action"}}
        met, evidence = await verify(kind, args)
        if kind == "build_python":
            record = result['coding']
            from aries.workspace.coding import editor_visible
            record['editor_window_observed'] = await editor_visible(Path(args['path'])) if record['editor_launch_accepted'] else False
            if not record['editor_window_observed']:
                evidence += ' The VS Code project window could not be confirmed.'
            return {"state": "done" if met and record['editor_window_observed'] else "partial", "summary": evidence,
                    "verification": {"met": met, "evidence": evidence}, "coding": record,
                    "cards": [{"title": "Generated Python project", "text": args['task'], "path": args['path'], "evidence": evidence},
                              {"title": "Test execution", "text": record['attempts'][-1]['output'][:4000], "evidence": f"{len(record['attempts'])} measured attempt(s); OS-isolated execution"}]}
        if kind == "python_project":
            path = Path(args["path"])
            report = json.loads((path / "run-result.json").read_text())
            cards = [
                {"title": "Python project", "text": str(path), "path": str(path), "evidence": "New project directory and source checked on disk"},
                {"title": "Execution result", "text": report["stdout"], "evidence": f"Isolated project Python process exited with code {report['returncode']}"},
                {"title": "VS Code verification", "text": evidence, "evidence": "Application observation after launch"},
            ]
        return {"state": "done" if met else "unconfirmed" if met is None else "failed", "summary": evidence if met is not False else "Verification failed: " + evidence,
                "verification": {"met": met, "evidence": evidence}, "cards": cards or [{"title": kind.replace('_', ' ').title(), "text": str(args.get("path") or args.get("package")), "evidence": evidence}]}
    if kind in {"open_app", "open_url", "search_web", "refresh_news", "brief", "health"}:
        from aries.operator import service as operator
        request = {"refresh_news": "scan for news", "brief": "build my brief", "health": "run system health"}.get(kind, step["request"])
        run = await operator.run(db, request, approve=approved, prepared_plan=step.get("operator_plan"))
        if run.verified_success and kind == "search_web":
            from aries.operator.desktop import observe
            found = False
            for _ in range(15):
                observed = await asyncio.to_thread(observe)
                found = any(args["query"].casefold() in w.title.casefold() and not w.minimised for w in (observed.windows or []))
                if found:
                    break
                await asyncio.sleep(0.4)
            if not found:
                return {"state": "unconfirmed", "summary": "A search page opened, but its window did not confirm the requested query", "operator": run.as_dict()}
            cards = [{"title": "Web search", "text": args["query"], "url": "https://duckduckgo.com/?q=" + quote(args["query"]), "evidence": "The visible browser window names the requested query (circumstantial evidence)"}]
        if run.verified_success and kind in {"refresh_news", "brief", "health"}:
            cards = await automation_cards(db, kind)
        return {"state": run.outcome, "summary": run.summary(), "operator": run.as_dict(), "cards": cards,
                "verification": {"met": True if run.verified_success else None,
                                 "unverifiable": not run.verified_success,
                                 "evidence": "Operator independent step verdicts; see operator.steps"}}
    if kind == "list_apps":
        cards = await asyncio.to_thread(installed_apps)
    elif kind == "processes":
        from aries.operator.desktop import read_processes
        rows = await asyncio.to_thread(read_processes)
        cards = [{"title": p.name, "text": f"Process ID: {p.pid}", "evidence": "Observed in this user's /proc entries"} for p in rows[:200]]
    elif kind == "find_files":
        from aries.shell.search import search_files
        from aries.settings import SettingsService
        excluded = await SettingsService(db).get("privacy.excluded_paths")
        result = await asyncio.to_thread(search_files, args["query"], excluded=excluded, limit=30)
        cards = [{"title": r["title"], "text": r["action"]["path"], "path": r["action"]["path"], "evidence": "Matching file on disk"} for r in result["results"]]
        return {"state": "partial" if result["truncated"] else "done", "summary": result["reason"] or f"{len(cards)} matching files", "cards": cards}
    elif kind in {"list_folder", "read_file"}:
        path = await checked_path(db, args["path"])
        if kind == "list_folder":
            if not path.is_dir():
                raise ValueError("That path is not a folder")
            for p in sorted(path.iterdir())[:100]:
                if p.name.startswith('.'):
                    continue
                try:
                    checked = await checked_path(db, str(p))
                except ValueError:
                    continue
                cards.append({"title": p.name, "text": "Folder" if checked.is_dir() else "File", "path": str(checked), "evidence": "Directory entry on disk"})
        else:
            if not path.is_file() or path.stat().st_size > 100000:
                raise ValueError("Read accepts a regular UTF-8 text file up to 100 KB")
            raw = path.read_bytes()
            text = raw.decode("utf-8")
            cards = [{"title": path.name, "text": text[:12000], "source": str(path), "evidence": "Read from disk" + ("; preview limited to 12000 characters" if len(text)>12000 else "")}]
        if kind == "read_file":
            import hashlib
            before = hashlib.sha256(raw).hexdigest()
            after = hashlib.sha256(path.read_bytes()).hexdigest()
            verdict = {"met": before == after, "type": "file_content_hash",
                       "evidence": "SHA-256 of complete bytes independently re-read after producing the preview",
                       "sha256": after}
        else:
            fresh = []
            for entry in sorted(path.iterdir())[:100]:
                if entry.name.startswith('.'):
                    continue
                try:
                    checked = await checked_path(db, str(entry))
                except ValueError:
                    continue
                fresh.append((entry.name, str(checked), "Folder" if checked.is_dir() else "File"))
            old = [(c["title"], c["path"], c["text"]) for c in cards]
            verdict = {"met": old == fresh, "type": "directory_entry_set",
                       "evidence": "Independent bounded directory re-read; compares names, resolved paths and types, not file contents or complete enumeration"}
        return {"state": "done" if verdict["met"] is True else "unconfirmed",
                "summary": f"{len(cards)} results" if verdict["met"] is True else "The file or folder changed during verification",
                "cards": cards, "verification": verdict}
    elif kind == "system":
        from aries.health.probes import run_all
        for probe in await run_all():
            for reading in probe.readings:
                cards.append({"title": reading.metric, "text": f"{reading.value} {reading.unit}" if reading.value is not None else reading.unavailable or "Unavailable", "evidence": "Live system probe", "source": reading.subject})
    elif kind == "remember":
        from aries.workspace.service import remember
        memory = await remember(db, args["text"])
        cards = [{"title": "Remembered", "text": memory["text"], "evidence": "Explicit user statement", "source": memory["id"]}]
    else:
        raise ValueError("Unsupported capability: " + kind)
    return {"state": "done", "summary": f"{len(cards)} results", "cards": cards}

from agentic_core.tools.base import ToolSpec
from agentic_core.tools.registry import register
from agentic_core.security.permissions import Permission
for kind in sorted(WRITES):
    register(ToolSpec(name="workspace."+kind, description=next(t for k,t,_ in CATALOGUE if k==kind), run=_mutate,
        input_schema={"capability": {"type": str, "required": True, "enum": [kind]}, "args": {"type": dict, "required": True}},
        permission=Permission.MANAGE_TOOLS, risk="medium", requires_approval=kind in SENSITIVE, side_effect=True, idempotent=False, timeout_s=1250 if kind == "install_app" else 600 if kind == "build_python" else 90 if kind in {"python_project", "ui_action"} or kind.startswith("browser_") else 30,
        tags=["workspace"]), replace=True)
TOOL_NAMES = tuple("workspace."+k for k in sorted(WRITES))

ARGUMENTS = {
    "agent_task": ("task",),
    "evaluation": (), "learning_eval": (),
    "build_python": ("path", "task"),
    "ui_action": ("app", "node", "action", "expected"),
    "browser_open": ("url",), "browser_inspect": ("session",), "browser_follow": ("session", "label"),
    "browser_fill": ("session", "label", "value"), "browser_close": ("session",),
    "inspect_app": ("app",), "python_project": ("path",),
    "open_app": ("app",), "open_url": ("url",), "open_path": ("path",),
    "search_web": ("query",), "research": ("query",), "read_article": ("url",), "processes": (),
    "refresh_news": (), "brief": (), "health": (), "system": (), "list_apps": (),
    "services": (), "disk": (),
    "service_control": ("action", "unit"),
    "package_info": ("package",),
    "find_files": ("query",), "list_folder": ("path",), "read_file": ("path",),
    "create_folder": ("path",), "create_file": ("path", "content"),
    "move_file": ("path", "destination"), "trash_file": ("path",),
    "install_app": ("app",), "remember": ("text",),
    "play_music": ("query",), "media_control": ("action",), "set_volume": ("level",),
    "say": ("text",),
    "abilities": (), "can_you": ("request",),
    "read_screen": (), "screenshot": (),
    "clipboard_read": (), "clipboard_write": ("text",),
    "editable_fields": ("app",), "type_text": ("app", "node", "mode", "text"),
    "network_status": (), "wifi_list": (), "wifi_connect": ("name",),
    "brightness": (), "set_brightness": ("level",),
}

def validate_action(kind, args):
    if kind not in ARGUMENTS or set(args) != set(ARGUMENTS[kind]):
        raise ValueError("Unknown capability or unexpected arguments")
    if any(not isinstance(v, str) or len(v)>2000 or ('\x00' in v) for v in args.values()):
        raise ValueError("Arguments must be text, at most 2000 characters each")
    if any(not args[k].strip() for k in args if k != "content"):
        raise ValueError("An action target cannot be empty")
    request = next(t for k,t,_ in CATALOGUE if k == kind) + ": " + ", ".join(args.values())
    # Desktop requests come from structured, validated values, not reparsed source text.
    if kind in {"open_url", "read_article", "browser_open"}:
        from aries.workspace.service import safe_link
        if not safe_link(args["url"]):
            raise ValueError("A valid HTTP or HTTPS URL is required")
        request = ("read article " if kind == "read_article" else "browse " if kind == "browser_open" else "open ") + args["url"]
    elif kind == "open_app":
        request = "open " + args["app"]
    elif kind == "search_web":
        request = "search web for " + args["query"]
    return {"kind": "research" if kind in {"research", "dashboard"} else "capability", "capability": kind, "args": args, "request": request}, request


async def automation_cards(db, kind):
    from sqlalchemy import select
    if kind == "brief":
        from aries.brief.models import AriesBrief
        row = (await db.execute(select(AriesBrief).order_by(AriesBrief.id.desc()).limit(1))).scalar_one_or_none()
        return [{"title": section["title"], "text": section.get("unavailable") or "\n".join(i["text"] for i in section.get("items", [])) or section.get("summary", "No items"), "evidence": "Morning Brief section", "source": f"brief:{row.id}"} for section in row.sections] if row else []
    if kind == "refresh_news":
        from aries.news.models import AriesNewsItem
        from aries.workspace.service import safe_link
        rows = (await db.execute(select(AriesNewsItem).where(AriesNewsItem.excluded_by.is_(None), AriesNewsItem.dismissed.is_(False)).order_by(AriesNewsItem.first_seen_at.desc()).limit(24))).scalars()
        return [{"title": r.title, "text": r.summary[:500], "url": r.link, "source": r.source_id, "published": r.published_at.isoformat() if r.published_at else None, "evidence": "News Radar collection"} for r in rows if safe_link(r.link)]
    from aries.automations.genome import last_run
    row = await last_run(db, "aries.health")
    if not row:
        return []
    data = row.as_dict()
    cards = [{"title": "Health check", "text": data["summary"], "evidence": "Recorded automation run", "source": f"health:{row.id}"}]
    for probe in (data.get("detail") or {}).get("probes", []):
        for reading in probe.get("readings", []):
            cards.append({"title": reading["metric"], "text": str(reading.get("value")) + " " + reading.get("unit", "") if reading.get("value") is not None else reading.get("unavailable") or "Unavailable", "evidence": "Measured by " + probe["probe"]})
    return cards

async def translate(db, request):
    """Local language parsing into the same twenty capabilities, never shell code.

    Only the user's own request enters this planner. Retrieved pages and private
    context are not allowed to supply tools, paths or outbound search queries.
    """
    from aries import intelligence
    from aries.settings import SettingsService
    from aries.operator.plan import _provider_is_local
    from agentic_core.llm import providers
    from agentic_core.llm.structured import extract_json
    settings = SettingsService(db)
    if await settings.get("operator.planner") == "router":
        return None
    await intelligence.arm(db)
    local, _ = _provider_is_local()
    if not local or not providers.available():
        return None
    vocabulary = [{"capability": k, "args": {name: "text" for name in names}} for k, names in ARGUMENTS.items()]
    prompt = ("Translate this user's request (including Macedonian) into JSON only: "
              '{"steps":[{"capability":"...","args":{...}}],"refusal":""}. '
              "Use at most six steps from this exact vocabulary: " + json.dumps(vocabulary) +
              ". Never substitute a different task for an unsupported request. Refuse unsupported work. "
              "For a goal requiring later actions to depend on earlier observations, return one agent_task with its task set to the exact original request. "
              "Do not invent URLs, filenames, file contents or facts to remember. Paths must be absolute "
              "or start with ~/. Ambiguous targets require refusal. A dashboard/research is a news topic. "
              "Supported install names: " + ", ".join(INSTALLS))
    try:
        raw = await asyncio.wait_for(providers.chat([{"role": "system", "content": prompt}, {"role": "user", "content": request}], purpose="workspace.plan"), timeout=30)
        obj = extract_json(raw)
        if not isinstance(obj, dict) or obj.get("refusal"):
            return None
        steps = obj.get("steps")
        if not isinstance(steps, list) or not 1 <= len(steps) <= 6:
            return None
        out = []
        for raw_step in steps:
            step, _ = validate_action(raw_step["capability"], raw_step["args"])
            if step['capability'] == 'agent_task' and step['args']['task'] != request:
                return None
            if step["capability"] == "open_url" and step["args"]["url"] not in request:
                # Named shortcuts have a known address; arbitrary model addresses do not.
                allowed = {url for name, url in WEBSITES.items() if re.search(r"\b"+re.escape(name)+r"\b", request, re.I)}
                if step["args"]["url"] not in allowed:
                    return None
            step["from_model"] = True
            out.append(step)
        return out
    except (Exception,):
        return None
