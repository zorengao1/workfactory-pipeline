import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workfactory.sources import skill_index
from workfactory.sources.skills_discovery import DiscoveryRejected, enrich_skills, settings

try:
    import numpy as np
except ImportError:
    np = None


def build(folder, bodies=None):
    """Three skills on orthogonal axes; occupation 11-1011.00 has a profile and two tasks."""
    folder.mkdir(parents=True, exist_ok=True)
    ids = ['aaa', 'bbb', 'ccc', 'ddd']
    skills = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1], [0.8, 0.6, 0]], dtype=np.float16)
    queries = np.array([[1, 0, 0], [0, 1, 0], [0.6, 0.8, 0]], dtype=np.float16)
    qids = ['11-1011.00|profile', '11-1011.00|task|0', '11-1011.00|task|1']
    np.save(folder / 'skills.f16.npy', skills)
    np.save(folder / 'queries.f16.npy', queries)
    (folder / 'skills.ids.json').write_text(json.dumps(ids))
    (folder / 'queries.ids.json').write_text(json.dumps(qids))
    db = sqlite3.connect(folder / 'skills.sqlite')
    db.execute('CREATE TABLE skills (skill_id TEXT PRIMARY KEY, name TEXT, description TEXT, source TEXT, repo TEXT,'
               ' url TEXT, path TEXT, n_words INTEGER, attachments TEXT, attachments_missing INTEGER, body TEXT)')
    words = bodies or {}
    for i in ids:
        db.execute('INSERT INTO skills VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                   (i, 'name-' + i, 'about ' + i, 'skillmd', 'org/repo', '', 'p', words.get(i, 100), 'none', 0, 'Body of ' + i))
    db.commit()
    db.close()
    (folder / 'manifest.json').write_text(json.dumps(dict(index_id='test', embedding_model='m', skills=4, queries=3)))
    return folder


@unittest.skipUnless(np, 'numpy is only needed where the local skill index runs')
class SkillIndexTests(unittest.TestCase):
    def test_round_robin_covers_each_query_and_respects_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = skill_index.SkillIndex(build(Path(tmp)))
            found = index.candidates('11-1011.00', 3, per_query=2, min_similarity=0.5)
            self.assertEqual(len(found), 3)
            self.assertEqual({d['id'] for d in found[:2]}, {'aaa', 'bbb'})
            self.assertNotIn('ccc', {d['id'] for d in found})
            self.assertEqual(found[0]['content'], 'Body of ' + found[0]['id'])
            self.assertTrue(all(d['source_id'] == 'skill-' + d['id'] for d in found))

    def test_exclusion_length_filter_and_unknown_occupation(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = skill_index.SkillIndex(build(Path(tmp), {'aaa': 9000}))
            ids = {d['id'] for d in index.candidates('11-1011.00', 4, min_similarity=0.5, max_words=4000, exclude=['bbb'])}
            self.assertEqual(ids, {'ddd'})
            near = index.neighbors('ddd', 5, min_similarity=0.5, max_similarity=0.92, max_words=4000)
            self.assertEqual([d['id'] for d in near], ['bbb'])
            self.assertEqual(index.neighbors('ddd', 5, 0.5, 0.92, exclude=['bbb']), [])
            self.assertEqual([d['id'] for d in index.neighbors('ddd', 5, 0.5, 0.7, max_words=10000)], ['bbb'])
            both = skill_index.SkillIndex(build(Path(tmp) / 'second'))
            self.assertEqual([d['id'] for d in both.neighbors('ddd', 5, 0.5, 0.92)], ['aaa', 'bbb'])
            with self.assertRaises(skill_index.SkillIndexError):
                index.neighbors('zzz', 3)
            with self.assertRaises(skill_index.SkillIndexError):
                index.candidates('99-9999.00', 3)

    def test_incomplete_or_inconsistent_index_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = build(Path(tmp))
            (folder / 'skills.ids.json').write_text(json.dumps(['aaa']))
            with self.assertRaises(skill_index.SkillIndexError):
                skill_index.SkillIndex(folder)
            (folder / 'skills.sqlite').unlink()
            with self.assertRaises(skill_index.SkillIndexError):
                skill_index.SkillIndex(folder)


class AnchorTests(unittest.TestCase):
    def folder(self, tmp):
        db = sqlite3.connect(Path(tmp) / 'skills.sqlite')
        db.execute('CREATE TABLE skills (skill_id TEXT PRIMARY KEY, name TEXT, description TEXT, source TEXT, repo TEXT,'
                   ' url TEXT, path TEXT, n_words INTEGER, attachments TEXT, attachments_missing INTEGER, body TEXT)')
        rows = [('a%d' % i, 'n', 'd', 'skillmd', 'big/repo', '', 'p', 500, 'none', 0, 'body') for i in range(6)]
        rows += [('b1', 'n', 'd', 'gym', 'small', '', 'p', 500, 'none', 0, 'body'), ('c1', 'n', 'd', 'claude', 'other', '', 'p', 500, 'none', 0, 'body'),
                 ('short', 'n', 'd', 'gym', 'x', '', 'p', 60, 'none', 0, 'body'), ('needs', 'n', 'd', 'gym', 'y', '', 'p', 500, 'none', 1, 'body'),
                 ('blank', '', '', 'gym', 'z', '', 'p', 500, 'none', 0, 'body')]
        db.executemany('INSERT INTO skills VALUES (?,?,?,?,?,?,?,?,?,?,?)', rows)
        db.commit()
        db.close()
        return Path(tmp)

    def test_anchors_are_seeded_self_contained_and_spread_over_repositories(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.folder(tmp)
            first = skill_index.sample_anchors(folder, 4, 7)
            self.assertEqual(first, skill_index.sample_anchors(folder, 4, 7))
            self.assertTrue({'b1', 'c1'} <= set(first[:3]))
            self.assertFalse({'short', 'needs', 'blank'} & set(skill_index.sample_anchors(folder, 8, 7)))
            with self.assertRaises(skill_index.SkillIndexError):
                skill_index.sample_anchors(folder, 9, 7)
            self.assertEqual(skill_index.read_documents(folder, ['b1'])['b1']['body'], 'body')
        with tempfile.TemporaryDirectory() as empty, self.assertRaises(skill_index.SkillIndexError):
            skill_index.sample_anchors(Path(empty), 1, 1)


class FakeIndex:
    identity = {'index_id': 'fake'}

    def __init__(self, batches):
        self.batches = list(batches)
        self.calls = []

    def candidates(self, code, limit, per_query, min_similarity, min_words, max_words, exclude=()):
        self.calls.append((code, limit, list(exclude)))
        return self.batches.pop(0) if self.batches else []

    def neighbors(self, anchor, limit, min_similarity, max_similarity, min_words, max_words, exclude=()):
        self.calls.append((anchor, limit, list(exclude)))
        return self.batches.pop(0) if self.batches else []


def doc(i, text):
    return dict(source_id='skill-' + i, id=i, name=i, description='', url='skill-index:x', provenance='skillmd:org/repo',
                content=text, sha256=i, similarity=0.6, matched_queries=['q'], attachments='none', attachments_missing=False)


def judged(decision='ready'):
    return {'decision': decision, 'objective': 'Compare vendor bids',
            'capabilities': [{'id': x, 'operation': x, 'input': 'quotes', 'output': 'evidence'} for x in ['extract', 'compare', 'verify']],
            'selected': [
                {'source_id': 'skill-a', 'capability_ids': ['extract', 'compare'], 'evidence_quote': 'Extract', 'role': 'analysis', 'inputs': ['quotes'], 'outputs': ['costs']},
                {'source_id': 'skill-b', 'capability_ids': ['verify'], 'evidence_quote': 'Verify', 'role': 'check', 'inputs': ['costs'], 'outputs': ['report']}],
            'steps': [{'id': str(i), 'source_id': 'skill-a' if i < 4 else 'skill-b', 'operation': op, 'input': 'premise', 'output': 'derived', 'depends_on': [str(i - 1)] if i else []}
                      for i, op in enumerate(['extract', 'normalize', 'compute', 'sensitivity', 'cross-check', 'recommend'])],
            'resources': [{'name': 'quotes', 'provision': 'synthesize', 'reason': 'authorized fictional inputs'}],
            'missing_capabilities': [], 'rejections': [{'source_id': 'skill-c', 'reason': 'different domain'}], 'explanation': 'ok'}


CASE = {'task_id': 'mixed-11-1011-00', 'stage': '01a_occupation', 'source_materials': [],
        'constraints': {'synthesis_allowed': True}, 'source_metadata': {'route': 'mixed', 'onet_code': '11-1011.00'}}


class LocalDiscoveryTests(unittest.TestCase):
    def config(self, tmp, **extra):
        return {'OPENAI_MODEL': 'test', '_POLICY': {'skill_discovery': {'backend': 'local_index', 'index_dir': tmp, **extra}}}

    def run_local(self, tmp, index, answers, **extra):
        with patch('workfactory.sources.skill_index.load_index', return_value=index), \
                patch('workfactory.sources.skills_discovery.ask', side_effect=answers) as model:
            return enrich_skills(copy.deepcopy(CASE), Path(tmp) / 'run', self.config(tmp, **extra)), model

    def test_judge_selects_only_relevant_skills_and_resumes_from_checkpoint(self):
        index = FakeIndex([[doc('a', 'Extract and compare quotes'), doc('b', 'Verify recommendation'), doc('c', 'Unrelated')]])
        with tempfile.TemporaryDirectory() as tmp:
            result, _ = self.run_local(tmp, index, [judged()])
            self.assertEqual([m['source_id'] for m in result['source_materials']], ['skill-a', 'skill-b'])
            meta = result['source_metadata']['skill_discovery']
            self.assertEqual((meta['rounds'], meta['candidates'], meta['index']), (1, 3, {'index_id': 'fake'}))
            self.assertIn('local embedding index', meta['method'])
            self.assertEqual(result['constraints']['skill_workflow']['objective'], 'Compare vendor bids')
            again, model = self.run_local(tmp, FakeIndex([]), [])
            self.assertEqual(again, result)
            model.assert_not_called()

    def test_more_requests_next_batch_without_repeating_candidates(self):
        index = FakeIndex([[doc('a', 'Extract and compare quotes')], [doc('b', 'Verify recommendation')]])
        first = judged('more')
        first.update(selected=[], steps=[], resources=[], missing_capabilities=['verify'])
        with tempfile.TemporaryDirectory() as tmp:
            result, model = self.run_local(tmp, index, [first, judged()], max_research_rounds=1)
            self.assertEqual(result['source_metadata']['skill_discovery']['rounds'], 2)
            self.assertEqual(index.calls[1][2], ['a'])
            self.assertEqual(model.call_args_list[1].args[1]['previous_feedback'][-1], 'verify')
            self.assertTrue(model.call_args_list[1].args[1]['final_round'])

    def test_fabricated_evidence_or_exhausted_rounds_reject(self):
        bad = judged()
        bad['selected'][0]['evidence_quote'] = 'Invented'
        index = FakeIndex([[doc('a', 'Extract and compare quotes'), doc('b', 'Verify recommendation')]])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(DiscoveryRejected):
                self.run_local(tmp, index, [bad, bad])
            self.assertFalse((Path(tmp) / 'run/enriched.json').exists())
            self.assertTrue((Path(tmp) / 'run/rejected.json').exists())

    def test_no_candidates_rejects_without_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('workfactory.sources.skill_index.load_index', return_value=FakeIndex([[]])), \
                    patch('workfactory.sources.skills_discovery.ask') as model:
                with self.assertRaises(DiscoveryRejected):
                    enrich_skills(copy.deepcopy(CASE), Path(tmp) / 'run', self.config(tmp))
                model.assert_not_called()

    def test_occupation_code_is_required(self):
        case = copy.deepcopy(CASE)
        del case['source_metadata']['onet_code']
        with tempfile.TemporaryDirectory() as tmp, patch('workfactory.sources.skill_index.load_index', return_value=FakeIndex([])):
            with self.assertRaises(ValueError):
                enrich_skills(case, Path(tmp) / 'run', self.config(tmp))

    def skill_case(self):
        anchor = doc('a', 'Extract and compare quotes')
        return {'task_id': 'skill-a', 'stage': '01b_skill', 'constraints': {'synthesis_allowed': True},
                'source_materials': [{k: anchor[k] for k in ('source_id', 'provenance', 'url', 'sha256', 'content')}],
                'source_metadata': {'route': 'skill', 'anchor_skill_id': 'a'}}

    def run_skill(self, tmp, index, answers):
        with patch('workfactory.sources.skill_index.load_index', return_value=index), \
                patch('workfactory.sources.skills_discovery.ask', side_effect=answers) as model:
            return enrich_skills(self.skill_case(), Path(tmp) / 'run', self.config(tmp)), model

    def test_skill_route_composes_anchor_with_recalled_neighbors(self):
        index = FakeIndex([[doc('b', 'Verify recommendation'), doc('c', 'Unrelated')]])
        with tempfile.TemporaryDirectory() as tmp:
            result, model = self.run_skill(tmp, index, [judged()])
            self.assertEqual([m['source_id'] for m in result['source_materials']], ['skill-a', 'skill-b'])
            self.assertEqual(index.calls[0][0], 'a')
            self.assertEqual(index.calls[0][2], ['a'])
            self.assertEqual(model.call_args.args[0], 'compose-0')
            self.assertEqual(model.call_args.args[1]['anchor_source_id'], 'skill-a')
            self.assertEqual(model.call_args.args[1]['candidates'][0]['source_id'], 'skill-a')
            self.assertIn('anchor skill', result['source_metadata']['skill_discovery']['method'])

    def test_skill_route_allows_anchor_alone_but_never_drops_it(self):
        alone = judged()
        alone['selected'] = [dict(alone['selected'][0], capability_ids=['extract', 'compare', 'verify'])]
        for step in alone['steps']:
            step['source_id'] = 'skill-a'
        with tempfile.TemporaryDirectory() as tmp:
            result, _ = self.run_skill(tmp, FakeIndex([[doc('b', 'Verify recommendation')]]), [alone])
            self.assertEqual([m['source_id'] for m in result['source_materials']], ['skill-a'])
        dropped = judged()
        dropped['selected'] = [dict(dropped['selected'][1], capability_ids=['extract', 'compare', 'verify'])]
        for step in dropped['steps']:
            step['source_id'] = 'skill-b'
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(DiscoveryRejected):
            self.run_skill(tmp, FakeIndex([[doc('b', 'Verify recommendation')]]), [dropped, dropped])

    def test_default_policy_uses_local_index(self):
        from workfactory.pipeline.pipeline_config import load_policy
        self.assertEqual(settings({'_POLICY': load_policy()})['backend'], 'local_index')


class RouteTests(unittest.TestCase):
    def run_route(self, route, policy, **meta):
        import workfactory.pipeline.batch_generate as batch
        case = {'task_id': 't', 'stage': '01a_occupation', 'source_materials': [], 'constraints': {},
                'source_metadata': {**({'route': route} if route else {}), **meta}}
        with tempfile.TemporaryDirectory() as tmp, \
                patch('workfactory.sources.skills_discovery.enrich_skills', side_effect=lambda c, *a: c) as skills, \
                patch('workfactory.sources.source_retrieval.enrich_case', side_effect=lambda c, *a: c) as web, \
                patch('workfactory.sources.source_retrieval.deliverable_case', side_effect=lambda c, *a: c) as artifact, \
                patch('workfactory.pipeline.batch_generate.attempt', return_value='trajectory.json'):
            batch.run_case(case, Path(tmp), {'OPENAI_MODEL': 'test', 'OPENAI_API_KEY': 'dummy', '_POLICY': policy})
            return skills.call_count, web.call_count, artifact.call_count

    def test_each_route_prepares_only_its_own_sources(self):
        policy = {'skill_discovery': {'enabled': True}, 'external_retrieval': True}
        self.assertEqual(self.run_route('occupation', policy), (0, 0, 0))
        self.assertEqual(self.run_route(None, policy), (0, 0, 0))
        self.assertEqual(self.run_route('skill', policy, anchor_skill_id='a'), (1, 0, 0))
        self.assertEqual(self.run_route('skill', policy), (0, 0, 0))
        self.assertEqual(self.run_route('deliverable', policy, deliverable_search=[{'source_id': 's', 'content': 'c'}]), (0, 0, 1))
        self.assertEqual(self.run_route('deliverable', {}, deliverable_url='https://example.org/a.pdf'), (0, 0, 1))
        self.assertEqual(self.run_route('deliverable', policy), (0, 0, 0))
        self.assertEqual(self.run_route('mixed', policy), (1, 1, 0))

    def test_routes_needing_the_index_fail_instead_of_degrading(self):
        with self.assertRaises(ValueError):
            self.run_route('mixed', {'skill_discovery': {'enabled': False}})
        with self.assertRaises(ValueError):
            self.run_route('skill', {}, anchor_skill_id='a')
        with self.assertRaises(ValueError):
            self.run_route('unknown', {})


class DeliverableRouteTests(unittest.TestCase):
    CASE = {'task_id': 'deliverable-x', 'stage': '01c_deliverable', 'source_materials': [],
            'constraints': {'synthesis_allowed': True, 'scope': 's'},
            'source_metadata': {'route': 'deliverable', 'deliverable_url': 'https://example.org/report.pdf', 'publisher': 'Example Org'}}

    def test_listed_url_becomes_the_only_material_without_web_search(self):
        from workfactory.sources import source_retrieval

        def download(url, folder, image):
            Path(folder).mkdir(parents=True, exist_ok=True)
            (Path(folder) / 'artifact').write_bytes(b'%PDF')
            (Path(folder) / 'artifact.txt').write_text('Annual report body')
            return {'url': url, 'sha256': 'ab' * 32}, 'Annual report body'
        config = {'OPENAI_MODEL': 'm', '_POLICY': {'sandbox': {'image': 'img'}}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(source_retrieval, 'download_deliverable', side_effect=download) as fetch, \
                patch.object(source_retrieval, 'complete') as model:
            result = source_retrieval.deliverable_case(copy.deepcopy(self.CASE), Path(tmp) / 'r', config)
            self.assertEqual(len(result['source_materials']), 1)
            item = result['source_materials'][0]
            self.assertTrue(item['source_id'].startswith('real-deliverable-'))
            self.assertIn('Example Org', item['provenance'])
            self.assertTrue(Path(item['snapshot']).is_file())
            self.assertFalse(result['constraints']['external_retrieval'])
            self.assertEqual(source_retrieval.deliverable_case(copy.deepcopy(self.CASE), Path(tmp) / 'r', config), result)
            self.assertEqual(fetch.call_count, 1)
            model.assert_not_called()
            changed = copy.deepcopy(self.CASE)
            changed['source_metadata']['deliverable_url'] = 'https://example.org/other.pdf'
            with self.assertRaises(ValueError):
                source_retrieval.deliverable_case(changed, Path(tmp) / 'r', config)

    def test_search_seeded_case_requires_configured_web_search_and_drops_the_cue(self):
        from workfactory.sources import source_retrieval
        case = copy.deepcopy(self.CASE)
        case['source_metadata'] = {'route': 'deliverable', 'deliverable_search': [{'source_id': 'search-cue-1', 'content': 'Accountants'}]}
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                source_retrieval.deliverable_case(copy.deepcopy(case), Path(tmp) / 'a', {'OPENAI_MODEL': 'm', '_POLICY': {'sandbox': {'image': 'i'}}})
            found = ({'deliverable_title': 'Audit plan', 'publisher': 'City'}, {'url': 'https://city.example/p.pdf', 'sha256': 'cd' * 32},
                     'text', Path(tmp), ['https://city.example/p.pdf'])
            (Path(tmp) / 'artifact.txt').write_text('text')
            with patch.object(source_retrieval, 'find_deliverable', return_value=found) as search:
                result = source_retrieval.deliverable_case(copy.deepcopy(case), Path(tmp) / 'b', {'OPENAI_MODEL': 'm', '_POLICY': {'sandbox': {'image': 'i'}}})
            self.assertEqual(search.call_args.args[0], case['source_metadata']['deliverable_search'])
            self.assertEqual([m['title'] for m in result['source_materials']], ['Audit plan'])
            self.assertNotIn('Accountants', json.dumps(result['source_materials']))
        with self.assertRaises(ValueError):
            with tempfile.TemporaryDirectory() as tmp:
                source_retrieval.deliverable_case({**case, 'source_metadata': {'route': 'deliverable'}}, Path(tmp) / 'c', {'_POLICY': {'sandbox': {'image': 'i'}}})

    def test_policy_accepts_pending_deliverable_cases_only(self):
        from workfactory.pipeline import pipeline_config
        policy = pipeline_config.load_policy()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'cases.json'
            path.write_text(json.dumps([copy.deepcopy(self.CASE)]))
            self.assertEqual(len(pipeline_config.source_cases({**policy, 'source_cases': str(path)})), 1)
            empty = copy.deepcopy(self.CASE)
            empty['source_metadata'] = {'route': 'deliverable'}
            path.write_text(json.dumps([empty]))
            with self.assertRaises(ValueError):
                pipeline_config.source_cases({**policy, 'source_cases': str(path)})


class BuildRouteTests(unittest.TestCase):
    def test_four_routes_are_built_from_filter_index_and_manifest(self):
        from workfactory.sources import source_pools
        occ = lambda code, major: {'source_id': 'onet-31.0-' + code, 'version': '31.0', 'onet_code': code, 'soc_code': code[:7],
                                   'soc_major': major, 'title': code, 'description': 'd', 'tasks': [{'id': '1', 'text': 't', 'type': 'Core'}],
                                   'skills_and_activities': [], 'url': 'u', 'attribution': 'a'}
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / 'occupations.json').write_text(json.dumps([occ('11-1011.00', '11-0000'), occ('13-2011.00', '13-0000'),
                                                              occ('29-1141.00', '29-0000'), occ('47-2061.00', '47-0000')]))
            (data / 'soc.json').write_text('[]')
            table = data / 'filter.csv'
            table.write_text('onet_code,digitizable,digitizable_reason,mixed_route,supplemental_search\n'
                             '11-1011.00,yes,a,yes,\n13-2011.00,yes,a,no,\n29-1141.00,limited,b,yes,\n47-2061.00,no,c,no,\n')
            index = data / 'index'
            index.mkdir()
            db = sqlite3.connect(index / 'skills.sqlite')
            db.execute('CREATE TABLE skills (skill_id TEXT PRIMARY KEY, name TEXT, description TEXT, source TEXT, repo TEXT,'
                       ' url TEXT, path TEXT, n_words INTEGER, attachments TEXT, attachments_missing INTEGER, body TEXT)')
            db.executemany('INSERT INTO skills VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                           [('s%d' % i, 'name%d' % i, 'd', 'skillmd', 'r%d' % i, '', 'p', 400, 'none', 0, 'Skill body %d' % i) for i in range(3)])
            db.commit()
            db.close()
            manifest = data / 'known.json'
            manifest.write_text(json.dumps([{'url': 'https://example.org/plan.pdf', 'title': 'Plan', 'publisher': 'Org'}]))
            with patch.object(source_pools, 'DATA', data):
                report = source_pools.build_cases(0, 2, 1, -1, str(table), ('yes',), -1, str(index), str(manifest))
                cases = json.loads((data / 'cases.json').read_text())
                self.assertEqual(report['cases_by_route'], {'occupation': 2, 'mixed': 1, 'skill': 2, 'deliverable': 3})
                routes = sorted((c['task_id'], c['source_metadata']['route']) for c in cases if c['stage'] == '01a_occupation')
                self.assertEqual(routes, [('mixed-11-1011-00', 'mixed'), ('onet-11-1011-00', 'occupation'), ('onet-13-2011-00', 'occupation')])
                skill = [c for c in cases if c['source_metadata']['route'] == 'skill'][0]
                self.assertEqual(skill['source_materials'][0]['source_id'], 'skill-' + skill['source_metadata']['anchor_skill_id'])
                self.assertTrue(skill['source_materials'][0]['content'].startswith('Skill body'))
                seeded = [c for c in cases if c['source_metadata'].get('deliverable_search')]
                self.assertEqual(sorted(c['task_id'] for c in seeded), ['deliverable-11-1011-00', 'deliverable-13-2011-00'])
                self.assertTrue(all(c['stage'] == '01c_deliverable' and c['source_materials'] == [] for c in seeded))
                self.assertEqual([c['source_metadata']['deliverable_url'] for c in cases if c['source_metadata'].get('deliverable_url')], ['https://example.org/plan.pdf'])
                from workfactory.pipeline import pipeline_config
                loaded = pipeline_config.source_cases({**pipeline_config.load_policy(), 'source_cases': str(data / 'cases.json')})
                self.assertEqual(len(loaded), 8)
                wider = source_pools.build_cases(0, 0, 1, -1, str(table), ('yes', 'limited'))
                self.assertEqual((wider['occupation_cases'], wider['mixed_cases']), (3, 2))
                with self.assertRaises(ValueError):
                    source_pools.build_cases(0, 0, 1, 5, str(table), ('yes',))
                with self.assertRaises(ValueError):
                    source_pools.build_cases(0, 2, 1, 0, str(table), ('yes',))
                manifest.write_text(json.dumps([{'url': 'http://insecure.example/a.pdf'}]))
                with self.assertRaises(ValueError):
                    source_pools.build_cases(0, 0, 1, 0, str(table), ('yes',), 0, None, str(manifest))
                table.write_text('onet_code,digitizable,digitizable_reason,mixed_route,supplemental_search\n11-1011.00,yes,a,yes,\n')
                with self.assertRaises(ValueError):
                    source_pools.build_cases(0, 0, 1, 0, str(table), ('yes',))

    def test_committed_filter_table_is_consistent(self):
        from workfactory.sources.source_pools import occupation_filter
        known, allowed = occupation_filter('config/occupation-filter.csv', ('yes',))
        self.assertEqual(len(known), 1016)
        self.assertTrue(all(v['digitizable'] == 'yes' for v in allowed.values()))
        _, every = occupation_filter('config/occupation-filter.csv', ('yes', 'limited', 'no'))
        self.assertFalse(any(v['mixed_route'] and v['digitizable'] == 'no' for v in every.values()))


if __name__ == '__main__':
    unittest.main()
