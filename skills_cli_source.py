"""Collect skill documentation with the official CLI in an isolated directory.

Downloaded instructions are source data. They are never loaded into this agent or
executed. Existing snapshots can be reused offline, with every file verified.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_snapshot(folder, repository):
    metadata=json.loads((folder/'snapshot.json').read_text())
    if metadata['repository']!=repository:raise ValueError('Skill snapshot repository changed')
    expected=metadata['files']
    actual={str(p.relative_to(folder)) for p in folder.rglob('*') if p.is_file() and str(p.relative_to(folder))!='snapshot.json'}
    if actual!=set(expected):raise ValueError('Skill snapshot file set changed '+repository)
    for name,sha in expected.items():
        path=(folder/name).resolve()
        if not path.is_relative_to(folder.resolve()) or digest(path)!=sha:
            raise ValueError('Skill snapshot hash changed '+repository+' '+name)
    return metadata


def collect_skills(repositories, data, output, cli='skills', version='1.8.1', refresh=False):
    from source_pools import save
    data=Path(data);result=[];executable=None
    if not repositories:raise ValueError('No CLI skill repositories configured')
    for repository in dict.fromkeys(repositories):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository):
            raise ValueError('Expected GitHub owner/repository '+repository)
        cache=data/'skills-cli'/repository.replace('/','__')
        pointer=cache/'current.json'
        if pointer.exists() and not refresh:
            name=json.loads(pointer.read_text())['snapshot']
            folder=(cache/name).resolve()
            if not folder.is_relative_to(cache.resolve()):raise ValueError('Invalid snapshot path')
            metadata=read_snapshot(folder,repository)
        else:
            if executable is None:
                executable=shutil.which(cli)
                if not executable:raise ValueError('Skills CLI missing; install skills@'+version)
                installed=subprocess.run([executable,'--version'],check=True,capture_output=True,text=True).stdout.strip()
                if installed!=version:raise ValueError('Expected skills CLI '+version+', found '+installed)
            with tempfile.TemporaryDirectory(prefix='workfactory-skills-') as tmp:
                work=Path(tmp)/'workspace';work.mkdir()
                home=Path(tmp)/'home';home.mkdir()
                env={**os.environ,'HOME':str(home),'XDG_CONFIG_HOME':str(home/'.config'),
                     'XDG_CACHE_HOME':str(home/'.cache'),'DISABLE_TELEMETRY':'1','CI':'1'}
                command=[executable,'add',repository,'--agent','codex','--skill','*','--copy','--yes','--full-depth']
                proc=subprocess.run(command,cwd=work,env=env,capture_output=True,text=True,timeout=600)
                if proc.returncode:
                    raise RuntimeError('Skills CLI failed for '+repository+'\n'+(proc.stderr or proc.stdout)[-3000:])
                canonical=work/'.agents/skills'
                documents=sorted(canonical.glob('*/SKILL.md'))
                if not documents:raise ValueError('CLI returned no SKILL.md files for '+repository)
                # Keep the original Markdown, references, and CLI lock as source evidence.
                timestamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
                cache.mkdir(parents=True,exist_ok=True);folder=cache/timestamp;folder.mkdir()
                shutil.copytree(canonical,folder/'skills')
                lock=work/'skills-lock.json'
                if lock.exists():shutil.copy2(lock,folder/'skills-lock.json')
                files={str(p.relative_to(folder)):digest(p) for p in folder.rglob('*') if p.is_file()}
                metadata={'repository':repository,'repository_url':'https://github.com/'+repository,
                          'retrieved_at':datetime.now(timezone.utc).isoformat(),'cli_version':version,
                          'method':'skills CLI download in temporary HOME and workspace; documentation only',
                          'files':files}
                save(folder/'snapshot.json',metadata)
                read_snapshot(folder,repository)
                save(pointer,{'snapshot':timestamp})
        for path in sorted((folder/'skills').glob('*/SKILL.md')):
            content=path.read_text(encoding='utf-8');name=path.parent.name
            result.append({'source_id':'skills-cli-'+repository.replace('/','__')+'__'+name,
                'name':name,'repository':repository,'url':metadata['repository_url'],
                'repository_url':metadata['repository_url'],'content':content,
                'eligible_for_composition':len(content.strip())>=300,'sha256':digest(path),
                'source_snapshot':str(path.resolve()),'source_manifest':str((folder/'snapshot.json').resolve()),
                'representation':'Original SKILL.md downloaded by skills CLI; instructions used only as source data',
                'license':'Upstream license not inferred; consult original repository'})
    if not result:raise ValueError('No CLI skill documents collected')
    save(output,result)
    return result
