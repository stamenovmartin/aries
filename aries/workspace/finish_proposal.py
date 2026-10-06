"""Propose completion from ordered evidence; never decide completion authority."""
from aries import flags
from aries.workspace import contracts
from aries.workspace.agent_planner import Decision


def propose(data):
    if not flags.enabled('ARIES_CONTRACT_FINISH'):return None
    agent=data.get('agent',{});contract=agent.get('contract',{})
    if not contract.get('supported') or not contract.get('requirements'):return None
    steps=data.get('steps',[])
    # If the fresh independent check fails, the planner gets a correction turn.
    if agent.get('automatic_finish_step_count')==len(steps):return None
    proof={e['evidence_id']:e for e in data.get('evidence',[]) if e.get('verified') is True}
    eligible=[]
    for step in steps:
        refs=[ref for ref in step.get('evidence_refs',[]) if ref in proof and
              proof[ref].get('step_id')==step.get('step_id') and proof[ref].get('source')==step.get('capability')]
        eligible.append(refs if step.get('verification_status')=='verified' and
                        step.get('execution_status')=='observed' else [])
    cursor=-1
    for requirement in contract['requirements']:
        found=next((i for i,s in enumerate(steps) if i>cursor and eligible[i] and
            contracts.matches(requirement,s) and contracts.evidence_matches(requirement,s.get('verification',{}))),None)
        if found is None:return None
        cursor=found
    # Include later valid alternatives too: an earlier observation may be stale.
    refs=list(dict.fromkeys(ref for group in eligible for ref in group))
    return Decision(action='finish',evidence_refs=refs)
