import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_contracts import minimal_plan
from workfactory.clients.pilot import run_stage
from workfactory.pipeline.planning_agent import review_errors


def response(message):
    return {'choices':[{'message':message}], 'usage':{'prompt_tokens':1,'completion_tokens':1}}


def tool(name, **args):
    return response({'role':'assistant','content':'','tool_calls':[{'id':name,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]})


def audit(issues=None, closures=None, verdict='pass'):
    return response({'role':'assistant','content':json.dumps({'verdict':verdict,'issues':issues or [],'closures':closures or [],'suggestions':[]})})


class PlanningTest(unittest.TestCase):
    def run_case(self, replies, turns):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        cfg={'OPENAI_MODEL':'fixture-model','_POLICY':{'plan_max_turns':turns}}
        with patch('workfactory.pipeline.planning_agent.complete',side_effect=replies) as complete:
            validation, plan=run_stage('03_plan',{'task_id':'t','intent':{},'constraints':{}},Path(folder.name),cfg,1000)
        return validation,plan,Path(folder.name)/'03_plan',complete

    def test_success_contract_and_tools(self):
        v,p,d,c=self.run_case([tool('save_plan',plan=minimal_plan()),tool('review_plan'),audit(),tool('submit_plan')],3)
        self.assertTrue(v['format_and_contract_pass'])
        self.assertEqual(json.loads((d/'parsed.json').read_text())['result'],p)
        self.assertIsNotNone(c.call_args_list[0].args[3])

    def test_submit_before_review_is_blocked(self):
        v,p,d,c=self.run_case([tool('save_plan',plan=minimal_plan()),tool('submit_plan')],2)
        self.assertIsNone(p);self.assertFalse(v['format_and_contract_pass'])
        self.assertFalse((d/'parsed.json').exists())

    def test_changes_invalidate_review(self):
        v,p,d,c=self.run_case([tool('save_plan',plan=minimal_plan()),tool('review_plan'),audit(),tool('update_plan',changes={'user_request':'changed'}),tool('submit_plan')],4)
        self.assertIsNone(p)

    def test_false_pass_and_missing_closure_block_submission(self):
        issue={'id':'i1','description':'wage ambiguity','evidence':'n1'}
        v,p,d,c=self.run_case([tool('save_plan',plan=minimal_plan()),tool('review_plan'),audit([issue],verdict='fail'),tool('review_plan'),audit(),tool('submit_plan')],4)
        self.assertIsNone(p);self.assertEqual(v['pending_issues'],[issue])
        self.assertTrue(review_errors({'verdict':'pass','issues':[issue],'closures':[],'suggestions':[]},[]))

    def test_repair_closure_allows_submission(self):
        issue={'id':'i1','description':'wage ambiguity','evidence':'n1'}
        closure={'id':'i1','status':'resolved','evidence':'n1 now defines ordinary pay'}
        v,p,d,c=self.run_case([tool('save_plan',plan=minimal_plan()),tool('review_plan'),audit([issue],verdict='fail'),tool('update_plan',changes={'user_request':'clarified'}),tool('review_plan'),audit(closures=[closure]),tool('submit_plan')],5)
        self.assertTrue(v['format_and_contract_pass'])

    def test_bad_structure_never_reaches_review(self):
        v,p,d,c=self.run_case([tool('save_plan',plan={}),tool('review_plan'),tool('submit_plan')],3)
        self.assertEqual(c.call_count,3);self.assertIsNone(p)

    def test_transport_failure_preserves_failure(self):
        with tempfile.TemporaryDirectory() as d, patch('workfactory.pipeline.planning_agent.complete',side_effect=RuntimeError('unsupported tools')):
            with self.assertRaises(RuntimeError):
                run_stage('03_plan',{'task_id':'t','constraints':{}},Path(d),{'OPENAI_MODEL':'x'},100)
            self.assertFalse(json.loads((Path(d)/'03_plan/validation.json').read_text())['format_and_contract_pass'])
            self.assertFalse((Path(d)/'03_plan/parsed.json').exists())

if __name__=='__main__':unittest.main()
