import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workfactory.sources.skills_discovery import (DEFAULTS, DiscoveryRejected, full_skill_text,
                              review_errors, search_cli, enrich_skills)


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
    def test_expanded_body_and_utf8_reference_are_preserved(self):
        body = '<p>后半部分关键规则</p>'
        record = 'abc:T'+format(len(body.encode()),'x')+','+body
        props = json.dumps({'previewHtml': '<h1>Intro</h1>', 'restHtml': '$abc'})
        html = '<script>self.__next_f.push('+json.dumps([1,record+props])+')</script>'
        self.assertIn('后半部分关键规则', full_skill_text(html))

    def test_preview_only_fails_closed(self):
        html = '<script>self.__next_f.push('+json.dumps([1,json.dumps({'previewHtml':'intro'})])+')</script>'
        with self.assertRaises(ValueError):full_skill_text(html)

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

    def test_cli_http_error_not_empty_result(self):
        proc = subprocess.CompletedProcess([],0,'No skills found','WF_SEARCH '+json.dumps({'status':401,'skills':[]}))
        with tempfile.TemporaryDirectory() as tmp, patch('workfactory.sources.skills_discovery.subprocess.run',return_value=proc):
            with self.assertRaises(RuntimeError):search_cli('test',Path(tmp),DEFAULTS)

    def test_cli_real_empty_and_ordered_results(self):
        proc = subprocess.CompletedProcess([],0,'No skills found','WF_SEARCH '+json.dumps({'status':200,'skills':[]}))
        with tempfile.TemporaryDirectory() as tmp, patch('workfactory.sources.skills_discovery.subprocess.run',return_value=proc):
            self.assertEqual(search_cli('test',Path(tmp),DEFAULTS),[])
        proc.stdout = 'https://skills.sh/org/repo/b\nhttps://skills.sh/org/repo/a'
        proc.stderr = 'WF_SEARCH '+json.dumps({'status':200,'skills':[{'id':'org/repo/a'},{'id':'org/repo/b'}]})
        with tempfile.TemporaryDirectory() as tmp, patch('workfactory.sources.skills_discovery.subprocess.run',return_value=proc):
            self.assertEqual([r['id'] for r in search_cli('test',Path(tmp),DEFAULTS)],['org/repo/b','org/repo/a'])

    def test_gap_search_and_checkpoint_resume(self):
        plan, docs, ready = fixture()
        gap = copy.deepcopy(ready)
        gap.update(decision='search', missing_capabilities=['verify'],next_queries=['audit quotes'])
        case = {'task_id':'test','stage':'01a_occupation','source_materials':[], 'constraints':{'synthesis_allowed':True}}
        with tempfile.TemporaryDirectory() as tmp:
            config = {'OPENAI_MODEL':'test','_POLICY':{'skill_discovery':{'cache_dir':tmp}}}
            version = subprocess.CompletedProcess([],0,'1.8.1\n','')
            with patch('workfactory.sources.skills_discovery.subprocess.run',return_value=version), patch('workfactory.sources.skills_discovery.ask',side_effect=[plan,gap,ready]), patch('workfactory.sources.skills_discovery.search_cli',side_effect=[[docs[0]],[],[],[docs[1]]]) as search, patch('workfactory.sources.skills_discovery.read_skill',side_effect=lambda r,*a:r):
                result = enrich_skills(case,Path(tmp)/'run',config)
                self.assertEqual(len(result['source_materials']),2)
                self.assertEqual(result['source_metadata']['skill_discovery']['rounds'],2)
                self.assertEqual(search.call_count,4)
            with patch('workfactory.sources.skills_discovery.ask') as model:
                self.assertEqual(result,enrich_skills(case,Path(tmp)/'run',config))
                model.assert_not_called()

    def test_budget_exhaustion_does_not_emit_accepted_case(self):
        plan, docs, review = fixture()
        review.update(decision='search',missing_capabilities=['verify'],next_queries=['new query'])
        case = {'task_id':'test','source_materials':[], 'constraints':{}}
        with tempfile.TemporaryDirectory() as tmp:
            config = {'OPENAI_MODEL':'test','_POLICY':{'skill_discovery':{'cache_dir':tmp,'max_research_rounds':0}}}
            with patch('workfactory.sources.skills_discovery.subprocess.run',return_value=subprocess.CompletedProcess([],0,'1.8.1','')), patch('workfactory.sources.skills_discovery.ask',side_effect=[plan,review]), patch('workfactory.sources.skills_discovery.search_cli',return_value=[]):
                with self.assertRaises(DiscoveryRejected):enrich_skills(case,Path(tmp)/'run',config)
            self.assertFalse((Path(tmp)/'run/enriched.json').exists())
            self.assertTrue((Path(tmp)/'run/rejected.json').exists())

    def test_batch_rejection_stops_before_environment(self):
        import workfactory.pipeline.batch_generate as batch_generate
        case = {'task_id':'t', 'stage':'01a_occupation', 'source_materials':[], 'constraints':{}}
        with tempfile.TemporaryDirectory() as tmp, patch('workfactory.sources.skills_discovery.enrich_skills', side_effect=DiscoveryRejected('no suitable skills')), patch('workfactory.pipeline.batch_generate.attempt') as build:
            batch_generate.run_case(case, Path(tmp), {'OPENAI_MODEL':'test','OPENAI_API_KEY':'dummy','_POLICY':{'skill_discovery':{'enabled':True}}})
            build.assert_not_called()
            state=json.loads((Path(tmp)/'t/status.json').read_text())
            self.assertEqual(state['state'],'rejected')

    def test_expansion_after_first_screen_is_not_truncated(self):
        body = '<p>' + ('later requirements ' * 1000) + '</p>'
        props = json.dumps({'previewHtml':'<p>intro</p>','restHtml':body})
        html = '<script>self.__next_f.push('+json.dumps([1,props])+')</script>'
        self.assertEqual(full_skill_text(html).count('later requirements'),1000)


if __name__ == '__main__':unittest.main()
