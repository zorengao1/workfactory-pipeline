"""Regression checks for relocated commands and repository resources."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workfactory.__main__ import COMMANDS
from workfactory.paths import ROOT
from workfactory.runtime.tool_runtime import Broker
from workfactory.operations.service import make_job


class RepositoryLayoutTests(unittest.TestCase):
    def test_public_commands_load_in_fresh_process(self):
        for command in COMMANDS:
            with self.subTest(command=command):
                result = subprocess.run(
                    [sys.executable, '-m', 'workfactory', command, '--help'],
                    cwd=ROOT, capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('usage:', result.stdout)

    def test_launchd_uses_module_and_repository_working_directory(self):
        job = make_job('/tmp/example', '/tmp/credentials', '/tmp/policy', ['test'])
        self.assertEqual(job['WorkingDirectory'], str(ROOT))
        args = job['ProgramArguments']
        self.assertEqual(args[args.index('-m') + 1], 'workfactory.operations.run_models')

    def test_file_adapters_resolve_after_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root/'logs').mkdir()
            broker = Broker(root, root/'logs', runtime={'python':sys.executable, 'node':'node'})
            for suffix, name in [('.docx', 'document_tool.py'), ('.pptx', 'presentation_tool.mjs')]:
                with self.subTest(suffix=suffix), patch(
                    'workfactory.runtime.tool_runtime.subprocess.run',
                    return_value=subprocess.CompletedProcess([], 0, '{}', '')
                ) as run:
                    broker.document(root/('sample'+suffix), {'title':'example'})
                    script = Path(run.call_args.args[0][1])
                    self.assertEqual(script, ROOT/'workfactory/runtime'/name)
                    self.assertTrue(script.is_file())

    def test_relative_document_links_exist(self):
        import re
        for path in [ROOT/'README.md', ROOT/'docs/README.md', ROOT/'docs/guide/RUNNING.md']:
            for target in re.findall(r'\]\(([^)]+)\)', path.read_text()):
                if '://' in target or target.startswith('#'):
                    continue
                target = target.split('#')[0]
                self.assertTrue((path.parent/target).exists(), str(path)+' -> '+target)
