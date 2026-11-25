import tempfile
import unittest
from pathlib import Path
from source_artifacts import artifacts, read_source, stage_reuse, verify_reuse, binding_errors, digest


class ArtifactTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.source=self.root/'artifact';self.source.write_bytes(b'%PDF-1.4\noriginal bytes\n%%EOF')
        (self.root/'artifact.txt').write_text('a'*100000+'late page evidence')
        self.materials=[{'source_id':'report','snapshot':str(self.source),'sha256':digest(self.source),'content':'excerpt'}]
        self.plan={'reference_files':[{'id':'f','path':'inputs/report.pdf','format':'pdf','method':'reuse','source_ids':['report']}]}

    def test_full_text_beyond_original_excerpt(self):
        result=read_source(artifacts(self.materials),'report',100000,100)
        self.assertEqual(result['text'],'late page evidence')

    def test_real_copy_and_modified_file_rejected(self):
        env=self.root/'env';env.mkdir()
        records=stage_reuse(self.plan,self.materials,env)
        self.assertEqual((env/'inputs/report.pdf').read_bytes(),self.source.read_bytes())
        self.assertTrue(verify_reuse(records,env))
        (env/'inputs/report.pdf').write_bytes(b'changed')
        self.assertFalse(verify_reuse(records,env))

    def test_missing_binding_wrong_format_and_path(self):
        self.plan['reference_files'][0]['source_ids']=[]
        self.assertTrue(binding_errors(self.plan,artifacts(self.materials)))
        self.plan['reference_files'][0].update(source_ids=['report'],format='md')
        self.assertTrue(binding_errors(self.plan,artifacts(self.materials)))
        self.plan['reference_files'][0].update(format='pdf',path='../escape.pdf')
        with self.assertRaises(ValueError):stage_reuse(self.plan,self.materials,self.root/'env')

    def test_corrupt_or_missing_snapshot_fails(self):
        self.source.write_bytes(b'corrupt')
        with self.assertRaises(ValueError):artifacts(self.materials)
        self.source.unlink()
        with self.assertRaises(ValueError):artifacts(self.materials)

    def test_missing_full_text_does_not_silently_use_excerpt(self):
        (self.root/'artifact.txt').unlink()
        with self.assertRaises(ValueError):read_source(artifacts(self.materials),'report')

    def test_preview_preserves_full_text_and_searches_tail(self):
        from source_artifacts import text_metadata, search_source
        text='x'*120000+'unique evidence'
        meta=text_metadata(self.root/'artifact.txt',text)
        self.assertTrue(meta['content_is_preview'])
        self.assertFalse(meta['extraction_truncated'])
        self.assertEqual(len(meta['content']),12000)
        self.materials[0].update(meta)
        catalog=artifacts(self.materials)
        match=search_source(catalog,'report','unique evidence')['matches'][0]
        self.assertEqual(match['match_start'],120000)
        self.assertIn('unique evidence',read_source(catalog,'report',match['start'],1000)['text'])
        (self.root/'artifact.txt').write_text('changed')
        with self.assertRaises(ValueError):artifacts(self.materials)
