"""Cross-process API slots on one host. Locks release automatically on crash.

All jobs sharing an API credential must use the same slot directory and limit.
This does not coordinate multiple hosts; use one runner host per credential.
"""
import fcntl
import hashlib
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def api_slot(config):
    limit = int(config.get('API_MAX_CONCURRENCY', 1))
    if limit < 1:
        raise ValueError('API_MAX_CONCURRENCY must be positive')
    scope=config.get('API_LIMIT_SCOPE','credential')
    if scope not in {'credential','model'}:raise ValueError('Unknown API limit scope')
    identity = hashlib.sha256((config.get('OPENAI_BASE_URL','')+'\0'+config['OPENAI_API_KEY']+
        ('\0'+config['OPENAI_MODEL'] if scope=='model' else '')).encode()).hexdigest()
    root = Path(config.get('API_LOCK_DIR',Path.home()/'.cache/workfactory/api-locks'))/identity
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Never silently permit a second controller with a different limit.
    with (root/'config.lock').open('a+') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        policy = root/'limit.json'
        if policy.exists() and json.loads(policy.read_text())['limit'] != limit:
            raise ValueError('Shared API limit differs; stop all jobs before changing lock configuration')
        policy.write_text(json.dumps({'limit':limit}))
    selected = None
    try:
        while selected is None:
            for index in range(limit):
                candidate = (root/f'{index}.lock').open('a+')
                try:
                    fcntl.flock(candidate, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    selected = candidate
                    break
                except BlockingIOError:
                    candidate.close()
            if selected is None:
                time.sleep(0.1)
        yield
    finally:
        if selected:
            selected.close()
