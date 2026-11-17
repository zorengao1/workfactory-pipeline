"""Audit unique saved responses, wall time, artifacts and optional posted rates."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import html
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pilot import save


def timestamp(value):return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()


def audit(root,pricing=None):
    root=Path(root).resolve();pricing=pricing or {};tasks=[]
    for seed in sorted(root.glob('*/*/seed.json')):
        folder=seed.parent;state=json.loads((folder/'status.json').read_text());seen=set();usage=Counter();phases={};starts=[];ends=[]
        for path in sorted(folder.rglob('*response.json')):
            r=json.loads(path.read_text());rid=r.get('id')
            if not rid or rid in seen or 'usage' not in r:continue
            seen.add(rid);u=r['usage'];phase='teacher' if '/09_teacher' in str(path) else 'source_research' if '/source_retrieval/' in str(path) else 'construction_and_probe'
            count=phases.setdefault(phase,Counter())
            cached=u.get('prompt_tokens_details',{}).get('cached_tokens',u.get('prompt_cache_hit_tokens',0)) or 0
            current=Counter(calls=1,input_tokens=u.get('prompt_tokens',0),cached_input_tokens=cached,output_tokens=u.get('completion_tokens',0))
            for item in r.get('responses_raw',{}).get('output',[]):
                if item.get('type')=='web_search_call':
                    current['web_tool_calls']+=1;current['web_action_'+item.get('action',{}).get('type','unknown')]+=1
            current['api_reported_web_requests']+=r.get('responses_raw',{}).get('tool_usage',{}).get('web_search',{}).get('num_requests',0)
            current['cache_write_tokens']+=u.get('prompt_tokens_details',{}).get('cache_write_tokens',0)
            current['reasoning_output_tokens']+=u.get('completion_tokens_details',{}).get('reasoning_tokens',0)
            count.update(current);usage.update(current)
            m=r.get('request_metrics',{})
            if m.get('started_at'):starts.append(timestamp(m['started_at']));ends.append(timestamp(m['finished_at']))
        start=min(starts) if starts else seed.stat().st_mtime
        terminal=state.get('state') in ('candidate_complete','error','needs_review')
        end=timestamp(state['updated_at']) if terminal else datetime.now(timezone.utc).timestamp()
        cost=None
        required=('input_per_million','cached_input_per_million','output_per_million')
        if all(pricing.get(k) is not None for k in required):
            cost=((usage['input_tokens']-usage['cached_input_tokens'])*pricing['input_per_million']+usage['cached_input_tokens']*pricing['cached_input_per_million']+usage['output_tokens']*pricing['output_per_million'])/1e6
        task={'task_id':folder.name,'state':state.get('state'),'started_at':datetime.fromtimestamp(start,timezone.utc).isoformat(),'finished_at':state.get('updated_at') if terminal else None,'wall_seconds':round(max(0,end-start),1),'usage':dict(usage),'phases':{k:dict(v) for k,v in phases.items()},'model_cost_usd_estimate':cost,'web_search_cost_usd':None,'trajectory':state.get('trajectory')}
        if state.get('trajectory'):
            trace=Path(state['trajectory']);d=json.loads(trace.read_text());task['messages']=len(d['messages']);task['failed_tool_calls']=len(d.get('failed_tool_calls',[]));task['manual_acceptance']=state.get('manual_acceptance');task['training_ready']=state.get('training_ready')
            lines=['<!doctype html><meta charset="utf-8"><title>教师轨迹</title><style>body{font:15px system-ui;max-width:1000px;margin:40px auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f4f4;padding:14px}details{margin:12px 0}summary{cursor:pointer}</style>', '<h1>'+html.escape(folder.name)+'</h1>']
            for i,m in enumerate(d['messages']):
                lines.append('<details><summary>'+str(i)+' '+html.escape(m['role'])+'</summary><pre>'+html.escape(json.dumps({k:v for k,v in m.items() if k!='_responses_output'},ensure_ascii=False,indent=2))+'</pre></details>')
            (trace.parent/'trajectory.html').write_text('\n'.join(lines))
        tasks.append(task)
    totals=Counter()
    for t in tasks:totals.update(t['usage'])
    report={'generated_at':datetime.now(timezone.utc).isoformat(),'tasks':tasks,'total_usage':dict(totals),'pricing':pricing,'cost_status':'estimated model token costs only' if pricing else 'awaiting actual endpoint prices; usage recorded, no invented charges','exclusions':['requests without saved usage','billing reconciliation','web search charges until rate and billing unit confirmed','local compute'],'batch_wall_seconds':round(max(timestamp(t['finished_at']) if t['finished_at'] else datetime.now(timezone.utc).timestamp() for t in tasks)-min(timestamp(t['started_at']) for t in tasks),1) if tasks else 0}
    save(root/'time_cost_report.json',report);return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root');p.add_argument('--pricing',type=Path);a=p.parse_args()
    r=audit(a.root,json.loads(a.pricing.read_text()) if a.pricing else None)
    print(json.dumps(r,ensure_ascii=False,indent=2))
