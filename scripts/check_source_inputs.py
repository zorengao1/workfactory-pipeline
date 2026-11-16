"""Run actual intent-generation/review checks on downloaded source-backed inputs."""
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from pipeline_config import load_policy,source_cases
from pilot import load_config,save
from batch_generate import text_stage


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();policy=load_policy(ROOT/'config/source-pool-validation.json');cases=source_cases(policy)
    occupations=[next(c for c in cases if c['stage']=='01a_occupation' and c['source_metadata']['soc_major']==group) for group in ['23-0000','25-0000']]
    skills=[c for c in cases if c['stage']=='01b_skill'][:2]
    config=load_config(a.config);config['_POLICY']=policy;config['API_MAX_CONCURRENCY']='2';config['API_LIMIT_SCOPE']='model'
    output=Path(a.output).resolve();output.mkdir(parents=True,exist_ok=True);results=[]
    for case in [*occupations,*skills]:
        folder=output/case['task_id'];folder.mkdir(exist_ok=True)
        base={k:case[k] for k in ['task_id','source_materials','constraints']}
        save(folder/'source_case.json',case)
        try:
            intent=text_stage(case['stage'],base,folder,config)
            review=text_stage('02_intent_review',{**base,'intent':intent},folder,config)
            results.append({'task_id':case['task_id'],'route':case['stage'],'intent':intent,'review':review})
        except Exception as exc:results.append({'task_id':case['task_id'],'error':str(exc).replace(config['OPENAI_API_KEY'],'[REDACTED]')})
        save(output/'summary.json',results);print(json.dumps(results[-1],ensure_ascii=False),flush=True)


if __name__=='__main__':main()
