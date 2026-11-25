"""Persistent macOS launchd runner. No credential values enter the plist."""
import argparse
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from workfactory.paths import ROOT


def identity(output):
    return 'com.workfactory.batch.' + hashlib.sha256(str(Path(output).resolve()).encode()).hexdigest()[:16]


def make_job(output, credentials, policy, models):
    output = Path(output).resolve()
    return {
        'Label': identity(output),
        'ProgramArguments': [sys.executable, '-u', '-m','workfactory.operations.run_models',
                             '--config', str(Path(credentials).resolve()),
                             '--pipeline-config', str(Path(policy).resolve()),
                             '--output', str(output), '--models', *models],
        'WorkingDirectory': str(ROOT), 'RunAtLoad': True,
        'EnvironmentVariables': {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'PYTHONUNBUFFERED': '1'},
        'StandardOutPath': str(output/'service.stdout.log'),
        'StandardErrorPath': str(output/'service.stderr.log'),
        'ExitTimeOut': 30,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'status', 'stop'])
    parser.add_argument('--output', required=True)
    parser.add_argument('--config')
    parser.add_argument('--pipeline-config')
    parser.add_argument('--models', nargs='+', choices=['deepseek-v4.1-flash-1017', 'mimo-v2.6-flash', 'gpt-6.1-sol'],
                        default=['deepseek-v4.1-flash-1017', 'mimo-v2.6-flash'])
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('This service uses macOS launchd; other service managers are not implemented')
    output = Path(args.output).resolve()
    domain = f'gui/{os.getuid()}'
    target = domain + '/' + identity(output)
    probe = subprocess.run(['launchctl', 'print', target], capture_output=True, text=True)
    if args.action == 'status':
        print(probe.stdout if probe.returncode == 0 else 'Service is not loaded')
        for path in sorted(output.glob('*/status.json')):
            print(path)
            print(path.read_text())
        return
    if args.action == 'stop':
        if probe.returncode == 0:
            subprocess.run(['launchctl', 'bootout', target], check=True)
        print('Stopped; saved attempts retained. Interrupted tools may require audit before restart.')
        return
    if probe.returncode == 0:
        parser.error('Service already loaded. Inspect status and stop before explicitly restarting.')
    if not args.config or not args.pipeline_config:
        parser.error('start requires --config and --pipeline-config')
    for path in (args.config, args.pipeline_config):
        if not Path(path).is_file():
            parser.error('Missing file ' + path)
    from workfactory.pipeline.pipeline_config import load_policy, source_cases
    from workfactory.runtime.preflight import check_runtime
    policy = load_policy(args.pipeline_config)
    source_cases(policy)
    check_runtime(policy)
    output.mkdir(parents=True, exist_ok=True)
    job = make_job(output, args.config, args.pipeline_config, args.models)
    # Pin Docker's executable directory into launchd's noninteractive PATH.
    docker = shutil.which('docker')
    if docker:
        job['EnvironmentVariables']['PATH'] = str(Path(docker).parent) + ':' + job['EnvironmentVariables']['PATH']
    plist = output/'service.plist'
    with plist.open('wb') as handle:
        plistlib.dump(job, handle)
    plist.chmod(0o600)
    subprocess.run(['launchctl', 'bootstrap', domain, str(plist)], check=True)
    print('Started ' + target)
    print('Logs ' + str(output))


if __name__ == '__main__':
    main()
