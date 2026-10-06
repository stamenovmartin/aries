"""ARIES learning — the loops of §16.

    medium loop   outcomes adjust preferences, slowly and with evidence
    reversal      an established preference may be taken back, under hysteresis

Importing this package registers the settings, the tables and the automation.
"""
from __future__ import annotations

from aries.learning import evidence, explain as explain_mod, feedback, history, reversal
from aries.learning import controls  # registers durable learned-value reset/undo history
from aries.learning import evidence_use  # registers durable evidence consumption receipts
from aries.learning import settings as _settings  # noqa: F401
from aries.learning.automation import AUTOMATION_ID, SPEC
from aries.learning.evidence import Slice, TopicEvidence, gather
from aries.learning.history import (
    AriesLearningChange, TargetStability, reversal_rate, stability,
)
from aries.learning.loop import (
    Proposal, apply, frozen_for, propose, run_pass, verdicts_for,
)
from aries.learning.explain import Explanation, explain, preferences
from aries.learning.feedback import AriesFeedback, Reading, answer, submit
from aries.learning.reversal import AriesReversal, POLICY_VERSION, Verdict, classify
from aries.learning.statistics import Interval, step_toward, wilson

__all__ = ["SPEC", "AUTOMATION_ID", "propose", "apply", "gather", "run_pass",
           "frozen_for", "verdicts_for", "Proposal", "TopicEvidence", "Slice",
           "history", "evidence", "reversal", "AriesLearningChange", "AriesReversal",
           "TargetStability", "stability", "reversal_rate", "classify", "Verdict",
           "POLICY_VERSION", "wilson", "step_toward", "Interval",
           "feedback", "submit", "answer", "AriesFeedback", "Reading",
           "explain", "preferences", "Explanation", "explain_mod"]
