from aries.settings.schema import SettingDef, define
for key,default,maximum,title in (
    ('goal_max_model_calls',32,256,'Shared model call limit'),
    ('goal_max_tokens',250000,4000000,'Shared inference token budget'),
    ('goal_max_tool_calls',64,512,'Shared tool and verification limit'),
    ('goal_deadline_seconds',1800,86400,'Goal wall time limit'),
):
    define(SettingDef('workspace.'+key,int,default,title,
        'Budget shared by a root goal and all children; captured at first execution and never reset by retries.',
        'workspace',control='number',minimum=1,maximum=maximum,user_only=True))
define(SettingDef('workspace.goal_max_cost_usd',float,0.0,'Shared goal cost limit',
    'Zero leaves cost uncapped. A positive cap refuses calls without a configured price; CLI account cost is not a known price.',
    'workspace',control='number',minimum=0.0,user_only=True))
define(SettingDef('workspace.agent_max_steps', int, 8, 'Agent action budget',
                  'Maximum capability attempts for one M14 goal, including failed attempts.',
                  'workspace', control='number', minimum=1, maximum=32, user_only=True))
define(SettingDef('workspace.agent_demo_directory', str, '~/Documents/ARIES-Demo', 'Agent demo directory',
                  'The explicit ARIES demo directory named in user goals. Create it before the demo.',
                  'workspace', user_only=True))
for key, default, title, description in (
    ("auto_close_tools", True, "Close temporary agent browsers", "Close browser sessions created by a finished agent task. Explicitly opened browsing sessions remain available."),
    ("auto_close_results", True, "Close completed result windows", "Completed temporary result windows close after 45 seconds unless pinned. Results remain in Monitor."),
    ("web_search", False, "Search public news for dashboard requests", "Sends the research words you submit to Google News. Private memories stay on this machine."),
    ("enabled", True, "Goal dashboards", "Accept submitted goals and build dashboards using available capabilities."),
    ("controlled_browser", True, "Use the ARIES browser for website commands", "Open public websites in a dedicated visible session with DOM evidence. Turning this off uses the desktop's default browser."),
):
    define(SettingDef("workspace." + key, bool, default, title, description,
                      "workspace", control="toggle", user_only=True))

define(SettingDef("workspace.dashboard_enabled", bool, False, "Refresh topic dashboards automatically",
                  "Build dashboards for your configured topics on a schedule. Does not perform desktop or file actions.",
                  "workspace", control="toggle", user_only=True))
define(SettingDef("workspace.topics", list, [], "Dashboard topics",
                  "Research topics to refresh in the background; each stays a research query, never a command.",
                  "workspace", control="tags", user_only=True))
define(SettingDef("workspace.interval_minutes", int, 60, "Dashboard refresh interval",
                  "How often to collect new results for your topics.", "workspace", control="number",
                  minimum=15, maximum=10080, unit="minutes"))

define(SettingDef('workspace.ai_briefings', bool, False, 'Generate AI reading briefings',
                  'Use the configured local model to organize collected source material into readable summaries. Source coverage stays visible.',
                  'workspace', control='toggle', user_only=True))

define(SettingDef('workspace.review_retrieval', str, 'overlap-v1', 'Task experience retrieval version',
                  'Choose how previous task reviews are selected. Compare versions in Learning before switching; selecting the previous version rolls back immediately.',
                  'workspace', control='select', choices=('overlap-v1', 'focused-v2', 'semantic-v3'), user_only=True))

# ── semantic memory ─────────────────────────────────────────────────────────
# The machine write path. `privacy.remember_conversations` still governs
# whether anything at all may be kept; this governs whether ARIES decides for
# itself what was worth keeping out of it.
define(SettingDef('workspace.semantic_memory', bool, True, 'Notice what matters',
                  'Let ARIES decide for itself which of the things you say are worth remembering, and write them down without being asked. What you said is stored verbatim and separately from what ARIES concluded from it.',
                  'workspace', control='toggle', user_only=True))
define(SettingDef('workspace.memory_retrieval', str, 'semantic-v3', 'Memory retrieval version',
                  'How stored memories are selected for a request. semantic-v3 compares meaning and works across languages; the older versions compare words and miss inflected forms.',
                  'workspace', control='select', choices=('overlap-v1', 'focused-v2', 'semantic-v3'), user_only=True))
define(SettingDef('workspace.memory_embedder', str, 'e5-base-int8', 'Memory embedding model',
                  'Which sentence model turns a memory into a vector. e5-base-int8 runs locally on the CPU; bge-m3-ollama scores higher and needs ollama.',
                  'workspace', control='select', choices=('e5-base-int8', 'bge-m3-ollama'), advanced=True, user_only=True))
define(SettingDef('workspace.memory_model', str, 'qwen2.5:7b', 'Memory decision model',
                  'The local model asked, in one word, how a new statement relates to what is already stored. It never writes the memory text and never decides which of two conflicting facts is true.',
                  'workspace', control='text', advanced=True, user_only=True))
define(SettingDef('workspace.memory_redundant_above', float, 0.97, 'Redundant above',
                  'Cosine similarity at or above which a new statement is treated as already stored, with no model call. Calibrate against experiments/memory before changing.',
                  'workspace', control='slider', minimum=0.5, maximum=1.0, advanced=True, user_only=True))
define(SettingDef('workspace.memory_novel_below', float, 0.85, 'Novel below',
                  'Cosine similarity at or below which a new statement is kept outright, with no model call. Between the two thresholds the local model is asked.',
                  'workspace', control='slider', minimum=0.0, maximum=1.0, advanced=True, user_only=True))
