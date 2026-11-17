"""Check relocated launch paths without network, model calls or Docker."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from workfactory.cli import COMMANDS
from workfactory.core.contracts import ROOT
from workfactory.operations.service import make_job
from workfactory.runtime.agent import Broker


class EntryPointTests(unittest.TestCase):
    def test_all_commands_have_safe_help(self):
        for command in COMMANDS:
            with self.subTest(command=command):
                result = subprocess.run(
                    [sys.executable, '-m', 'workfactory', command, '--help'],
                    cwd=ROOT, capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('usage:', result.stdout)

    def test_export_runs_as_a_child_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)/'09_teacher'
            stage.mkdir()
            fixtures = {
                'validation.json': {'pass': True, 'after': {'outputs/report.txt': 'sha'}},
                '00-request.json': {'messages': [{'role': 'user', 'content': 'task'}],
                                    'tools': [], 'model': 'test'},
                '00-response.json': {'choices': [{'message': {'role': 'assistant', 'content': 'done'}}]},
                'parsed.json': {'deliverables': ['outputs/report.txt']},
            }
            for name, value in fixtures.items():
                (stage/name).write_text(json.dumps(value))
            output=Path(tmp)/'trajectory.json'
            result=subprocess.run([sys.executable, '-m', 'workfactory', 'export',
                                   str(stage), '--output', str(output)],
                                  cwd=ROOT,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertFalse(json.loads(output.read_text())['training_ready'])

    def test_background_job_uses_importable_module(self):
        job=make_job('/tmp/run','/tmp/credentials.env','/tmp/policy.json',['gpt-6.1-sol'])
        self.assertEqual(job['ProgramArguments'][2:4],['-m','workfactory.pipeline.models'])
        self.assertEqual(job['WorkingDirectory'],str(ROOT))

    def test_multi_model_child_uses_package_and_repository_cwd(self):
        from workfactory.pipeline.models import main
        with tempfile.TemporaryDirectory() as tmp:
            args=['workfactory','--config','/tmp/credentials.env','--pipeline-config',
                  '/tmp/policy.json','--output',tmp,'--models','gpt-6.1-sol']
            with patch.object(sys,'argv',args),patch('workfactory.pipeline.models.subprocess.run',
                    return_value=Mock(returncode=0)) as run:
                main()
            self.assertEqual(run.call_args.args[0][2:4],['-m','workfactory.pipeline.batch'])
            self.assertEqual(run.call_args.kwargs['cwd'],ROOT)

    def test_document_adapter_uses_moved_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();(root/'outputs').mkdir()
            broker=Broker(root,root/'logs',('outputs',),{'python':sys.executable})
            with patch('workfactory.runtime.agent.subprocess.run',return_value=Mock(
                    returncode=0,stderr='',stdout='{}')) as run:
                broker.document(root/'outputs/report.docx',{'title':'Report'})
            self.assertEqual(Path(run.call_args.args[0][1]),ROOT/'workfactory/tools/documents.py')
            self.assertTrue(Path(run.call_args.args[0][1]).is_file())
