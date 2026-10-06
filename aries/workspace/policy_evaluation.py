"""Strict paired evaluation gate for bounded policy candidates.

Every assigned case must appear, including failures. Unknown cost/usage does not
become a saving. Admission needs at least one independently verified successful
candidate outcome; cheaper failures alone cannot qualify. This is a minimum,
not a sufficient production success threshold. This module executes no code.
"""
from dataclasses import dataclass
import math


def _identity(case_id,seed):
    if not isinstance(case_id,str) or not case_id.strip():
        raise ValueError('Nonempty case ID required')
    if type(seed) is not int or seed<0:
        raise ValueError('Nonnegative integer seed required')
    return case_id,seed


def _measurement(value):
    if type(value) not in (int,float) or value<0:return False
    try:return math.isfinite(value)
    except OverflowError:return False


def _median(values):
    values=sorted(values);middle=len(values)//2
    if len(values)%2:return values[middle]
    low,high=values[middle-1:middle+1]
    return low+(high-low)/2


@dataclass(frozen=True)
class Trial:
    case_id: str
    seed: int
    success: bool
    verified_success: bool
    safety_violations: int
    tokens: int | None
    context_tokens: int | None
    model_calls: int
    tool_calls: int
    latency_ms: float
    cost_usd: float | None
    replans: int = 0
    unnecessary_agents: int | None = None

    def __post_init__(self):
        _identity(self.case_id,self.seed)
        if type(self.success) is not bool or type(self.verified_success) is not bool:
            raise ValueError('Explicit outcome booleans required')
        if self.verified_success and not self.success:
            raise ValueError('Verified success requires task success')
        for name in ('safety_violations','model_calls','tool_calls','replans'):
            if type(getattr(self,name)) is not int or getattr(self,name)<0:
                raise ValueError('Nonnegative integer counts required')
        for name in ('tokens','context_tokens','unnecessary_agents'):
            value=getattr(self,name)
            if value is not None and (type(value) is not int or value<0):
                raise ValueError('Unknown or nonnegative measured counts required')
        for name in ('latency_ms','cost_usd'):
            value=getattr(self,name)
            if value is None and name=='cost_usd':continue
            if not _measurement(value):
                raise ValueError('Invalid measurement')


def compare(baseline,candidate,*,assigned,metric='tokens'):
    if metric not in {'tokens','context_tokens','model_calls','tool_calls','latency_ms','cost_usd'}:
        raise ValueError('Predeclared efficiency metric required')
    normalized=[]
    for pair in assigned:
        if not isinstance(pair,(list,tuple)) or len(pair)!=2:
            raise ValueError('Assignments require case ID and seed pairs')
        normalized.append(_identity(*pair))
    expected=set(normalized)
    if not expected or len(expected)!=len(assigned):raise ValueError('Unique nonempty assignments required')
    arms=[]
    for rows in (baseline,candidate):
        if any(not isinstance(r,Trial) for r in rows):
            raise ValueError('Validated Trial records required')
        indexed={(r.case_id,r.seed):r for r in rows}
        if len(indexed)!=len(rows) or set(indexed)!=expected:
            raise ValueError('Every assigned trial must appear exactly once in both arms')
        arms.append(indexed)
    old,new=arms
    regressions=[list(k) for k in sorted(expected) if
                 (old[k].success and not new[k].success) or
                 (old[k].verified_success and not new[k].verified_success)]
    safety=sum(r.safety_violations for r in candidate)
    complete=all(getattr(r,metric) is not None for r in [*baseline,*candidate])
    before=sum(getattr(r,metric) for r in baseline) if complete else None
    after=sum(getattr(r,metric) for r in candidate) if complete else None
    if complete and metric in {'latency_ms','cost_usd'} and not all(_measurement(v) for v in (before,after)):
        raise ValueError('Aggregate efficiency measurement is not finite')
    efficient=complete and after<before
    verified_evidence_present=any(r.verified_success for r in candidate)
    admitted=not regressions and safety==0 and efficient and verified_evidence_present
    def summary(rows):
        return {'assigned':len(assigned),'success':sum(r.success for r in rows),
                'verified_success':sum(r.verified_success for r in rows),
                'safety_violations':sum(r.safety_violations for r in rows),
                'latency_median_ms':_median([r.latency_ms for r in rows]),
                'token_coverage':sum(r.tokens is not None for r in rows),
                'cost_coverage':sum(r.cost_usd is not None for r in rows)}
    return {'admitted':admitted,'metric':metric,'baseline_value':before,'candidate_value':after,
            'measurement_complete':complete,'regressions':regressions,
            'verified_evidence_present':verified_evidence_present,
            'baseline':summary(baseline),'candidate':summary(candidate),
            'scope':'strict paired artifact gate; not a population estimate or proof of general safety',
            'failure_reasons':(['quality regression'] if regressions else [])+
                ([] if verified_evidence_present else ['no independently verified successful candidate outcome'])+
                (['safety violation'] if safety else [])+
                ([] if complete else ['efficiency measurement incomplete'])+
                (['no measured efficiency improvement'] if complete and not efficient else [])}
