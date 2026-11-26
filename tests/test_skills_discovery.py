import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workfactory.sources.skills_discovery import DEFAULTS, DiscoveryRejected, review_errors, settings


def fixture():
    plan = {'objective': 'Compare vendor bids', 'queries': ['quotes', 'costs', 'decision'],
            'capabilities': [{'id': x, 'operation': x, 'input': 'quotes', 'output': 'evidence'} for x in ['extract', 'compare', 'verify']]}
    docs = [{'source_id': 'a', 'content': 'Extract and compare quotes', 'sha256': 'a', 'id': 'org/repo/a', 'url': 'https://example/a'},
            {'source_id': 'b', 'content': 'Verify recommendation', 'sha256': 'b', 'id': 'org/repo/b', 'url': 'https://example/b'}]
    review = {'decision': 'ready', 'selected': [
        {'source_id': 'a', 'capability_ids': ['extract', 'compare'], 'evidence_quote': 'Extract', 'role': 'analysis', 'inputs': ['quotes'], 'outputs': ['costs']},
        {'source_id': 'b', 'capability_ids': ['verify'], 'evidence_quote': 'Verify', 'role': 'check', 'inputs': ['costs'], 'outputs': ['report']}],
        'steps': [{'id': str(i), 'source_id': 'a' if i < 4 else 'b', 'operation': op, 'input': 'premise', 'output': 'derived', 'depends_on': [str(i-1)] if i else []}
                  for i, op in enumerate(['extract', 'normalize', 'compute', 'sensitivity', 'cross-check', 'recommend'])],
        'resources': [{'name': 'quotes', 'provision': 'synthesize', 'reason': 'task authorizes fictional business inputs'}],
        'missing_capabilities': [], 'next_queries': [], 'rejections': [], 'explanation': 'Complementary coherent workflow'}
    return plan, docs, review


class SkillDiscoveryTests(unittest.TestCase):
    def test_valid_workflow(self):
        plan, docs, review = fixture()
        self.assertEqual(review_errors(plan, review, docs, DEFAULTS, True), [])

    def test_missing_capability_rejected(self):
        plan, docs, review = fixture()
        review['selected'][1]['capability_ids'] = ['extract']
        self.assertTrue(review_errors(plan, review, docs, DEFAULTS, True))

    def test_fake_evidence_rejected(self):
        plan, docs, review = fixture()
        review['selected'][0]['evidence_quote'] = 'Invented evidence'
        self.assertTrue(review_errors(plan, review, docs, DEFAULTS, True))

    def test_parallel_or_duplicate_steps_do_not_satisfy_depth(self):
        plan, docs, review = fixture()
        for step in review['steps']:step['depends_on'] = []
        self.assertIn('Insufficient dependent workflow depth', review_errors(plan, review, docs, DEFAULTS, True))
        review['steps'][1]['id'] = '0'
        self.assertTrue(review_errors(plan, review, docs, DEFAULTS, True))

    def test_unavailable_or_unauthorized_resource_rejected(self):
        plan, docs, review = fixture()
        self.assertTrue(review_errors(plan, review, docs, DEFAULTS, False))
        review['resources'][0]['provision'] = 'unavailable'
        self.assertTrue(review_errors(plan, review, docs, DEFAULTS, True))

    def test_only_local_index_backend_is_accepted(self):
        self.assertEqual(settings({})['backend'], 'local_index')
        for backend in ('skills_cli', 'tfidf'):
            with self.assertRaises(ValueError):
                settings({'_POLICY': {'skill_discovery': {'backend': backend}}})

    def test_batch_rejection_stops_before_environment(self):
        import workfactory.pipeline.batch_generate as batch_generate
        case = {'task_id':'t', 'stage':'01a_occupation', 'source_materials':[], 'constraints':{}, 'source_metadata':{'route':'mixed'}}
        with tempfile.TemporaryDirectory() as tmp, patch('workfactory.sources.skills_discovery.enrich_skills', side_effect=DiscoveryRejected('no suitable skills')), patch('workfactory.pipeline.batch_generate.attempt') as build:
            batch_generate.run_case(case, Path(tmp), {'OPENAI_MODEL':'test','OPENAI_API_KEY':'dummy','_POLICY':{'skill_discovery':{'enabled':True}}})
            build.assert_not_called()
            state=json.loads((Path(tmp)/'t/status.json').read_text())
            self.assertEqual(state['state'],'rejected')


if __name__ == '__main__':unittest.main()
