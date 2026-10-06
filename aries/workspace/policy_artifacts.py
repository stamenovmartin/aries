"""Offline context-policy evidence registry, deliberately disconnected from runtime.

SQLite transactions couple selection with its history. Content hashes bind bytes,
not the truth/authenticity of a producer's observations. A trusted caller records
observations and explicitly reviews selection. Nothing here changes live settings,
executes a candidate, or authorizes deployment.
"""
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time

from aries.workspace.policy_evaluation import Trial,compare

METRICS={'tokens','context_tokens','model_calls','tool_calls','latency_ms','cost_usd','replans','unnecessary_agents'}
OBJECTIVES=METRICS-{'replans','unnecessary_agents'}


def _json(value):
    def validate(v):
        if v is None or type(v) in (str,bool,int):return
        if type(v) is float and math.isfinite(v):return
        if type(v) is list:
            for item in v:validate(item)
            return
        if type(v) is dict and all(type(k) is str for k in v):
            for item in v.values():validate(item)
            return
        raise ValueError('Strict finite JSON values required')
    validate(value)
    encoded=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
    if len(encoded.encode())>2_000_000:raise ValueError('Artifact exceeds two megabytes')
    return encoded


def _digest(text):return hashlib.sha256(text.encode()).hexdigest()


def _provenance(value):
    if type(value) is not dict or set(value)!={'source','environment','scorer'}:
        raise ValueError('Source, environment and scorer SHA-256 required')
    for digest in value.values():
        if type(digest) is not str or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('Invalid SHA-256')
    return value


def _identity(case,seed):
    if type(case) is not str or not case.strip() or type(seed) is not int or seed<0:
        raise ValueError('Valid case ID and nonnegative seed required')
    return case,seed


class Registry:
    def __init__(self,path):
        self.path=Path(path)
        # Explicit path; no default live database, settings registration or migration.
        with self._db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, body TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS selections (
                    name TEXT PRIMARY KEY, policy TEXT NOT NULL, revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS decisions (
                    name TEXT NOT NULL, revision INTEGER NOT NULL, artifact TEXT NOT NULL,
                    PRIMARY KEY (name,revision));
            ''')

    @contextmanager
    def _db(self,write=False):
        db=sqlite3.connect(self.path,timeout=10,isolation_level=None)
        db.row_factory=sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:db.close()

    def _put(self,db,kind,payload):
        body=_json({'kind':kind,'schema':1,'payload':payload});key=_digest(body)
        db.execute('INSERT OR IGNORE INTO artifacts VALUES (?,?,?,?)',(key,kind,body,time.time()))
        self._get(db,key,kind)
        return key

    def _get(self,db,key,kind):
        row=db.execute('SELECT kind,body FROM artifacts WHERE id=?',(key,)).fetchone()
        if not row or row['kind']!=kind or _digest(row['body'])!=key:
            raise ValueError('Missing, mismatched or altered artifact')
        value=json.loads(row['body'])
        if _json(value)!=row['body'] or value['kind']!=kind or value['schema']!=1:
            raise ValueError('Noncanonical artifact')
        return value['payload']

    def artifact(self,key,kind):
        with self._db() as db:return self._get(db,key,kind)

    def policy(self,*,context_chars,context_items):
        if type(context_chars) is not int or not 256<=context_chars<=5000:
            raise ValueError('Context size outside supported bound')
        if type(context_items) is not int or not 1<=context_items<=20:
            raise ValueError('Context item count outside supported bound')
        with self._db(write=True) as db:
            return self._put(db,'policy',{'family':'context-selection-v1',
                'context_chars':context_chars,'context_items':context_items})

    def fixture(self,cases):
        if type(cases) is not dict or not cases:raise ValueError('Nonempty fixture cases required')
        for case in cases:_identity(case,0)
        with self._db(write=True) as db:return self._put(db,'fixture',{'cases':cases})

    def plan(self,baseline,candidate,fixture,*,assigned,provenance,metric='tokens',min_verified=None,
             required_metrics=None,nonregression_metrics=None):
        if metric not in OBJECTIVES:raise ValueError('Unsupported efficiency objective')
        if baseline==candidate:raise ValueError('Distinct policies required')
        pairs=[]
        for pair in assigned:
            if type(pair) not in (list,tuple) or len(pair)!=2:raise ValueError('Invalid assignment')
            pairs.append(_identity(*pair))
        if not pairs or len(set(pairs))!=len(pairs):raise ValueError('Unique nonempty assignments required')
        minimum=len(pairs) if min_verified is None else min_verified
        if type(minimum) is not int or not 1<=minimum<=len(pairs):raise ValueError('Invalid verified outcome threshold')
        required=list(required_metrics) if required_metrics is not None else ['tokens','context_tokens','model_calls','tool_calls','latency_ms']
        guarded=list(nonregression_metrics) if nonregression_metrics is not None else ['model_calls','tool_calls','replans']
        if not set(required+guarded)<=METRICS:raise ValueError('Unknown telemetry field')
        with self._db(write=True) as db:
            self._get(db,baseline,'policy');self._get(db,candidate,'policy')
            cases=self._get(db,fixture,'fixture')['cases']
            if any(case not in cases for case,_ in pairs):raise ValueError('Assignment outside frozen fixture')
            return self._put(db,'plan',{'baseline':baseline,'candidate':candidate,'fixture':fixture,
                'assigned':[list(p) for p in pairs],'provenance':_provenance(provenance),'metric':metric,
                'min_verified':minimum,'required_metrics':sorted(set(required+[metric])),
                'nonregression_metrics':sorted(set(guarded)),
                'registry_sha256':_digest(Path(__file__).read_text()),
                'gate_sha256':_digest(Path(__file__).with_name('policy_evaluation.py').read_text())})

    def observation(self,plan,arm,trial,*,provenance,raw):
        # `raw` is caller-supplied evidence, not an authenticated verifier result.
        if arm not in {'baseline','candidate'}:raise ValueError('Unknown experiment arm')
        if not isinstance(trial,Trial):raise ValueError('Validated trial required')
        with self._db(write=True) as db:
            spec=self._get(db,plan,'plan')
            if _provenance(provenance)!=spec['provenance']:raise ValueError('Experiment environment drift')
            if [trial.case_id,trial.seed] not in spec['assigned']:raise ValueError('Unassigned observation')
            return self._put(db,'observation',{'plan':plan,'arm':arm,'policy':spec[arm],
                'trial':asdict(trial),'raw':raw,'provenance':provenance})

    def _evaluate(self,db,plan,observations):
        spec=self._get(db,plan,'plan')
        if spec['registry_sha256']!=_digest(Path(__file__).read_text()):
            raise ValueError('Registry gate changed; register a new plan')
        self._get(db,spec['baseline'],'policy');self._get(db,spec['candidate'],'policy')
        self._get(db,spec['fixture'],'fixture')
        if spec['gate_sha256']!=_digest(Path(__file__).with_name('policy_evaluation.py').read_text()):
            raise ValueError('Evaluation gate changed; register a new plan')
        arms={'baseline':[],'candidate':[]}
        for key in observations:
            row=self._get(db,key,'observation')
            if row['plan']!=plan or row['provenance']!=spec['provenance'] or row['policy']!=spec[row['arm']]:
                raise ValueError('Foreign experiment observation')
            arms[row['arm']].append(Trial(**row['trial']))
        result=compare(arms['baseline'],arms['candidate'],assigned=spec['assigned'],metric=spec['metric'])
        blockers=[]
        if result['candidate']['verified_success']<spec['min_verified']:blockers.append('verified outcome threshold not met')
        for name in spec['required_metrics']:
            if any(getattr(row,name) is None for rows in arms.values() for row in rows):blockers.append('missing required '+name)
        for name in spec['nonregression_metrics']:
            values=[[getattr(row,name) for row in arms[arm]] for arm in ['baseline','candidate']]
            if any(v is None for vs in values for v in vs):blockers.append('missing guard metric '+name)
            elif sum(values[1])>sum(values[0]):blockers.append('resource regression '+name)
        return {'comparison':result,'blockers':blockers,'eligible':result['admitted'] and not blockers,
                'deployment_authorized':False}

    def evaluate(self,plan,observations):
        observations=list(observations)
        with self._db(write=True) as db:
            result=self._evaluate(db,plan,observations)
            return self._put(db,'evaluation',{'plan':plan,'observations':list(observations),'result':result})

    def selected(self,name):
        with self._db() as db:
            row,_=self._state(db,name)
            if not row:return None
            policy=self._get(db,row['policy'],'policy')
            return {**dict(row),'configuration':policy,'deployment_authorized':False}

    def _state(self,db,name):
        current=db.execute('SELECT * FROM selections WHERE name=?',(name,)).fetchone()
        rows=db.execute('SELECT revision,artifact FROM decisions WHERE name=? ORDER BY revision',(name,)).fetchall()
        events=[];previous=None;old_policy=None
        for revision,row in enumerate(rows):
            event=self._get(db,row['artifact'],'decision')
            if (row['revision']!=revision or event['revision']!=revision or event['name']!=name or
                event['previous_event']!=previous or event['old_policy']!=old_policy):
                raise ValueError('Selection history is inconsistent')
            self._get(db,event['new_policy'],'policy')
            events.append(event);previous=row['artifact'];old_policy=event['new_policy']
        if bool(current)!=bool(events) or (current and
            (current['revision']!=len(events)-1 or current['policy']!=old_policy)):
            raise ValueError('Selection pointer does not match history')
        return current,events

    def _decision(self,db,name,policy,*,expected_revision,action,actor,reason,evaluation=None,rollback_target=None):
        if not all(type(v) is str and v.strip() for v in (name,actor,reason)):raise ValueError('Name, actor and reason required')
        current,_=self._state(db,name)
        self._get(db,policy,'policy')
        revision=current['revision'] if current else -1
        if type(expected_revision) is not int or revision!=expected_revision:raise ValueError('Stale selection revision')
        previous=db.execute('SELECT artifact FROM decisions WHERE name=? AND revision=?',(name,revision)).fetchone()
        if previous:self._get(db,previous['artifact'],'decision')
        event=self._put(db,'decision',{'name':name,'revision':revision+1,'action':action,'actor':actor,'reason':reason,
            'old_policy':current['policy'] if current else None,'new_policy':policy,'evaluation':evaluation,
            'previous_event':previous['artifact'] if previous else None,'rollback_target':rollback_target,
            'deployment_authorized':False})
        db.execute('INSERT INTO decisions VALUES (?,?,?)',(name,revision+1,event))
        db.execute('INSERT INTO selections VALUES (?,?,?) ON CONFLICT(name) DO UPDATE SET policy=excluded.policy,revision=excluded.revision',
                   (name,policy,revision+1))
        return event

    def initialize(self,name,policy,*,actor,reason):
        with self._db(write=True) as db:
            self._get(db,policy,'policy')
            return self._decision(db,name,policy,expected_revision=-1,action='initialize',actor=actor,reason=reason)

    def promote(self,name,evaluation,*,expected_revision,provenance,actor,reason):
        with self._db(write=True) as db:
            record=self._get(db,evaluation,'evaluation');spec=self._get(db,record['plan'],'plan')
            if _provenance(provenance)!=spec['provenance']:raise ValueError('Selection environment drift')
            current=db.execute('SELECT * FROM selections WHERE name=?',(name,)).fetchone()
            if not current or current['policy']!=spec['baseline']:raise ValueError('Evaluated baseline no longer selected')
            result=self._evaluate(db,record['plan'],record['observations'])
            if not result['eligible']:raise ValueError('Candidate failed the frozen evaluation criteria')
            return self._decision(db,name,spec['candidate'],expected_revision=expected_revision,action='promote',
                                  actor=actor,reason=reason,evaluation=evaluation)

    def rollback(self,name,target_revision,*,expected_revision,actor,reason):
        if type(target_revision) is not int or type(expected_revision) is not int or not 0<=target_revision<expected_revision:
            raise ValueError('Rollback requires a prior committed revision')
        with self._db(write=True) as db:
            row=db.execute('SELECT artifact FROM decisions WHERE name=? AND revision=?',(name,target_revision)).fetchone()
            if not row:raise ValueError('Unknown historical selection')
            event=self._get(db,row['artifact'],'decision');policy=event['new_policy']
            self._get(db,policy,'policy')
            return self._decision(db,name,policy,expected_revision=expected_revision,action='rollback',actor=actor,reason=reason,
                                  rollback_target=target_revision)

    def history(self,name):
        with self._db() as db:
            return self._state(db,name)[1]
