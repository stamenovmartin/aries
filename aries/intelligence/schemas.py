"""Decisions describe intent; they never authorize or contain executable commands."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

# ASK and OUT_OF_SCOPE are the two answers this vocabulary could not give until
# 2026-10-03, and their absence was measurable. Over a 225-utterance fixture
# (experiments/router-ood) confidence separated "can do" from "must not act" with
# AUC 0.642 — the best accuracy any threshold could reach was 60.9%, against 55.6%
# for a system that never acts at all. The cause was not the model: with fourteen
# intents and no way to say "none of these", a classifier must pick a wrong one,
# and it did, at confidence 1.00 — 'јави се на Марија' as SEND_EMAIL on a machine
# with no telephony, 'испечати го овој документ' as READ_EMAIL with no printer.
# UNKNOWN cannot do this job while it also means "contract-supported goal" at
# confidence 1.0 and "provider unavailable" at 0.0.
#   ASK           the request is well formed but underspecified: one question away
#   OUT_OF_SCOPE  well specified and impossible on this machine
Intent = Literal['OPEN_APP','OPEN_URL','SEARCH_WEB','READ_EMAIL','SEND_EMAIL','CALENDAR_ACTION',
                 'SYSTEM_ACTION','RESEARCH','CODING','CLASSIFY','EXTRACT','AUTOMATION','FILE_ACTION',
                 'ASK','OUT_OF_SCOPE','UNKNOWN']
Tool = Literal['none','desktop.launch','browser.open','browser.search','system.status','file.list',
               'workspace','automation','classifier','extractor']
class Decision(Strict):
    intent: Intent
    tool: Tool = 'none'
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    requires_cloud: bool = False
    estimated_complexity: Literal['simple','moderate','complex'] = 'moderate'
    reason: str = Field(max_length=600)

class Route(Decision):
    execution_level: Literal['code','local','cloud']
    source: Literal['rule','local','cache','fallback']
    blocked_reason: str = ''
    input_tokens: int | None = None
    output_tokens: int | None = None

class Request(Strict):
    text: str = Field(min_length=1, max_length=12000)
    background: bool = False

class Classification(Strict):
    category: Literal['urgent','important','normal','low']
    should_notify: bool
    should_execute: Literal[False] = False
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    reason: str = Field(max_length=600)

class Extraction(Strict):
    summary: str = Field(max_length=2000)
    topics: list[str] = Field(max_length=12)
    dates: list[str] = Field(max_length=12)


def apply_notification_policy(decision: Classification) -> Classification:
    """Conservative deterministic gate; still not notification delivery authority."""
    return decision.model_copy(update={'should_notify':False}) if decision.category=='low' else decision
