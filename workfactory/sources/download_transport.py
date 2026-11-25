"""Bounded same-URL retries; no mirrors or access-control bypass."""
import http.client
import json
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

LIMIT = 20 * 1024 * 1024


def fetch_bytes(url, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    partial = folder / 'download.part'
    # Unvalidated partial bytes must never be joined with a new representation.
    if partial.exists():
        index = 1
        while (folder / f'download.previous-{index:02d}.part').exists():
            index += 1
        partial.rename(folder / f'download.previous-{index:02d}.part')
    parts = b''
    validator = None
    known_total = None

    def event(**fields):
        with (folder / 'download_events.jsonl').open('a') as handle:
            handle.write(json.dumps(fields) + '\n')

    for segment in range(32):
        offset = len(parts)
        for retry in range(3):
            headers = {'User-Agent': 'WorkFactoryResearch/1.0',
                       'Accept-Encoding': 'identity',
                       'Range': f'bytes={offset}-{offset + 1048575}'}
            if validator:
                headers['If-Range'] = validator
            try:
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=90) as response:
                    import re
                    if response.headers.get('Content-Encoding', 'identity').lower() not in ('identity', ''):
                        raise ValueError('Unsupported Content-Encoding for byte-range download')
                    cr = response.headers.get('Content-Range')
                    total = None
                    expected = None
                    if response.status == 206:
                        match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', cr or '')
                        if not match or int(match[1]) != offset or not offset <= int(match[2]) < int(match[3]):
                            raise ValueError('Invalid Content-Range')
                        expected = int(match[2]) - offset + 1
                        total = int(match[3])
                        if known_total is not None and total != known_total:
                            raise ValueError('Remote file length changed during download')
                    elif response.status == 200:
                        length = response.headers.get('Content-Length')
                        expected = total = int(length) if length else None
                    else:
                        raise ValueError('Unsupported download status ' + str(response.status))
                    if total is not None and total > LIMIT:
                        raise ValueError('Deliverable exceeds 20 MiB')
                    current_validator = response.headers.get('ETag')
                    if current_validator and current_validator.startswith('W/'):
                        current_validator = None
                    current_validator = current_validator or response.headers.get('Last-Modified')
                    if response.status == 206 and validator and current_validator and validator != current_validator:
                        raise ValueError('Remote file version changed during download')
                    body = response.read(LIMIT + 1)
                    if len(body) > LIMIT:
                        raise ValueError('Deliverable exceeds 20 MiB')
                    if expected is not None and len(body) != expected:
                        raise http.client.IncompleteRead(body, max(0, expected - len(body)))
                    if not body:
                        raise http.client.IncompleteRead(b'', 1)
                    parts = body if response.status == 200 else parts + body
                    if len(parts) > LIMIT:
                        raise ValueError('Deliverable exceeds 20 MiB')
                    validator = current_validator or validator
                    known_total = total
                    partial.write_bytes(parts)
                    event(segment=segment, retry=retry, offset=offset, received=len(body), total=total, status=response.status)
                    if response.status == 200 or len(parts) == total:
                        return parts, response.geturl(), dict(response.headers), total
                    break
            except (urllib.error.URLError, http.client.HTTPException, socket.timeout, ConnectionError) as exc:
                status = exc.code if isinstance(exc, urllib.error.HTTPError) else None
                transient = status is None or status in (408, 429, 500, 502, 503, 504)
                category = 'access_denied' if status in (401, 403) else ('not_found' if status in (404, 410) else 'transport')
                event(segment=segment, retry=retry, status=status, category=category, error_type=type(exc).__name__)
                if not transient or retry == 2:
                    raise
                delay = 2 ** retry
                if status == 429:
                    value = exc.headers.get('Retry-After', '')
                    if value.isdigit():
                        delay = min(int(value), 60)
                time.sleep(delay)
    raise ValueError('Incomplete HTTP download after 32 range requests')
