import tempfile
import unittest
from pathlib import Path
from workfactory.operations.service import identity, make_job


class ServiceTests(unittest.TestCase):
    def test_stable_identity_and_separate_batches(self):
        self.assertEqual(identity('/tmp/a'), identity('/tmp/a'))
        self.assertNotEqual(identity('/tmp/a'), identity('/tmp/b'))

    def test_job_passes_paths_not_secrets_and_no_infinite_retry(self):
        with tempfile.TemporaryDirectory(prefix='space path ') as tmp:
            root = Path(tmp)
            job = make_job(root, root/'credentials.env', root/'policy.json', ['mimo-v2.6-flash'])
            self.assertIn(str((root/'credentials.env').resolve()), job['ProgramArguments'])
            self.assertNotIn('OPENAI_API_KEY', job['EnvironmentVariables'])
            self.assertNotIn('KeepAlive', job)
            self.assertTrue(job['RunAtLoad'])
            self.assertEqual(job['ProgramArguments'][-1], 'mimo-v2.6-flash')
