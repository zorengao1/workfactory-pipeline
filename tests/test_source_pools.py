import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from source_pools import SOCParser,SkillText,balanced,related_skill_bundles,fetch,fetch_soc


class SourcePoolTests(unittest.TestCase):
    def test_soc_keeps_hierarchy_and_definitions_separate(self):
        parser=SOCParser()
        parser.feed('<ul><li>23-0000 Legal<ul><li>23-1000 Lawyers<ul><li>23-1010 Lawyers and Clerks<ul><li>23-1011 <a>Lawyers</a><div class="answer"><p>Represent clients.</p></div></li></ul></li></ul></li></ul></li></ul>')
        row=parser.records['23-1011']
        self.assertEqual(row['title'],'Lawyers')
        self.assertEqual(row['description'],'Represent clients.')
        self.assertEqual(row['parent_code'],'23-1010')
        self.assertNotIn('Represent',parser.records['23-0000']['title'])

    def test_skill_capture_excludes_summary_and_navigation(self):
        parser=SkillText();parser.feed('<div class="prose">summary</div><span>SKILL.md</span><div><div class="prose"><h1>Analysis</h1><div>Inputs and outputs</div></div></div><nav>footer</nav>')
        text=''.join(parser.text)
        self.assertIn('Inputs and outputs',text)
        self.assertNotIn('summary',text)
        self.assertNotIn('footer',text)

    def test_balanced_sampling_covers_groups_before_second_member(self):
        items=[{'soc_major':'11','id':i} for i in range(4)]+[{'soc_major':'23','id':9}]
        sampled=balanced(items,42)
        self.assertEqual({r['soc_major'] for r in sampled[:2]},{'11','23'})
        self.assertEqual(sampled,balanced(items,42))

    def test_cache_tampering_is_rejected_before_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'source.html';p.write_text('changed')
            p.with_suffix('.html.source.json').write_text(json.dumps({'url':'https://example.org','sha256':'old'}))
            with patch('source_pools.urllib.request.urlopen') as network:
                with self.assertRaises(ValueError):fetch('https://example.org',p)
                network.assert_not_called()

    def test_real_bls_snapshot_has_expected_coverage(self):
        root=Path(__file__).resolve().parents[1]
        parser=SOCParser();parser.feed((root/'resources/soc-2018/major_groups.html').read_text())
        self.assertEqual(sum(r['code'].endswith('-0000') for r in parser.records.values()),23)
        self.assertEqual(sum(not r['code'].endswith('0') for r in parser.records.values()),867)

    def test_clean_checkout_can_load_bls_snapshot_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('source_pools.DATA',Path(tmp)), patch('source_pools.urllib.request.urlopen') as network:
                records=fetch_soc()
                self.assertEqual(len(records),1447)
                network.assert_not_called()
                self.assertTrue((Path(tmp)/'soc.json').is_file())

    def test_alias_documents_are_not_proposed_for_composition(self):
        skills=[{'name':'a','content':'extract quote table prices','eligible_for_composition':True},
                {'name':'b','content':'compare quote table prices costs','eligible_for_composition':True},
                {'name':'alias','content':'call another skill','eligible_for_composition':False}]
        bundles=related_skill_bundles(skills,2,42)
        self.assertTrue(all(s['name']!='alias' for b in bundles for s in b))


if __name__=='__main__':unittest.main()
