"""Read-only audit of saved responses and exported candidates for a batch."""
import argparse
import json
from collections import Counter
from pathlib import Path
from workfactory.models.client import read_json, save


def report(root):
    models={}
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or not (folder/'seeds.json').exists():continue
        model=folder.name
        tasks={}
        for p in sorted(folder.glob('*/seed.json')):
            dest=p.parent;state=read_json(dest/'status.json')
            attempts=[]
            for a in sorted(dest.glob('attempt-*')):
                detail=read_json(a/'status.json') if (a/'status.json').exists() else {}
                attempts.append({'path':str(a),'status':detail})
            tasks[dest.name]={'status':state,'attempts':attempts}
        usage=Counter();returned=Counter();seen=set()
        for p in sorted(folder.rglob('*response.json')):
            r=read_json(p);rid=r.get('id') or str(p)
            if rid in seen:continue
            seen.add(rid);u=r.get('usage',{})
            usage.update(calls=1,prompt_tokens=u.get('prompt_tokens',0),
                         completion_tokens=u.get('completion_tokens',0),
                         cached_tokens=u.get('prompt_tokens_details',{}).get('cached_tokens',u.get('prompt_cache_hit_tokens',0)))
            returned[r.get('model','unknown')]+=1
        models[model]={'status':read_json(folder/'status.json'),'tasks':tasks,
                       'saved_api_usage':dict(usage),'returned_models':dict(returned),
                       'completed_candidates':sum(t['status'].get('state')=='candidate_complete' for t in tasks.values())}
        exported=[]
        for task,data in tasks.items():
            state=data['status']
            if state.get('state')!='candidate_complete':continue
            trace=Path(state['trajectory'])
            attempt=read_json(trace.parent/'status.json')
            exported.append({'task_id':task,'model':model,'trajectory':str(trace),
                'environment':attempt['clean_environment'],
                'deliverables':[str(Path(attempt['teacher_directory'])/name.removeprefix('/task/')) for name in attempt['deliverables']],
                'manual_acceptance':state.get('manual_acceptance','pending'),
                'training_ready':False})
        save(folder/'candidate_index.json',exported)
    result={'models':models,'counting':'saved unique API response IDs, includes rejected attempts; excludes calls without saved responses',
            'acceptance':'candidate completion is separate from manual artifact review and tokenized SFT readiness'}
    save(root/'batch_summary.json',result)
    lines=['WorkFactory 批量运行记录','']
    for model,data in models.items():
        target=data['status'].get('target',len(data['tasks']))
        lines.extend([model,f"已导出 {data['completed_candidates']} / {target} 条候选轨迹",f"状态 {data['status'].get('state')}"])
        for task,data2 in data['tasks'].items():
            last=data2['attempts'][-1]['status'] if data2['attempts'] else {}
            lines.append(f"  {task}  {data2['status'].get('state')}  {last.get('stage','')}")
        lines.append('')
    lines.extend(['轨迹保存在对应任务的 attempt 目录下 trajectory.json',
                  '交付物保存在 teacher_workspace/outputs',
                  '完整原始请求、响应和工具结果保存在 09_teacher',
                  '候选轨迹仍需独立交付物核验，尚未生成训练 token 掩码'])
    (root/'STATUS.txt').write_text('\n'.join(lines)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root');a=p.parse_args()
    r=report(Path(a.root).resolve())
    print(json.dumps({k:{'state':v['status'].get('state'),'completed':v['completed_candidates'],'calls':v['saved_api_usage'].get('calls',0)} for k,v in r['models'].items()}))
