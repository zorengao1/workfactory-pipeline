import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from batch_generate import cases, run_case, StageRejected, text_stage, agent
from pilot import read_json, save


class BatchTests(unittest.TestCase):
    def test_resume_reuses_accepted_text_retry(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);path=root/'03_plan-retry-01/03_plan';path.mkdir(parents=True)
            save(path/'validation.json',{'format_and_contract_pass':True,'status':'ok'})
            save(path/'parsed.json',{'result':{'fixture':'saved plan'}})
            with patch('batch_generate.run_stage') as run:
                self.assertEqual(text_stage('03_plan',{},root,{}),{'fixture':'saved plan'})
            run.assert_not_called()

    def test_transport_resume_preserves_original_request_and_history(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);stage=root/'06_probe';stage.mkdir()
            history=[{'role':'user','content':'original visible task'}]
            save(stage/'05-request.json',{'messages':history})
            with patch('batch_generate.run_agent',return_value={'status':'ok','result':{}}) as run:
                agent('06_probe',{},root,stage,{},('outputs',))
            self.assertEqual(run.call_args.kwargs['resume_messages'],history)
            self.assertEqual(run.call_args.args[3],root/'06_probe-resume-01')
            self.assertTrue((stage/'05-request.json').exists())

    def test_matched_seeds_have_unique_ids_and_supported_resources(self):
        seeds=cases()
        self.assertEqual(len({c['task_id'] for c in seeds}),5)
        for c in seeds:
            self.assertEqual(c['constraints']['allowed_reference_formats'],[])
            self.assertNotIn('reference_file_count',c['constraints'])
            self.assertFalse(c['constraints']['external_retrieval'])

    def test_success_is_not_repeated_and_failed_attempt_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);case=cases()[0];config={'OPENAI_MODEL':'test','OPENAI_API_KEY':'secret'}
            with patch('batch_generate.attempt',side_effect=[StageRejected('bad plan'),'candidate.json']) as stage:
                run_case(case,root,config)
                run_case(case,root,config)
            self.assertEqual(stage.call_count,2)
            task=root/case['task_id']
            self.assertEqual(read_json(task/'attempt-01/status.json')['state'],'rejected')
            self.assertEqual(read_json(task/'status.json')['state'],'candidate_complete')

    def test_transport_failure_stops_case_and_redacts_secret(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);case=cases()[0];config={'OPENAI_MODEL':'test','OPENAI_API_KEY':'secret'}
            with patch('batch_generate.attempt',side_effect=RuntimeError('secret HTTP 429')) as stage:
                with self.assertRaises(RuntimeError):run_case(case,root,config)
            self.assertEqual(stage.call_count,1)
            text=(root/case['task_id']/'status.json').read_text()
            self.assertNotIn('secret',text)
            self.assertEqual(read_json(root/case['task_id']/'status.json')['state'],'error')


if __name__=='__main__':unittest.main()
