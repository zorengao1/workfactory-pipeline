"""Explicitly recover one failed task while other tasks finish in the same batch."""
import argparse
import fcntl
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from workfactory.pipeline.batch import run_case
from workfactory.core.config import load_policy,source_cases
from workfactory.models.client import load_config,read_json
from workfactory.runtime.preflight import check_runtime

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--pipeline-config',required=True);p.add_argument('--output',required=True);p.add_argument('--model',required=True);p.add_argument('--task',required=True);a=p.parse_args()
    policy=load_policy(a.pipeline_config);check_runtime(policy);config=load_config(a.config)
    config.update(OPENAI_MODEL=a.model,_POLICY=policy,API_MAX_CONCURRENCY=str(policy['api_max_concurrency']),API_LIMIT_SCOPE=policy.get('api_limit_scope','model'))
    config.setdefault('MAX_OUTPUT_TOKENS','65536');config.setdefault('TRANSPORT_ATTEMPTS','3')
    model=Path(a.output).resolve()/a.model;task=model/a.task
    with (task/'recovery.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if read_json(task/'status.json')['state'] not in ('error','needs_review'):
            raise RuntimeError('Only a stopped failed task may be explicitly recovered')
        cases=[x for x in source_cases(policy) if x['task_id']==a.task]
        if len(cases)!=1:raise ValueError('Unknown task')
        run_case(cases[0],model,config)
