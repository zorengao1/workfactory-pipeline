"""Bounded online CLI discovery. Skills are untrusted source data, never executed."""
import copy
import fcntl
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from workfactory.pipeline.contracts import ROOT, TEXT, array, obj, string, validate
from workfactory.clients.pilot import complete

DEFAULTS = dict(enabled=True, cli='skills', cli_version='1.8.1',
                initial_queries=3, per_query=5, initial_candidates=15,
                extra_candidates=10, max_research_rounds=2, max_candidates=35,
                min_selected=2, max_selected=4, min_operations=6, min_chain_depth=4,
                cache_dir='data/skills_discovery_cache', cache_ttl_seconds=86400,
                request_timeout=60)
CAP = obj(id=TEXT, operation=TEXT, input=TEXT, output=TEXT)
PLAN = obj(objective=TEXT, capabilities=array(CAP, 3), queries=array(TEXT, 3, 3))
SELECTED = obj(source_id=TEXT, capability_ids=array(TEXT, 1), evidence_quote=TEXT,
               role=TEXT, inputs=array(TEXT, 1), outputs=array(TEXT, 1))
STEP = obj(id=TEXT, source_id=TEXT, operation=TEXT, input=TEXT, output=TEXT,
           depends_on=array(TEXT))
RESOURCE = obj(name=TEXT, provision=string('provided', 'synthesize', 'unavailable'), reason=TEXT)
REVIEW = obj(decision=string('ready', 'search', 'reject'),
             selected=array(SELECTED), steps=array(STEP), resources=array(RESOURCE, 1),
             missing_capabilities=array(TEXT), next_queries=array(TEXT, maximum=3),
             rejections=array(obj(source_id=TEXT, reason=TEXT)), explanation=TEXT)


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def settings(config):
    policy = {**DEFAULTS, **config.get('_POLICY', {}).get('skill_discovery', {})}
    for key in ('per_query', 'initial_candidates', 'extra_candidates', 'max_candidates',
                'min_selected', 'max_selected', 'min_operations', 'min_chain_depth',
                'cache_ttl_seconds', 'request_timeout'):
        if type(policy[key]) is not int or policy[key] < 1:
            raise ValueError('Invalid skill discovery setting ' + key)
    if policy['initial_queries'] != 3 or type(policy['max_research_rounds']) is not int or policy['max_research_rounds'] < 0:
        raise ValueError('Expected three initial queries and nonnegative retry rounds')
    if policy['min_selected'] > policy['max_selected']:
        raise ValueError('Invalid selected skill range')
    return policy


class DiscoveryRejected(ValueError):
    pass


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {'p', 'li', 'h1', 'h2', 'h3', 'pre', 'tr', 'br', 'hr'}:
            self.parts.append('\n')

    def handle_data(self, data):
        self.parts.append(data)


def full_skill_text(html):
    """Read preview AND restHtml from public Next.js page data, without running JS."""
    chunks = []
    for match in re.finditer(r'self\.__next_f\.push\((.*?)\)</script>', html, re.S):
        try:
            item = json.loads(match[1])
        except ValueError:
            continue
        if isinstance(item, list) and len(item) > 1 and item[0] == 1 and isinstance(item[1], str):
            chunks.append(item[1])
    flight = ''.join(chunks)
    def field(name):
        found = re.search('"' + name + r'"\s*:\s*("(?:\\.|[^"\\])*")', flight)
        if not found:
            raise ValueError('Full skill page field missing ' + name)
        value = json.loads(found[1])
        if value.startswith('$'):
            ref = re.search(re.escape(value[1:]) + r':T([0-9a-f]+),', flight)
            if not ref:
                raise ValueError('Unresolved skill page body reference')
            length = int(ref[1], 16)
            raw = flight[ref.end():].encode()[:length]
            if len(raw) != length:
                raise ValueError('Truncated skill page data')
            return raw.decode()
        return value
    parser = PageText()
    parser.feed(field('previewHtml') + field('restHtml'))
    text = ''.join(parser.parts).strip()
    if not text:
        raise ValueError('Skill body is empty')
    return text


def search_cli(query, folder, policy):
    """Use installed official CLI, observing HTTP failures that CLI otherwise hides."""
    folder.mkdir(parents=True, exist_ok=True)
    observer = ROOT / 'scripts/skills_http_observer.cjs'
    env = {**os.environ, 'DISABLE_TELEMETRY': '1', 'NO_COLOR': '1'}
    env['NODE_OPTIONS'] = env.get('NODE_OPTIONS', '') + ' --require ' + json.dumps(str(observer))
    for attempt in range(3):
        proc = subprocess.run([policy['cli'], 'find', query], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=policy['request_timeout'], env=env)
        events = [json.loads(line[len('WF_SEARCH '):]) for line in proc.stderr.splitlines()
                  if line.startswith('WF_SEARCH ')]
        save(folder / f'attempt-{attempt}.json', dict(query=query, stdout=proc.stdout,
             stderr=proc.stderr, exit_code=proc.returncode, http=events))
        failed = [e for e in events if e.get('status') != 200]
        if any(e.get('valid_payload') is False for e in events):
            raise ValueError('Skills search response schema changed')
        if not proc.returncode and events and not failed:
            # Consume structured IDs actually returned to CLI, in CLI output order.
            known = {s['id']: s for e in events for s in e.get('skills', [])}
            urls = re.findall(r'https://skills\.sh/([^\s\x1b]+)', proc.stdout)
            result = []
            seen = set()
            for key in urls:
                if key in known and key not in seen:
                    seen.add(key)
                    result.append({**known[key], 'url': 'https://www.skills.sh/' + key})
            if known and not result:
                raise ValueError('CLI output format changed')
            return result
        transient = failed and all(e.get('status') is None or e.get('status') in (429, 500, 502, 503, 504) for e in failed)
        if not transient or attempt == 2:
            raise RuntimeError('Skills CLI search failed; see HTTP audit, not a zero-match result')
        time.sleep(min(30, max([2 ** attempt] + [e.get('retry_after', 0) for e in failed])))
    raise RuntimeError('Skills CLI retry exhausted')


def read_skill(record, cache, policy):
    key = digest(record['id'])
    folder = cache / key
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'cache.lock').open('a+') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        meta_path = folder / 'current.json'
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            text = (folder / meta['text_file']).read_text()
            if digest(text) != meta['sha256']:
                raise ValueError('Skill cache checksum changed')
            if time.time() - meta['fetched_at'] < policy['cache_ttl_seconds']:
                return {**record, **meta, 'content': text}
        for attempt in range(3):
            try:
                with urllib.request.urlopen(record['url'], timeout=policy['request_timeout']) as response:
                    raw = response.read(8 * 1024 * 1024 + 1)
                break
            except (urllib.error.URLError, TimeoutError) as exc:
                if isinstance(exc, urllib.error.HTTPError) and exc.code not in (429, 500, 502, 503, 504):
                    raise
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError('Skill page exceeds 8 MiB')
        version = hashlib.sha256(raw).hexdigest()
        (folder / (version + '.html')).write_bytes(raw)
        text = full_skill_text(raw.decode())
        sha = digest(text)
        (folder / (sha + '.txt')).write_text(text)
        meta = dict(sha256=sha, text_file=sha + '.txt', fetched_at=time.time(),
                    snapshot=str((folder / (version + '.html')).resolve()),
                    source_id='skill-' + key[:24])
        save(meta_path, meta)
        return {**record, **meta, 'content': text}


def ask(kind, payload, schema, folder, config):
    path = folder / (kind + '.json')
    if path.exists():
        stored = json.loads(path.read_text())
        if stored['input'] != payload:
            raise ValueError('Skill review checkpoint input changed')
        return stored['output']
    prompt = (ROOT / 'prompts' / ('skills_' + kind.split('-')[0] + '.txt')).read_text()
    messages = [{'role': 'system', 'content': prompt + '\nJSON Schema\n' + json.dumps(schema)},
                {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]
    request = dict(model=config['OPENAI_MODEL'], messages=messages)
    audit = folder / (kind + '-attempts')
    audit.mkdir(exist_ok=True)
    attempt_dir = audit / f'{len(list(audit.iterdir())):04d}'
    attempt_dir.mkdir()
    save(attempt_dir / 'request.json', request)
    response = complete(config, messages, int(config.get('MAX_OUTPUT_TOKENS', 16384)))
    save(attempt_dir / 'response.json', response)
    if response['choices'][0].get('finish_reason') == 'length':
        raise ValueError('Skill model response truncated')
    result = json.loads(response['choices'][0]['message']['content'])
    errors = validate(result, schema)
    if errors:
        raise ValueError('Invalid skill model output ' + '; '.join(errors))
    save(path, dict(input=payload, output=result))
    return result


def review_errors(plan, review, documents, policy, synthesis_allowed):
    """Structural checks supplement, never replace, semantic model review."""
    errors = []
    candidates = {d['source_id']: d for d in documents}
    caps = {c['id'] for c in plan['capabilities']}
    chosen = review['selected']
    ids = [s['source_id'] for s in chosen]
    if not policy['min_selected'] <= len(set(ids)) == len(ids) <= policy['max_selected']:
        errors.append('Select distinct complementary skills within configured range')
    covered = set()
    for s in chosen:
        doc = candidates.get(s['source_id'])
        if not doc or s['evidence_quote'] not in doc['content']:
            errors.append('Selected skill lacks verbatim body evidence')
        covered.update(s['capability_ids'])
    if covered != caps:
        errors.append('Required capabilities not fully covered or unknown IDs used')
    if review['missing_capabilities']:
        errors.append('Unresolved capability gaps')
    for r in review['resources']:
        if r['provision'] == 'unavailable' or (r['provision'] == 'synthesize' and not synthesis_allowed):
            errors.append('Unavailable required resource ' + r['name'])
    steps = review['steps']
    depths = {}
    used = set()
    if len(steps) < policy['min_operations']:
        errors.append('Too few substantive operations')
    operations = set()
    for step in steps:
        if step['source_id'] not in ids:
            errors.append('Step refers to unselected skill')
        used.add(step['source_id'])
        operations.add(step['operation'].strip().lower())
        if step['id'] in depths or any(dep not in depths for dep in step['depends_on']):
            errors.append('Workflow must be an ordered acyclic dependency graph')
            continue
        depths[step['id']] = 1 + max([depths[d] for d in step['depends_on']] or [0])
    if used != set(ids) or len(operations) < policy['min_operations']:
        errors.append('Unused skills or duplicated operations')
    if max(depths.values(), default=0) < policy['min_chain_depth']:
        errors.append('Insufficient dependent workflow depth')
    return errors


def enrich_skills(case, folder, config):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    policy = settings(config)
    checkpoint = dict(case=case, policy=policy, model=config['OPENAI_MODEL'])
    with (folder / 'run.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _enrich(case, folder, config, policy, checkpoint)


def _enrich(case, folder, config, policy, checkpoint):
    start = folder / 'input.json'
    if start.exists() and json.loads(start.read_text()) != checkpoint:
        raise ValueError('Skill discovery configuration changed; use a new run directory')
    save(start, checkpoint)
    if (folder / 'enriched.json').exists():
        return json.loads((folder / 'enriched.json').read_text())
    version = subprocess.run([policy['cli'], '--version'], capture_output=True, text=True, check=True).stdout.strip()
    if version != policy['cli_version']:
        raise ValueError('Expected skills CLI ' + policy['cli_version'] + ', got ' + version)
    plan = ask('plan', {'case': case, 'policy': policy}, PLAN, folder, config)
    if len({c['id'] for c in plan['capabilities']}) != len(plan['capabilities']):
        raise ValueError('Duplicate capability IDs')
    queries = plan['queries']
    if len({q.strip().casefold() for q in queries}) != 3:
        raise ValueError('Three distinct initial search queries required')
    previous_feedback = []
    attempted = set()
    documents = []
    seen_hashes = set()
    tried_queries = set()
    cache = Path(policy['cache_dir'])
    if not cache.is_absolute():
        cache = ROOT / cache
    for round_no in range(policy['max_research_rounds'] + 1):
        round_dir = folder / f'round-{round_no:02d}'
        round_dir.mkdir(exist_ok=True)
        budget = policy['initial_candidates'] if round_no == 0 else policy['extra_candidates']
        shortlists = []
        for i, query in enumerate(queries):
            if query.strip().casefold() in tried_queries:
                continue
            tried_queries.add(query.strip().casefold())
            result_path = round_dir / f'query-{i}.json'
            if result_path.exists():
                result = json.loads(result_path.read_text())
            else:
                result = search_cli(query, round_dir / f'query-{i}', policy)
                save(result_path, result)
            shortlists.append(result[:policy['per_query']])
        # Round-robin preserves different search facets under the per-round budget.
        picked = [lst[i] for i in range(policy['per_query']) for lst in shortlists if i < len(lst)]
        added = 0
        for record in picked:
            if record['id'] in attempted:
                continue
            if added >= budget or len(attempted) >= policy['max_candidates']:
                break
            attempted.add(record['id'])
            added += 1
            evidence = round_dir / (digest(record['id']) + '.json')
            try:
                doc = json.loads(evidence.read_text()) if evidence.exists() else read_skill(record, cache, policy)
                if not evidence.exists():
                    save(evidence, doc)
                if doc['sha256'] not in seen_hashes:
                    documents.append(doc)
                    seen_hashes.add(doc['sha256'])
            except (ValueError, urllib.error.URLError, TimeoutError) as exc:
                save(round_dir / (digest(record['id']) + '-error.json'), {'id': record['id'], 'error': str(exc)})
        payload = {'case': case, 'plan': plan, 'policy': policy, 'candidates': documents,
                   'round': round_no, 'tried_queries': sorted(tried_queries), 'previous_feedback': previous_feedback}
        review = ask('review-' + str(round_no), payload, REVIEW, folder, config)
        errors = review_errors(plan, review, documents, policy, case.get('constraints', {}).get('synthesis_allowed', False))
        save(round_dir / 'coverage.json', dict(review=review, errors=errors, candidate_count=len(documents), examined=len(attempted)))
        if review['decision'] == 'ready' and not errors:
            result = copy.deepcopy(case)
            selected = {s['source_id'] for s in review['selected']}
            result['source_materials'] += [dict(source_id=d['source_id'], provenance=d['url'],
                url=d['url'], sha256=d['sha256'], content=d['content']) for d in documents if d['source_id'] in selected]
            result.setdefault('constraints', {})['skill_workflow'] = dict(objective=plan['objective'],
                capabilities=plan['capabilities'], selected=review['selected'], steps=review['steps'], resources=review['resources'])
            result['constraints']['scope'] = result['constraints'].get('scope', '') + '\nPreserve the approved skill workflow, capability coverage and substantive dependent operations. Supply required premises; do not precompute solver outputs.'
            result.setdefault('source_metadata', {})['skill_discovery'] = dict(method='skills CLI + full-body LLM review',
                selected_ids=sorted(selected), rounds=round_no + 1, candidates=len(documents),
                audit=str(folder.resolve()), execution_verified=False)
            save(folder / 'enriched.json', result)
            return result
        if review['decision'] == 'reject' or not review['next_queries']:
            break
        previous_feedback = errors + review['missing_capabilities']
        queries = review['next_queries']
    save(folder / 'rejected.json', {'reason': 'No sufficient executable skill workflow within search budget',
                                  'last_review': review, 'structural_errors': errors})
    raise DiscoveryRejected('Skill discovery rejected; inspect ' + str(folder / 'rejected.json'))
