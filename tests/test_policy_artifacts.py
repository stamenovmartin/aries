"""Isolated offline registry acceptance; no services or model calls."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from tests._bootstrap import bootstrap
bootstrap('aries-policy-artifacts')
from aries.workspace.policy_artifacts import Registry
from aries.workspace.policy_evaluation import Trial


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'offline.sqlite'
        self.r=Registry(self.path)
        self.provenance=dict(source='a'*64,environment='b'*64,scorer='c'*64)
        self.a=self.r.policy(context_chars=4000,context_items=12)
        self.b=self.r.policy(context_chars=2000,context_items=8)
        self.fixture=self.r.fixture({'read':{'expected':'fixture bytes'}})
        self.plan=self.r.plan(self.a,self.b,self.fixture,assigned=[['read',0]],provenance=self.provenance)
        self.base=Trial('read',0,True,True,0,100,50,2,3,50.,None)
        self.r.initialize('context',self.a,actor='reviewer',reason='baseline')

    def rows(self,plan=None,base=None,candidate=None):
        plan=plan or self.plan
        return [self.r.observation(plan,arm,trial,provenance=self.provenance,raw={'verifier':'synthetic fixture'})
                for arm,trial in [('baseline',base or self.base),
                                  ('candidate',candidate or replace(self.base,tokens=80))]]

    def promote(self,evaluation,revision=0):
        return self.r.promote('context',evaluation,expected_revision=revision,
                              provenance=self.provenance,actor='reviewer',reason='reviewed fixture')

    def test_persisted_lifecycle_and_generator_evidence(self):
        rows=self.rows()
        evaluation=self.r.evaluate(self.plan,iter(rows))
        record=self.r.artifact(evaluation,'evaluation')
        self.assertEqual(record['observations'],rows)
        self.assertTrue(record['result']['eligible'])
        self.promote(evaluation)
        reopened=Registry(self.path)
        self.assertEqual(reopened.selected('context')['policy'],self.b)
        reopened.rollback('context',0,expected_revision=1,actor='reviewer',reason='withdraw candidate')
        self.assertEqual(reopened.selected('context')['policy'],self.a)
        history=reopened.history('context')
        self.assertEqual([e['action'] for e in history],['initialize','promote','rollback'])
        self.assertEqual(history[-1]['rollback_target'],0)
        self.assertTrue(all(not e['deployment_authorized'] for e in history))
        self.assertFalse(reopened.selected('context')['deployment_authorized'])
        with self.assertRaises(ValueError):self.promote(evaluation,0)  # ABA cannot reuse stale revision.

    def test_frozen_fixture_assignments_and_provenance(self):
        changed=self.r.fixture({'read':{'expected':'different'}})
        self.assertNotEqual(changed,self.fixture)
        self.assertEqual(self.r.artifact(self.plan,'plan')['fixture'],self.fixture)
        with self.assertRaises(ValueError):
            self.r.plan(self.a,self.b,self.fixture,assigned=[['absent',0]],provenance=self.provenance)
        with self.assertRaises(ValueError):
            self.r.observation(self.plan,'candidate',self.base,provenance={**self.provenance,'source':'d'*64},raw={})
        with self.assertRaises(ValueError):self.r.evaluate(self.plan,self.rows()[:1])
        rows=self.rows()
        with self.assertRaises(ValueError):self.r.evaluate(self.plan,rows+rows)
        foreign=self.r.plan(self.a,self.b,changed,assigned=[['read',0]],provenance=self.provenance)
        with self.assertRaises(ValueError):self.r.evaluate(foreign,rows)

    def test_quality_safety_telemetry_and_resource_gates(self):
        for changes in [{'verified_success':False},{'safety_violations':1},{'tokens':100},
                        {'tokens':None},{'context_tokens':None},{'tool_calls':300},{'replans':1}]:
            with self.subTest(changes=changes):
                evaluation=self.r.evaluate(self.plan,self.rows(candidate=replace(self.base,tokens=80,**changes)
                    if 'tokens' not in changes else replace(self.base,**changes)))
                self.assertFalse(self.r.artifact(evaluation,'evaluation')['result']['eligible'])
                with self.assertRaises(ValueError):self.promote(evaluation)
                self.assertEqual(self.r.selected('context')['revision'],0)

    def test_default_threshold_rejects_partial_verified_evidence(self):
        plan=self.r.plan(self.a,self.b,self.fixture,assigned=[['read',0],['read',1]],provenance=self.provenance)
        rows=self.rows(plan)
        failed=replace(self.base,seed=1,success=False,verified_success=False)
        rows+=self.rows(plan,base=failed,candidate=replace(failed,tokens=80))
        result=self.r.artifact(self.r.evaluate(plan,rows),'evaluation')['result']
        self.assertTrue(result['comparison']['admitted'])
        self.assertFalse(result['eligible'])
        self.assertIn('verified outcome threshold not met',result['blockers'])

    def test_invalid_policy_and_non_json_evidence(self):
        for chars in [True,255,5001]:
            with self.assertRaises(ValueError):self.r.policy(context_chars=chars,context_items=8)
        for raw in [{'v':float('nan')},{'v':object()},{1:'ambiguous key'}]:
            with self.assertRaises(ValueError):
                self.r.observation(self.plan,'candidate',self.base,provenance=self.provenance,raw=raw)
        with self.assertRaises(TypeError):self.r.policy(context_chars=2000,context_items=8,permissions=['write'])

    def test_gate_change_and_environment_change_refuse_promotion(self):
        evaluation=self.r.evaluate(self.plan,self.rows())
        with patch('aries.workspace.policy_artifacts.Path.read_text',return_value='changed gate'):
            with self.assertRaises(ValueError):self.promote(evaluation)
        with self.assertRaises(ValueError):
            self.r.promote('context',evaluation,expected_revision=0,
                provenance={**self.provenance,'environment':'d'*64},actor='reviewer',reason='drift')

    def test_content_corruption_detected(self):
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE artifacts SET body='{}' WHERE id=?",(self.fixture,))
        with self.assertRaises(ValueError):self.r.artifact(self.fixture,'fixture')
        with self.assertRaises(ValueError):self.r.evaluate(self.plan,self.rows())

    def test_pointer_corruption_detected(self):
        with sqlite3.connect(self.path) as db:db.execute('UPDATE selections SET policy=?',(self.b,))
        with self.assertRaises(ValueError):self.r.selected('context')
        with self.assertRaises(ValueError):self.r.history('context')

    def test_deleted_history_detected(self):
        with sqlite3.connect(self.path) as db:db.execute('DELETE FROM decisions')
        with self.assertRaises(ValueError):self.r.selected('context')
        with self.assertRaises(ValueError):self.r.initialize('context',self.a,actor='x',reason='x')

    def test_failed_transaction_leaves_no_partial_history(self):
        evaluation=self.r.evaluate(self.plan,self.rows())
        with sqlite3.connect(self.path) as db:
            count=db.execute('SELECT count(*) FROM artifacts').fetchone()[0]
            db.execute("CREATE TRIGGER fail_selection BEFORE UPDATE ON selections BEGIN SELECT RAISE(ABORT,'injected failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.promote(evaluation)
        self.assertEqual(self.r.selected('context')['revision'],0)
        self.assertEqual(len(self.r.history('context')),1)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM artifacts').fetchone()[0],count)

    def test_simultaneous_reviewers_only_one_commits(self):
        evaluation=self.r.evaluate(self.plan,self.rows())
        def attempt(_):
            try:self.promote(evaluation);return True
            except ValueError:return False
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(attempt,range(4)))
        self.assertEqual(sum(results),1)
        self.assertEqual(len(self.r.history('context')),2)
        with self.assertRaises(ValueError):
            self.r.rollback('context',0,expected_revision=2,actor='x',reason='stale')


if __name__=='__main__':unittest.main()
