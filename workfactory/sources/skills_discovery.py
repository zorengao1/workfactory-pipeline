"""Skill recall and composition from the local embedding index. Skills are untrusted source data, never executed.

Mixed route: occupation query vectors nominate skills. Skill route: an anchor skill nominates related skills.
In both, the model reads full bodies, judges applicability and composes a dependent workflow.
A missing index fails; no other source is substituted.
"""
import copy
import fcntl
import hashlib
import json
from pathlib import Path

from workfactory.pipeline.contracts import ROOT, TEXT, array, obj, string, validate
from workfactory.clients.pilot import complete

DEFAULTS = dict(enabled=True, backend='local_index', index_dir='data/skill_index',
                per_query=5, initial_candidates=15, extra_candidates=10, max_research_rounds=1,
                min_similarity=0.4, max_skill_words=4000, neighbor_min_similarity=0.5,
                neighbor_max_similarity=0.85, min_selected=2, max_selected=4,
                skill_route_min_selected=1, min_operations=6, min_chain_depth=4)
CAP = obj(id=TEXT, operation=TEXT, input=TEXT, output=TEXT)
SELECTED = obj(source_id=TEXT, capability_ids=array(TEXT, 1), evidence_quote=TEXT,
               role=TEXT, inputs=array(TEXT, 1), outputs=array(TEXT, 1))
STEP = obj(id=TEXT, source_id=TEXT, operation=TEXT, input=TEXT, output=TEXT,
           depends_on=array(TEXT))
RESOURCE = obj(name=TEXT, provision=string('provided', 'synthesize', 'unavailable'), reason=TEXT)
JUDGE = obj(decision=string('ready', 'more', 'reject'), objective=TEXT, capabilities=array(CAP),
            selected=array(SELECTED), steps=array(STEP), resources=array(RESOURCE),
            missing_capabilities=array(TEXT), rejections=array(obj(source_id=TEXT, reason=TEXT)),
            explanation=TEXT)


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
    if policy['backend'] != 'local_index':
        raise ValueError('Skill discovery only supports the local_index backend, got ' + str(policy['backend']))
    for key in ('per_query', 'initial_candidates', 'extra_candidates', 'min_selected', 'max_selected',
                'skill_route_min_selected', 'min_operations', 'min_chain_depth'):
        if type(policy[key]) is not int or policy[key] < 1:
            raise ValueError('Invalid skill discovery setting ' + key)
    if type(policy['max_research_rounds']) is not int or policy['max_research_rounds'] < 0:
        raise ValueError('Expected nonnegative retry rounds')
    for key in ('min_similarity', 'neighbor_min_similarity', 'neighbor_max_similarity'):
        if not isinstance(policy[key], (int, float)) or isinstance(policy[key], bool) or not 0 <= policy[key] <= 1:
            raise ValueError('Invalid skill discovery setting ' + key)
    if type(policy['max_skill_words']) is not int or policy['max_skill_words'] < 50:
        raise ValueError('Invalid skill discovery setting max_skill_words')
    if policy['min_selected'] > policy['max_selected'] or policy['skill_route_min_selected'] > policy['max_selected']:
        raise ValueError('Invalid selected skill range')
    return policy


class DiscoveryRejected(ValueError):
    pass


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
    from workfactory.sources.skill_index import load_index
    location = Path(policy['index_dir'])
    index = load_index(location if location.is_absolute() else ROOT / location)
    checkpoint = dict(case=case, policy=policy, model=config['OPENAI_MODEL'], index=index.identity)
    with (folder / 'run.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        start = folder / 'input.json'
        if start.exists() and json.loads(start.read_text()) != checkpoint:
            raise ValueError('Skill discovery configuration changed; use a new run directory')
        save(start, checkpoint)
        if (folder / 'enriched.json').exists():
            return json.loads((folder / 'enriched.json').read_text())
        return _enrich(case, folder, config, policy, index)


def accept(case, folder, plan, review, documents, method, rounds, extra=None):
    result = copy.deepcopy(case)
    selected = {s['source_id'] for s in review['selected']}
    present = {m['source_id'] for m in result['source_materials']}
    result['source_materials'] += [dict(source_id=d['source_id'], provenance=d.get('provenance') or d['url'],
        url=d['url'], sha256=d['sha256'], content=d['content']) for d in documents if d['source_id'] in selected and d['source_id'] not in present]
    result.setdefault('constraints', {})['skill_workflow'] = dict(objective=plan['objective'],
        capabilities=plan['capabilities'], selected=review['selected'], steps=review['steps'], resources=review['resources'])
    result['constraints']['scope'] = result['constraints'].get('scope', '') + '\nPreserve the approved skill workflow, capability coverage and substantive dependent operations. Supply required premises; do not precompute solver outputs.'
    result.setdefault('source_metadata', {})['skill_discovery'] = dict(method=method,
        selected_ids=sorted(selected), rounds=rounds, candidates=len(documents),
        audit=str(folder.resolve()), execution_verified=False, **(extra or {}))
    save(folder / 'enriched.json', result)
    return result


def _enrich(case, folder, config, policy, index):
    """Embedding recall nominates; the model judges full bodies and composes the workflow."""
    meta = case.get('source_metadata', {})
    route = meta.get('route')
    if route == 'mixed':
        code = meta.get('onet_code')
        if not code:
            raise ValueError('Mixed route recall needs source_metadata.onet_code')
        kind, anchor, documents = 'judge', None, []
        recall = lambda limit, seen: index.candidates(code, limit, policy['per_query'], policy['min_similarity'],
                                                     50, policy['max_skill_words'], exclude=seen)
        method = 'local embedding index by occupation + full-body LLM judge'
    elif route == 'skill':
        anchor = meta.get('anchor_skill_id')
        documents = [m for m in case['source_materials'] if m['source_id'] == 'skill-' + str(anchor)]
        if not anchor or len(documents) != 1:
            raise ValueError('Skill route recall needs the anchor skill among source materials')
        documents = [dict(documents[0], id=anchor)]
        kind = 'compose'
        policy = {**policy, 'min_selected': policy['skill_route_min_selected']}
        recall = lambda limit, seen: index.neighbors(anchor, limit, policy['neighbor_min_similarity'],
                                                    policy['neighbor_max_similarity'], 50, policy['max_skill_words'], exclude=seen)
        method = 'local embedding index by anchor skill + full-body LLM composition'
    else:
        raise ValueError('Skill discovery applies to mixed and skill routes, got ' + str(route))
    synthesis = case.get('constraints', {}).get('synthesis_allowed', False)
    previous_feedback = []
    review = None
    errors = ['No candidate skills above the similarity floor']
    last = policy['max_research_rounds']
    for round_no in range(last + 1):
        round_dir = folder / f'round-{round_no:02d}'
        round_dir.mkdir(exist_ok=True)
        stored = round_dir / 'candidates.json'
        if stored.exists():
            fresh = json.loads(stored.read_text())
        else:
            fresh = recall(policy['initial_candidates'] if round_no == 0 else policy['extra_candidates'],
                           [d['id'] for d in documents])
            save(stored, fresh)
        if not fresh and round_no:
            break
        documents = documents + fresh
        if not documents:
            break
        payload = {'case': case, 'policy': policy, 'candidates': documents, 'round': round_no,
                   'final_round': round_no == last, 'previous_feedback': previous_feedback}
        if anchor:
            payload['anchor_source_id'] = 'skill-' + anchor
        review = ask(kind + '-' + str(round_no), payload, JUDGE, folder, config)
        plan = dict(objective=review['objective'], capabilities=review['capabilities'])
        errors = review_errors(plan, review, documents, policy, synthesis)
        if len(plan['capabilities']) < 3 or len({c['id'] for c in plan['capabilities']}) != len(plan['capabilities']):
            errors.append('At least three distinct capabilities required')
        if anchor and 'skill-' + anchor not in {s['source_id'] for s in review['selected']}:
            errors.append('Anchor skill must be part of the workflow')
        save(round_dir / 'coverage.json', dict(review=review, errors=errors, candidate_count=len(documents)))
        if review['decision'] == 'ready' and not errors:
            return accept(case, folder, plan, review, documents, method, round_no + 1, dict(index=index.identity))
        if review['decision'] == 'reject':
            break
        previous_feedback = errors + review['missing_capabilities']
    save(folder / 'rejected.json', {'reason': 'No sufficient executable skill workflow among indexed candidates',
                                  'last_review': review, 'structural_errors': errors})
    raise DiscoveryRejected('Skill discovery rejected; inspect ' + str(folder / 'rejected.json'))
