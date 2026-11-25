import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import json

from workfactory.runtime.tool_runtime import Broker, run_agent


class FileBoundaryTests(unittest.TestCase):
    def test_traversal_absolute_and_symlink_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); root=base/'task'; root.mkdir()
            (root/'link').symlink_to(base)
            b=Broker(root,base/'logs',('outputs',))
            for path in ['../secret','/etc/passwd','link/secret']:
                with self.assertRaises(ValueError): b.path(path)

    def test_probe_can_only_write_output_and_cannot_list_hidden_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); root=base/'task'; root.mkdir()
            (base/'plan.json').write_text('hidden')
            (root/'REQUEST.txt').write_text('visible')
            b=Broker(root,base/'logs',('outputs',))
            with self.assertRaises(ValueError):
                b.call('write_text',{'path':'REQUEST.txt','text':'changed'})
            b.call('write_text',{'path':'outputs/report.txt','text':'result'})
            self.assertEqual(b.call('list_files',{})['files'],['REQUEST.txt','outputs/report.txt'])
            self.assertEqual((root/'REQUEST.txt').read_text(),'visible')

    def test_readonly_reviewer_cannot_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=Broker(Path(tmp),Path(tmp)/'logs')
            with self.assertRaises(ValueError):
                b.call('write_text',{'path':'outputs/report.txt','text':'result'})

    def test_structured_submission_is_validated_without_parsing_prose(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);root=base/'task';root.mkdir()
            parsed={'task_id':'t','status':'blocked','result':None,'issues':['missing required input']}
            response={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':'not the submitted result',
                'tool_calls':[{'id':'submit1','type':'function','function':{'name':'submit_result','arguments':json.dumps(parsed)}}]}}]}
            inputs={'task_id':'t','environment':{'user_request':'task','reference_files':[],'resources':{}},'workspace':{}}
            with patch('workfactory.runtime.tool_runtime.complete',return_value=response):
                result=run_agent('06_probe',inputs,root,base/'logs',{'OPENAI_MODEL':'test','OPENAI_API_KEY':'secret'})
            self.assertEqual(result,parsed)
            self.assertEqual(json.loads((base/'logs/submission.json').read_text())['method'],'submit_result')

    def test_teacher_submission_requires_successful_output_readback(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);root=base/'task';(root/'outputs').mkdir(parents=True)
            (root/'outputs/report.xlsx').write_bytes(b'test fixture')
            parsed={'task_id':'t','status':'ok','result':{'deliverables':['outputs/report.xlsx'],
                'summary':'done','assumptions':[],'unmet_requirements':[]},'issues':[]}
            def response(name,args,call_id):
                return {'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
                    'tool_calls':[{'id':call_id,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}}]}
            responses=[response('submit_result',parsed,'early'),response('read_workbook',{'path':'outputs/report.xlsx'},'read'),response('submit_result',parsed,'final')]
            inputs={'task_id':'t','environment':{'user_request':'task','reference_files':[],'resources':{}},'workspace':{}}
            with patch('workfactory.runtime.tool_runtime.complete',side_effect=responses),patch.object(Broker,'workbook',return_value={'inspection':'test'}):
                result=run_agent('09_teacher',inputs,root,base/'logs',{'OPENAI_MODEL':'test','OPENAI_API_KEY':'secret'},('outputs',))
            self.assertEqual(result,parsed)
            self.assertIn('must be reopened',json.loads((base/'logs/00-tool-early.json').read_text())['error'])

    def test_invalid_number_format_is_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);root=base/'task';root.mkdir()
            b=Broker(root,base/'logs',('outputs',))
            sheets=[{'name':'Data','rows':[['count'],[8]],'formats':[{'range':'A2','format':'wrap'}]}]
            with patch('workfactory.runtime.tool_runtime.subprocess.run') as process:
                with self.assertRaisesRegex(ValueError,'unsupported numeric/date format'):
                    b.call('create_workbook',{'path':'outputs/test.xlsx','sheets_json':json.dumps(sheets)})
                process.assert_not_called()
            self.assertFalse((root/'outputs/test.xlsx').exists())

    def test_plain_json_cannot_bypass_submission_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);root=base/'task';root.mkdir()
            value={'task_id':'t','status':'blocked','result':None,'issues':['missing input']}
            response={'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':json.dumps(value)}}]}
            inputs={'task_id':'t','environment':{'user_request':'task','reference_files':[],'resources':{}},'workspace':{}}
            with patch('workfactory.runtime.tool_runtime.complete',return_value=response):
                result=run_agent('06_probe',inputs,root,base/'logs',{'OPENAI_MODEL':'test','OPENAI_API_KEY':'secret'})
            self.assertIsNone(result)
            self.assertFalse(json.loads((base/'logs/validation.json').read_text())['pass'])


if __name__=='__main__':unittest.main()
