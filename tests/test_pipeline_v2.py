import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from workfactory.pipeline.batch_generate import materialize, StageRejected
from workfactory.runtime.docker_runtime import DockerRuntime
from workfactory.pipeline.environment_pilot import checks


class PipelineV2Tests(unittest.TestCase):
    def test_initial_retries_preserve_plan_and_rejected_build(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);plan={'reference_files':[],'fixed':'original'}
            seen=[]
            def agent(stage,inputs,workspace,logs,*args):
                seen.append((stage,inputs))
                if stage=='04_build':
                    if 'materialization-00' in str(workspace):raise StageRejected('bad artifact')
                    (workspace/'REQUEST.txt').write_text('task')
                return {'status':'ok','result':{'verdict':'pass'}}
            with patch('workfactory.pipeline.batch_generate.agent',side_effect=agent):
                result=materialize({'task_id':'test','constraints':{}},plan,root,{})
            self.assertEqual(result.parent.name,'materialization-01')
            self.assertTrue((root/'materialization-00/rejected.json').exists())
            self.assertTrue(all(inputs['plan']==plan for _,inputs in seen))

    def test_document_extension_does_not_hide_invalid_content(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'REQUEST.txt').write_text('task');(root/'fake.pdf').write_text('not a PDF')
            result=checks(root,{'reference_files':[{'path':'fake.pdf','format':'pdf'}]})
            self.assertTrue(result['exact_file_set'])
            self.assertFalse(result['format_match'])

    def test_container_mounts_only_visible_task_and_outputs(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'REQUEST.txt').write_text('visible')
            runtime=DockerRuntime(root,('outputs',),{'image':'workfactory/runtime:test'},root/'logs')
            with patch('workfactory.runtime.docker_runtime.subprocess.run',return_value=Mock(returncode=0,stdout='',stderr='')) as run:
                runtime.execute('ls /task');runtime.close()
            command=run.call_args_list[0].args[0]
            self.assertIn('none',command)
            self.assertIn('--user',command)
            mounts=[command[i+1] for i,v in enumerate(command) if v=='--mount']
            self.assertEqual(len(mounts),2)
            self.assertTrue(mounts[0].endswith('dst=/task,readonly'))
            self.assertTrue(mounts[1].endswith('dst=/task/outputs'))
            self.assertNotIn('/var/run/docker.sock',' '.join(command))
            self.assertFalse(runtime.started)
