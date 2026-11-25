"""Export WorkFactory's clean environment to a self-contained Harbor task.

No model calls, source downloads, or teacher answers are included in the image.
A verifier must be supplied explicitly to produce an evaluation-ready package.
"""
import argparse
import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _files(root):
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('Symlinks are not allowed in Harbor packages ' + str(path))
        if path.is_file():
            yield path


def export_task(task_id, environment, output, verifier=None):
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*', task_id) or '..' in task_id:
        raise ValueError('Invalid task ID')
    environment = Path(environment).resolve()
    output = Path(output).absolute()
    if output.exists():
        raise FileExistsError('Choose a new export directory to preserve existing tasks')
    request = environment / 'REQUEST.txt'
    inputs = environment / 'inputs'
    if not request.is_file() or not inputs.is_dir():
        raise ValueError('Clean environment requires REQUEST.txt and inputs/')
    allowed = [request, *list(_files(inputs))]
    if request.is_symlink() or inputs.is_symlink():
        raise ValueError('Source symlinks are not allowed')
    if not request.read_text().strip():
        raise ValueError('Empty task instruction')
    # Refuse to package environments containing answers or hidden build metadata.
    actual = set(_files(environment))
    if actual != set(allowed):
        raise ValueError('Export only a clean environment with REQUEST.txt and inputs/')
    verifier_files = []
    if verifier is not None:
        verifier = Path(verifier).resolve()
        if not (verifier/'test.sh').is_file():
            raise ValueError('Verifier directory must contain test.sh')
        verifier_files = list(_files(verifier))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.harbor-export-', dir=output.parent) as temp:
        package = Path(temp)/task_id
        workspace = package/'environment/workspace'
        workspace.mkdir(parents=True)
        shutil.copyfile(request, workspace/'REQUEST.txt')
        shutil.copytree(inputs, workspace/'inputs')
        (package/'instruction.md').write_text(request.read_text() +
            '\n\nWork in /task. Reference files are in /task/inputs. '
            'Write final deliverables to /task/outputs. External network access is disabled.\n')
        # Build from the tracked recipe, not a developer-machine image tag.
        recipe = (ROOT/'docker/Dockerfile').read_text()
        recipe += '''\nUSER root
COPY workspace/ /task/
RUN mkdir -p /task/outputs && chown -R root:root /task/inputs /task/REQUEST.txt && chmod -R a-w /task/inputs /task/REQUEST.txt && chmod 755 /task && chown worker:worker /task/outputs
USER worker
WORKDIR /task
'''
        (package/'environment/Dockerfile').write_text(recipe)
        ready = verifier is not None
        (package/'task.toml').write_text(
            'schema_version = "1.4"\n\n[task]\nname = ' + json.dumps('workfactory/'+task_id) +
            '\n\n[metadata]\nsource_pipeline = "workfactory"\nverifier_ready = '+str(ready).lower()+
            '\n\n[agent]\nuser = "worker"\nnetwork_mode = "no-network"\n'
            '\n[environment]\nnetwork_mode = "no-network"\ncpus = 1\nmemory_mb = 2048\nstorage_mb = 10240\nbuild_timeout_sec = 1800.0\n'
            '\n[verifier]\ntimeout_sec = 600.0\n')
        if verifier is not None:
            tests = package/'tests';tests.mkdir()
            for source in verifier_files:
                dest=tests/source.relative_to(verifier);dest.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(source,dest)
            (tests/'test.sh').chmod(0o755)
        manifest = {
            'task_id': task_id, 'format': 'harbor', 'schema_version': '1.4',
            'verifier_status': 'provided_not_runtime_validated' if ready else 'pending',
            'runtime_validated': False,
            'reference_sha256': {str(p.relative_to(environment)):hashlib.sha256(p.read_bytes()).hexdigest() for p in allowed},
        }
        manifest['package_sha256'] = {str(p.relative_to(package)):hashlib.sha256(p.read_bytes()).hexdigest() for p in _files(package)}
        (package/'export_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        package.rename(output)
    return manifest


def ensure_task(task_id, environment, output):
    """Resume only an unchanged export of the same clean environment."""
    output = Path(output)
    if not output.exists():
        return export_task(task_id, environment, output)
    manifest = json.loads((output/'export_manifest.json').read_text())
    expected = manifest['reference_sha256']
    actual = {str(p.relative_to(environment)):hashlib.sha256(p.read_bytes()).hexdigest()
              for p in _files(Path(environment))}
    package_hashes = {str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in _files(output) if p != output/'export_manifest.json'}
    if manifest['task_id'] != task_id or actual != expected or package_hashes != manifest.get('package_sha256'):
        raise ValueError('Harbor export changed; choose a new output directory')
    return manifest


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--task-id',required=True)
    parser.add_argument('--environment',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--verifier',help='Approved verifier directory containing test.sh')
    args=parser.parse_args()
    print(json.dumps(export_task(args.task_id,args.environment,args.output,args.verifier),indent=2))


if __name__ == '__main__':
    main()
