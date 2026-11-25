import unittest
from workfactory.sources.extraction_quality import preflight, text_quality
class ExtractionTests(unittest.TestCase):
 def test_empty(self):
  with self.assertRaisesRegex(ValueError,'empty_download'):preflight(b'','https://a/report.pdf')
 def test_fake_pdf(self):
  with self.assertRaisesRegex(ValueError,'html_instead'):preflight(b'<html>login</html>','https://a/report.pdf','text/html')
 def test_pdf(self):preflight(b'%PDF-1.7 content','https://a/report.pdf','application/pdf')
 def test_short_text(self):self.assertTrue(text_quality('A concise report with sufficient readable factual content.')['short_document'])
 def test_labels_not_content(self):
  with self.assertRaises(ValueError):text_quality('\n'.join('PAGE '+str(i) for i in range(200)))

class CacheTests(unittest.TestCase):
 def test_stale_extraction_replaced_and_cached(self):
  import tempfile,json,hashlib
  from pathlib import Path
  from unittest.mock import patch
  from subprocess import CompletedProcess
  from workfactory.sources.source_retrieval import download_deliverable
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);body=b'%PDF-1.7 test %%EOF';url='https://example.org/a.pdf'
   (p/'artifact').write_bytes(body)
   (p/'artifact.source.json').write_text(json.dumps({'url':url,'sha256':hashlib.sha256(body).hexdigest(),'content_type':'application/pdf'}))
   (p/'artifact.txt').write_text('stale text')
   text='Newly extracted document with enough readable content for processing.'
   with patch('workfactory.sources.source_retrieval.subprocess.run',return_value=CompletedProcess([],0,text,'')) as run:
    self.assertEqual(download_deliverable(url,p,'test')[1],text)
    self.assertEqual(download_deliverable(url,p,'test')[1],text)
    self.assertEqual(run.call_count,1)
   self.assertTrue(list(p.glob('artifact.previous-*.txt')))
