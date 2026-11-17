import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from workfactory.models.limits import api_slot


class ApiGateTests(unittest.TestCase):
    def test_concurrent_requests_never_exceed_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            config={'OPENAI_API_KEY':'fixture','OPENAI_MODEL':'test','API_LOCK_DIR':folder,
                    'API_MAX_CONCURRENCY':2,'API_LIMIT_SCOPE':'model'}
            guard=threading.Lock();active=0;peak=0
            def request(_):
                nonlocal active,peak
                with api_slot(config):
                    with guard:active+=1;peak=max(peak,active)
                    time.sleep(.02)
                    with guard:active-=1
            with ThreadPoolExecutor(8) as pool:list(pool.map(request,range(16)))
            self.assertEqual(peak,2)
            self.assertEqual(active,0)

    def test_models_have_independent_limits_and_exception_releases_slot(self):
        with tempfile.TemporaryDirectory() as folder:
            config={'OPENAI_API_KEY':'fixture','OPENAI_MODEL':'a','API_LOCK_DIR':folder,
                    'API_MAX_CONCURRENCY':1,'API_LIMIT_SCOPE':'model'}
            with api_slot(config):
                with api_slot({**config,'OPENAI_MODEL':'b'}):pass
            with self.assertRaises(RuntimeError):
                with api_slot(config):raise RuntimeError('test')
            with api_slot(config):pass

    def test_inconsistent_limits_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            config={'OPENAI_API_KEY':'fixture','API_LOCK_DIR':folder,'API_MAX_CONCURRENCY':1}
            with api_slot(config):pass
            with self.assertRaises(ValueError):
                with api_slot({**config,'API_MAX_CONCURRENCY':2}):pass
