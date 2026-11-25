import tempfile
import unittest
from pathlib import Path
from workfactory.exports.harbor_export import export_task


class HarborExportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.env=self.root/'clean';self.env.mkdir()
        (self.env/'inputs').mkdir()
        (self.env/'REQUEST.txt').write_text('Review the attached report and write a recommendation.')
        (self.env/'inputs/report.pdf').write_bytes(b'%PDF-original')
        self.out=self.root/'harbor/task'

    def test_clean_export_keeps_original_and_no_answer(self):
        result=export_task('sample',self.env,self.out)
        self.assertEqual((self.out/'environment/workspace/inputs/report.pdf').read_bytes(),b'%PDF-original')
        self.assertIn('/task/outputs',(self.out/'instruction.md').read_text())
        self.assertTrue((self.out/'instruction.md').read_text().startswith((self.env/'REQUEST.txt').read_text()))
        self.assertFalse((self.out/'environment/workspace/REQUEST.txt').exists())
        self.assertNotIn('/task/REQUEST.txt',(self.out/'environment/Dockerfile').read_text())
        self.assertTrue((self.env/'REQUEST.txt').is_file())
        self.assertNotIn('COPY tests',(self.out/'environment/Dockerfile').read_text())
        self.assertNotIn('workfactory/runtime:',(self.out/'environment/Dockerfile').read_text())
        self.assertEqual(result['verifier_status'],'pending')
        self.assertFalse((self.out/'tests/test.sh').exists())

    def test_teacher_output_rejected(self):
        (self.env/'outputs').mkdir();(self.env/'outputs/answer.txt').write_text('answer')
        with self.assertRaisesRegex(ValueError,'clean environment'):
            export_task('sample',self.env,self.out)

    def test_symlink_rejected(self):
        (self.env/'inputs/link').symlink_to(self.env/'REQUEST.txt')
        with self.assertRaisesRegex(ValueError,'Symlinks'):
            export_task('sample',self.env,self.out)

    def test_existing_export_not_overwritten(self):
        export_task('sample',self.env,self.out)
        with self.assertRaises(FileExistsError):export_task('sample',self.env,self.out)

    def test_verifier_separate_from_build_context(self):
        verifier=self.root/'verifier';verifier.mkdir()
        (verifier/'test.sh').write_text('#!/bin/sh\nexit 1\n')
        result=export_task('sample',self.env,self.out,verifier)
        self.assertTrue((self.out/'tests/test.sh').is_file())
        self.assertFalse((self.out/'environment/tests').exists())
        self.assertEqual(result['verifier_status'],'provided_not_runtime_validated')

    def test_resume_detects_environment_and_package_changes(self):
        from workfactory.exports.harbor_export import ensure_task
        ensure_task('sample',self.env,self.out)
        ensure_task('sample',self.env,self.out)
        (self.out/'instruction.md').write_text('modified')
        with self.assertRaisesRegex(ValueError,'export changed'):
            ensure_task('sample',self.env,self.out)

    def test_resume_rejects_changed_source(self):
        from workfactory.exports.harbor_export import ensure_task
        ensure_task('sample',self.env,self.out)
        (self.env/'inputs/report.pdf').write_bytes(b'new')
        with self.assertRaisesRegex(ValueError,'export changed'):
            ensure_task('sample',self.env,self.out)
