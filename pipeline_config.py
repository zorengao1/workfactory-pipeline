"""Serializable pipeline policy, kept separate from secrets and task instances."""
import json
from pathlib import Path
from contracts import ROOT, STAGES


def load_policy(path=None):
    path = Path(path or ROOT/'config/pipeline.json').resolve()
    policy = json.loads(path.read_text())
    for field in ('task_workers', 'api_max_concurrency', 'max_agent_turns'):
        if not isinstance(policy[field], int) or policy[field] < 1:
            raise ValueError(field+' must be a positive integer')
    if not isinstance(policy.get('plan_max_turns',20), int) or isinstance(policy.get('plan_max_turns',20), bool) or policy.get('plan_max_turns',20) < 1:
        raise ValueError('plan_max_turns must be a positive integer')
    for stage in policy.get('stage_models', {}):
        if stage not in STAGES:
            raise ValueError('Unknown stage '+stage)
    policy['_config_path'] = str(path)
    return policy


def source_cases(policy):
    source = Path(policy['source_cases'])
    if not source.is_absolute():
        source = ROOT/source
    cases = json.loads(source.read_text())
    ids = set()
    for case in cases:
        if case['task_id'] in ids or '/' in case['task_id'] or '..' in case['task_id']:
            raise ValueError('Invalid or duplicate task ID')
        ids.add(case['task_id'])
        if case['stage'] not in ('01a_occupation','01b_skill','01c_deliverable'):
            raise ValueError('Unknown source route')
        if not case.get('source_materials'):
            raise ValueError('Source materials and provenance are required')
        constraints = {
            'allowed_reference_formats':policy['allowed_reference_formats'],
            'required_deliverable_formats':policy['required_deliverable_formats'],
            'external_retrieval':policy['external_retrieval'],
            'purpose':'按工作意图和信息支撑图决定参考文件数量与格式，不凑数量，不强制表格。'
                      'allowed_reference_formats 为空表示不限定后缀，须使用执行环境实际可处理的格式。'
                      '保留来源标注，明确合成内容。所有必要前提可见，派生结果留给求解者。'
                      '请求固定为根目录 REQUEST.txt，参考文件放 inputs，成果放 outputs。',
            **case.get('constraints', {})}
        if policy.get('reference_file_count') is not None:
            constraints['reference_file_count'] = policy['reference_file_count']
        case['constraints'] = constraints
    return cases


def stage_config(config, stage):
    from pilot import load_config
    credential_path = config.get("_POLICY", {}).get("stage_credentials", {}).get(stage)
    if credential_path:
        config = {**config, **load_config(credential_path)}
    model = config.get('_POLICY', {}).get('stage_models', {}).get(stage)
    return {**config, **({'OPENAI_MODEL':model} if model else {})}
