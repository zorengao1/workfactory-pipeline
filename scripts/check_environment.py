"""Verify Docker isolation and multi-format I/O without calling any model API."""
import json
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from docker_runtime import DockerRuntime


def main():
    with tempfile.TemporaryDirectory(prefix='workfactory-check-') as tmp:
        root=Path(tmp)
        (root/'inputs').mkdir()
        (root/'inputs'/'protected.txt').write_text('original')
        (root/'check.py').write_text((ROOT/'scripts/container_smoke.py').read_text())
        runtime=DockerRuntime(root,('outputs',),{'image':'workfactory/runtime:v2'},root/'logs')
        try:
            result=runtime.execute('python /task/check.py')
            if result['exit_code']:
                raise RuntimeError(json.dumps(result))
            forbidden=runtime.execute('echo changed > /task/inputs/protected.txt')
            if forbidden['exit_code']==0 or (root/'inputs/protected.txt').read_text()!='original':
                raise RuntimeError('Read-only input isolation failed')
            print(result['stdout'].strip())
            print('Read-only input isolation passed')
        finally:
            runtime.close()


if __name__=='__main__':main()
