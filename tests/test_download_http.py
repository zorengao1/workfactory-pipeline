"""Real loopback HTTP tests, exercising urllib and socket reads."""
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from download_transport import fetch_bytes
class HTTPTests(unittest.TestCase):
 def test_real_http(self):
  counts={};payload=b'actual PDF-like test content'
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_GET(self):
    path=self.path;counts[path]=counts.get(path,0)+1
    if path=='/redirect':
     self.send_response(302);self.send_header('Location','/full');self.end_headers();return
    if path=='/denied':
     self.send_response(403);self.end_headers();return
    if path in ['/empty','/short','/busy'] and counts[path]==1:
     self.send_response(503 if path=='/busy' else 200)
     self.send_header('Content-Length','8' if path=='/short' else '0');self.end_headers()
     if path=='/short':self.wfile.write(b'x');self.close_connection=True
     return
    if path=='/range':
     start=int(self.headers['Range'].split('=')[1].split('-')[0]);end=min(start+6,len(payload))
     self.send_response(206);self.send_header('Content-Range',f'bytes {start}-{end-1}/{len(payload)}');body=payload[start:end]
    else:self.send_response(200);body=payload
    self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   for route in ['full','redirect','range','empty','short','busy']:
    with self.subTest(route=route),tempfile.TemporaryDirectory() as d,patch('download_transport.time.sleep'):
     body,*_=fetch_bytes(f'http://127.0.0.1:{server.server_port}/{route}',Path(d));self.assertEqual(body,payload)
   with tempfile.TemporaryDirectory() as d:
    from urllib.error import HTTPError
    with self.assertRaises(HTTPError):fetch_bytes(f'http://127.0.0.1:{server.server_port}/denied',Path(d))
    self.assertEqual(counts['/denied'],1)
  finally:server.shutdown();server.server_close();thread.join()
