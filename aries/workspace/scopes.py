"""Executor-enforced, subtractive grants for temporary runtime specialists."""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import time
from pydantic import BaseModel, ConfigDict, Field

_active = ContextVar('aries_capability_grant',default=None)


class Grant(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,frozen=True)
    root_id: str = Field(min_length=1,max_length=64)
    capabilities: list[str] = Field(min_length=1,max_length=58)
    paths: list[str] = Field(default_factory=list,max_length=16)
    task_ids: list[str] = Field(default_factory=list,max_length=16)
    expires_at: float
    read_only: bool = True

    def validate_registry(self):
        from aries.workspace.registry import registry
        for name in self.capabilities:
            cap=registry.get(name)
            if self.read_only and (cap.effect!='read' or cap.requires_approval):
                raise PermissionError('A read-only specialist cannot receive '+name)
        return self


def current():
    return _active.get()


@contextmanager
def use(grant):
    grant=Grant.model_validate(grant).validate_registry()
    parent=current()
    if parent and (grant.root_id!=parent.root_id or not set(grant.capabilities)<=set(parent.capabilities)
                   or not set(grant.paths)<=set(parent.paths) or not set(grant.task_ids)<=set(parent.task_ids)
                   or grant.expires_at>parent.expires_at or (parent.read_only and not grant.read_only)):
        raise PermissionError('A specialist cannot widen inherited authority')
    token=_active.set(grant)
    try:yield grant
    finally:_active.reset(token)


def enforce(cap,args):
    grant=current()
    if grant is None:return
    if time.time()>=grant.expires_at:
        raise PermissionError('Specialist grant expired')
    if cap.name not in grant.capabilities or (grant.read_only and cap.effect!='read'):
        raise PermissionError('Capability outside specialist grant')
    # Exact resources, not string prefixes; ordinary path policy and nofollow I/O
    # still run afterwards. Resolve at use time to detect changed symlinks.
    for key in ('path','source','destination'):
        value=args.get(key)
        if value is not None:
            allowed={str(Path(p).expanduser().absolute()) for p in grant.paths}
            lexical=str(Path(value).expanduser().absolute())
            resolved=str(Path(value).expanduser().resolve())
            if lexical not in allowed or resolved not in allowed:
                raise PermissionError('Path outside specialist grant')
    if 'task_id' in args and args['task_id'] not in grant.task_ids:
        raise PermissionError('Task outside specialist grant')
    # Sessions, URLs and focused-desktop reads require a different resource grant.
    if any(key in args for key in ('url','session','window_id')):
        raise PermissionError('This specialist has no browser or desktop resource grant')
