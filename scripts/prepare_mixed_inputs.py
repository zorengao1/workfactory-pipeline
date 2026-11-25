"""Prepare occupation-anchored cases through online skills CLI and model review."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contracts import ROOT
from pilot import load_config
from pipeline_config import load_policy, stage_config
from skills_discovery import enrich_skills, DiscoveryRejected, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--occupations', nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', required=True, help='Model credential .env, never committed')
    parser.add_argument('--pipeline-config', default=str(ROOT/'config/pipeline.json'))
    parser.add_argument('--audit', type=Path, required=True)
    args = parser.parse_args()
    config = load_config(args.config)
    config['_POLICY'] = load_policy(args.pipeline_config)
    cases = json.loads((ROOT/'data/source_pools/cases.json').read_text())
    results = []
    rejected = []
    for code in args.occupations:
        matches = [c for c in cases if c['task_id'] == 'onet-' + code.replace('.', '-')]
        if len(matches) != 1:
            raise ValueError('Unknown or duplicate occupation ' + code)
        case = matches[0]
        case['task_id'] = 'mixed-' + code.replace('.', '-')
        try:
            results.append(enrich_skills(case, args.audit/case['task_id'], stage_config(config, case['stage'])))
        except DiscoveryRejected as exc:
            rejected.append({'task_id': case['task_id'], 'reason': str(exc)})
    save(args.output, results)
    save(args.output.with_suffix('.rejected.json'), rejected)
    print('Accepted source candidates', len(results), 'rejected', len(rejected))
    if not results:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
