import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from skills_cli_source import collect_skills


class SkillsCLISourceTests(unittest.TestCase):
    def fake_cli(self, command, **kwargs):
        if command[-1]=='--version':
            return subprocess.CompletedProcess(command,0,'1.8.1\n','')
        work=Path(kwargs['cwd'])
        self.assertNotEqual(kwargs['env']['HOME'],str(Path.home()))
        self.assertEqual(kwargs['env']['DISABLE_TELEMETRY'],'1')
        self.assertIn('--copy',command)
        folder=work/'.agents/skills/reporting';folder.mkdir(parents=True)
        (folder/'SKILL.md').write_text('# Reporting\n'+('Read evidence and produce reports. '*20))
        (folder/'reference.txt').write_text('Supporting source')
        (work/'skills-lock.json').write_text('{"version":1,"skills":{}}')
        return subprocess.CompletedProcess(command,0,'installed','')

    def collect(self, tmp):
        with patch('skills_cli_source.shutil.which',return_value='/test/skills'),patch('skills_cli_source.subprocess.run',side_effect=self.fake_cli):
            return collect_skills(['example/reports'],Path(tmp),Path(tmp)/'skills.json')

    def test_original_markdown_references_and_lock_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            records=self.collect(tmp)
            self.assertEqual(len(records),1)
            self.assertTrue(records[0]['eligible_for_composition'])
            skill=Path(records[0]['source_snapshot'])
            self.assertTrue((skill.parent/'reference.txt').is_file())
            metadata=json.loads(Path(records[0]['source_manifest']).read_text())
            self.assertIn('skills-lock.json',metadata['files'])
            self.assertEqual(records[0]['repository'],'example/reports')

    def test_cached_collection_is_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            expected=self.collect(tmp)
            with patch('skills_cli_source.subprocess.run') as run,patch('skills_cli_source.shutil.which') as which:
                records=collect_skills(['example/reports'],Path(tmp),Path(tmp)/'offline.json')
                self.assertEqual(records,expected)
                run.assert_not_called();which.assert_not_called()

    def test_changed_reference_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            records=self.collect(tmp)
            (Path(records[0]['source_snapshot']).parent/'reference.txt').write_text('changed')
            with self.assertRaisesRegex(ValueError,'hash changed'):
                collect_skills(['example/reports'],Path(tmp),Path(tmp)/'out.json')

    def test_failure_preserves_previous_pool(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'skills.json';output.write_text('previous pool')
            with patch('skills_cli_source.shutil.which',return_value='/test/skills'),patch('skills_cli_source.subprocess.run',side_effect=[subprocess.CompletedProcess([],0,'1.8.1\n',''),subprocess.CompletedProcess([],1,'','download failed')]):
                with self.assertRaisesRegex(RuntimeError,'download failed'):
                    collect_skills(['example/reports'],Path(tmp),output)
            self.assertEqual(output.read_text(),'previous pool')


if __name__=='__main__':unittest.main()
