"""Payload-bound provenance checked at the final inference boundary.

Labels are supplied by trusted assemblers, never by a model's routing decision.
Unknown content stays local. This is a transport policy, not a semantic PII detector.
"""
from dataclasses import dataclass
import hashlib
import json
import re

PUBLIC = frozenset({'instruction', 'user_request', 'public', 'synthetic'})
KNOWN = PUBLIC | {'file_content', 'personal', 'secret', 'unknown'}


def digest(messages, schema):
    return hashlib.sha256(json.dumps([messages, schema], sort_keys=True,
                                    ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True)
class Provenance:
    payload_sha256: str
    data_classes: tuple[str, ...]


def bind(messages, schema, classes):
    values = tuple(sorted(set(classes)))
    if not values or not set(values) <= KNOWN:
        raise ValueError('Explicit known data classes required')
    return Provenance(digest(messages, schema), values)


def classify(messages, schema, provenance):
    if isinstance(provenance, Provenance) and provenance.payload_sha256 == digest(messages, schema):
        return frozenset(provenance.data_classes) if set(provenance.data_classes) <= KNOWN else frozenset({'unknown'})
    # Empty prompts are used by adapter checks; a schema may itself carry data.
    if not messages and not schema:
        return frozenset({'instruction'})
    return frozenset({'unknown'})


def cloud_block(classes, *, privacy_mode, send_file_contents):
    if type(privacy_mode) is not bool or type(send_file_contents) is not bool:
        raise ValueError('Inference privacy policy is unavailable')
    if privacy_mode:
        return 'Privacy mode requires local inference'
    if classes & {'secret', 'personal', 'unknown'}:
        return 'Payload contains local-only or unclassified data'
    if 'file_content' in classes and not send_file_contents:
        return 'File contents may not leave the machine'
    return None


def request_classes(text):
    """Explicit private intent is local; this is not general PII detection."""
    if re.search(r'\b(private|confidential|secret|password|credential|calendar|mail|email|medical)\b|приват|лозинк',text,re.I):
        return {'personal'}
    return {'user_request'}


def planner_classes(data, payload=None):
    """Conservative origin labels before any prompt truncation or summarization."""
    classes = {'instruction', 'user_request'}
    if payload:
        classes.update(request_classes(payload.get('goal','')))
        if any(key in payload.get('environment',{}) for key in ('windows','audio')):
            classes.add('personal')
    agent = data.get('agent') or {}
    context = agent.get('context') or {}
    if context:
        # Memories, reviews, previous goals and references are personal context.
        # Even a truncated preview must retain this label.
        meaningful = any(value for key, value in context.items()
                         if key != 'working_context') or bool((context.get('working_context') or {}).get('entities'))
        if meaningful:
            classes.add('personal')
    classes.update(agent.get('context_data_classes') or ())
    for step in data.get('steps') or []:
        if step.get('capability') in {'file.read', 'file.write'}:
            classes.add('file_content')
        else:
            # Desktop, browser sessions and system/network observations can contain
            # personal identifiers. A future public-source adapter must label them.
            classes.add('personal')
    if agent.get('private') is True:
        classes.add('personal')
    return classes
