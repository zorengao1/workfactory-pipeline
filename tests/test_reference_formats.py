import tempfile
import unittest
from pathlib import Path
from environment_pilot import checks

class ReferenceFormatTests(unittest.TestCase):
    def test_encoding_labels_do_not_reject_valid_reference_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'inputs').mkdir();(p/'REQUEST.txt').write_text('Read references')
            (p/'inputs/notes.md').write_text('# Notes\nObserved facts')
            (p/'inputs/data.csv').write_text('key,value\na,1\n')
            plan={'reference_files':[{'path':'inputs/notes.md','format':'Markdown UTF-8'},{'path':'inputs/data.csv','format':'CSV (UTF-8)'}]}
            result=checks(p,plan);self.assertTrue(result['format_match']);self.assertTrue(result['exact_file_set'])
            plan['reference_files'][0]['format']='PDF'
            self.assertFalse(checks(p,plan)['format_match'])
