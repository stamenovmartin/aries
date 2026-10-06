"""Falsifiable probe predicates; volatile samples are explicitly fresh observations.

Directory, search and task snapshots must agree with a second read. Live system
measurements can change between reads: validate their identity and structure,
and use the fresh sample as evidence without claiming numerical agreement.
"""
import json
import math
from pathlib import Path


def finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def count(value):
    return isinstance(value,int) and not isinstance(value,bool) and value>=0


def readings(rows):
    return isinstance(rows,list) and bool(rows) and all(
        isinstance(r,dict) and isinstance(r.get('metric'),str) and r['metric']
        and (finite(r.get('value')) or (r.get('value') is None and bool(r.get('unavailable'))))
        for r in rows) and any(finite(r.get('value')) for r in rows)


def valid(kind,args,data):
    if not isinstance(data,dict) or not isinstance(data.get('observed_at'),str):return False
    if kind in {'directory_state','file_search'}:
        key,entries=('path','entries') if kind=='directory_state' else ('root','matches')
        requested=str(Path(args['path']).expanduser().resolve())
        rows=data.get(entries)
        if data.get(key)!=requested or not isinstance(rows,list) or data.get('count')!=len(rows):return False
        if not count(data.get('count')) or not isinstance(data.get('truncated'),bool):return False
        for row in rows:
            if not isinstance(row,dict) or not isinstance(row.get('path'),str):return False
            path=Path(row['path'])
            if not path.is_absolute() or '..' in path.parts or not path.is_relative_to(requested) or str(path)==requested:return False
            if kind=='directory_state' and (path.parent!=Path(requested) or row.get('name')!=path.name
                                           or not isinstance(row.get('directory'),bool)):return False
            if kind=='file_search' and (not count(row.get('size')) or not isinstance(row.get('modified_at'),str)):return False
        return True
    if kind=='task_state':
        return (data.get('task_id')==args.get('task_id') and
                data.get('state') in {'queued','running','proposed','done','answered','partial','failed',
                                      'cancelled','interrupted','held','needs_clarification'} and
                count(data.get('steps')) and isinstance(data.get('evidence_ids'),list) and
                all(isinstance(i,str) for i in data['evidence_ids']))
    if kind=='process_probe':
        rows=data.get('processes')
        return (isinstance(rows,list) and count(data.get('count')) and data['count']>=len(rows)
                and isinstance(data.get('truncated'),bool)
                and data['truncated']==(data['count']>len(rows))
                and all(isinstance(r,dict) and count(r.get('pid')) and r['pid']>0
                        and isinstance(r.get('name'),str) and bool(r['name']) for r in rows)
                and len({r['pid'] for r in rows})==len(rows))
    if kind=='storage_probe':
        rows=data.get('filesystems')
        return (data.get('probe')=='statvfs' and readings(rows)
                and all(finite(r.get('value')) and 0<=r['value']<=100 for r in rows)
                and data.get('highest') in rows
                and data['highest']['value']==max(r['value'] for r in rows))
    if kind=='system_probe':
        probes=data.get('probes')
        return (isinstance(probes,list) and bool(probes)
                and all(isinstance(p,dict) and p.get('probe') in {'cpu','memory','disk'}
                        and isinstance(p.get('ok'),bool) for p in probes)
                and {p['probe'] for p in probes}=={'cpu','memory','disk'} and len(probes)==3
                and all(readings(p.get('readings')) for p in probes if p['ok'])
                and any(p['ok'] for p in probes))
    return False


def agrees(kind,args,result,fresh):
    try:
        if not valid(kind,args,result) or not valid(kind,args,fresh):return False
        if kind in {'system_probe','storage_probe','process_probe'}:
            return True  # Fresh, validated measurements replace the old sample.
        def stable(data):
            data={k:v for k,v in data.items() if k!='observed_at'}
            for key in ('entries','matches','evidence_ids'):
                if key in data:data[key]=sorted(data[key],key=lambda v:json.dumps(v,sort_keys=True))
            return data
        return stable(result)==stable(fresh)
    except (KeyError,TypeError,ValueError,OverflowError):
        return False
