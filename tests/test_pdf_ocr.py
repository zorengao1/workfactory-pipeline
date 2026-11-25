import io
import json
import subprocess
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from workfactory.sources.pdf_extraction import extract_pdf
from workfactory.pipeline.pipeline_config import stage_config


class PDFOCRTests(unittest.TestCase):
    def extract(self, texts, runner):
        reader = Mock(is_encrypted=False)
        reader.pages = [Mock(extract_text=Mock(return_value=t)) for t in texts]
        module = types.SimpleNamespace(PdfReader=Mock(return_value=reader))
        diagnostic = io.StringIO()
        with patch.dict('sys.modules', {'pypdf': module}), patch('workfactory.sources.pdf_extraction.subprocess.run', runner):
            text = extract_pdf(Path('/source/artifact'), diagnostic)
        return text, diagnostic.getvalue()

    def test_native_pdf_does_not_ocr(self):
        run = Mock()
        text, log = self.extract(['Native document text with enough readable characters.'], run)
        run.assert_not_called()
        self.assertIn('Native document', text)
        self.assertFalse(json.loads(log.splitlines()[-1])['ocr_performed'])

    def test_mixed_pdf_only_ocr_low_text_page(self):
        run = Mock(side_effect=[subprocess.CompletedProcess([], 0),
            subprocess.CompletedProcess([], 0, 'Recognized scanned report with sufficient readable content.')])
        text, log = self.extract(['Native document text with enough readable characters.', ''], run)
        self.assertEqual(run.call_count, 2)
        self.assertIn('PAGE 2\nRecognized', text)
        self.assertEqual(run.call_args_list[0].args[0][2:5], ['2', '-l', '2'])
        self.assertEqual(json.loads(log.splitlines()[-1])['pages'][1]['method'], 'ocr')

    def test_missing_ocr_dependency_fails(self):
        with self.assertRaisesRegex(RuntimeError, 'pdf_ocr_failed'):
            self.extract([''], Mock(side_effect=FileNotFoundError()))

    def test_ocr_timeout_fails(self):
        with self.assertRaisesRegex(RuntimeError, 'pdf_ocr_failed'):
            self.extract([''], Mock(side_effect=subprocess.TimeoutExpired('tesseract', 90)))

    def test_blank_scan_is_rejected(self):
        run = Mock(side_effect=[subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 0, '')])
        with self.assertRaisesRegex(ValueError, 'pdf_no_text_after_ocr'):
            self.extract([''], run)

    def test_stage_credentials_cannot_enable_search(self):
        with patch('workfactory.clients.pilot.load_config', return_value={'NATIVE_WEB_SEARCH': '1'}):
            result = stage_config({'_POLICY': {'stage_credentials': {'09_teacher': 'secret.env'}}}, '09_teacher')
        self.assertEqual(result['NATIVE_WEB_SEARCH'], '0')

    def test_default_search_does_not_enable_solver_search(self):
        from workfactory.pipeline.pipeline_config import load_policy, source_cases
        policy = load_policy()
        self.assertTrue(policy['external_retrieval'])
        seeds = [{'task_id':'test', 'stage':'01a_occupation', 'source_materials':[{'content':'test'}], 'constraints':{'external_retrieval':True}}]
        with patch('pathlib.Path.read_text', return_value=json.dumps(seeds)):
            self.assertTrue(all(not c['constraints']['external_retrieval'] for c in source_cases(policy)))

    def test_sources_not_mounted_for_teacher(self):
        from workfactory.runtime.tool_runtime import run_agent
        config = {'_POLICY': {'sandbox': {'backend': 'docker', 'construction_sources': '/private'}},
                  '_CONSTRUCTION_SOURCES': '/private'}
        with patch('workfactory.runtime.docker_runtime.DockerRuntime') as runtime, patch('workfactory.runtime.tool_runtime._run_agent'):
            run_agent('09_teacher', {}, '/task', '/logs', config)
        self.assertNotIn('construction_sources', runtime.call_args.args[2])

    def test_extractor_embeds_current_ocr_implementation(self):
        from workfactory.sources.source_retrieval import EXTRACTOR
        compile(EXTRACTOR, '<extractor>', 'exec')
        self.assertIn('t=extract_pdf(p,sys.stderr)', EXTRACTOR)
