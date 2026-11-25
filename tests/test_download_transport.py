import io
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch
from workfactory.sources.download_transport import fetch_bytes

class Response(io.BytesIO):
    def __init__(self, body, status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}
    def geturl(self): return 'https://example.org/file'

class DownloadTests(unittest.TestCase):
    def run_fetch(self, responses):
        with tempfile.TemporaryDirectory() as d, patch('urllib.request.urlopen', side_effect=responses) as call, patch('time.sleep'):
            result = fetch_bytes('https://example.org/file', Path(d))
            return result, call.call_count
    def test_ranges(self):
        result, count = self.run_fetch([Response(b'ab',206,{'Content-Range':'bytes 0-1/4'}),Response(b'cd',206,{'Content-Range':'bytes 2-3/4'})])
        self.assertEqual(result[0],b'abcd')
    def test_short_response_retried(self):
        result,count=self.run_fetch([Response(b'a',200,{'Content-Length':'2'}),Response(b'ab',200,{'Content-Length':'2'})])
        self.assertEqual((result[0],count),(b'ab',2))
    def test_range_ignored_replaces_partial(self):
        result,_=self.run_fetch([Response(b'ab',206,{'Content-Range':'bytes 0-1/4'}),Response(b'abcd',200,{'Content-Length':'4'})])
        self.assertEqual(result[0],b'abcd')
    def test_403_not_retried(self):
        err=urllib.error.HTTPError('https://example.org/file',403,'Forbidden',{},None)
        with tempfile.TemporaryDirectory() as d, patch('urllib.request.urlopen',side_effect=err) as call:
            with self.assertRaises(urllib.error.HTTPError):fetch_bytes('https://example.org/file',Path(d))
            self.assertEqual(call.call_count,1)
    def test_version_change_rejected(self):
        with self.assertRaises(ValueError):
            self.run_fetch([Response(b'ab',206,{'Content-Range':'bytes 0-1/4','ETag':'a'}),Response(b'cd',206,{'Content-Range':'bytes 2-3/4','ETag':'b'})])
    def test_503_retried(self):
        result,count=self.run_fetch([urllib.error.HTTPError('https://example.org/file',503,'Busy',{},None),Response(b'ok')])
        self.assertEqual((result[0],count),(b'ok',2))

    def test_empty_response_retried(self):
        result, count = self.run_fetch([Response(b''), Response(b'ok')])
        self.assertEqual((result[0], count), (b'ok', 2))
