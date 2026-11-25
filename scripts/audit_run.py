"""Audit unique saved responses, wall time, artifacts and optional posted rates."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import html
import csv
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from workfactory.clients.pilot import save


def timestamp(value):return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()


def price_usage(usage,pricing):
    details=usage.get('prompt_tokens_details',{})
    input_tokens=usage.get('prompt_tokens',0);read=details.get('cached_tokens',0);write=details.get('cache_write_tokens',0)
    plain=input_tokens-read-write
    if plain<0:raise ValueError('Cache token buckets exceed reported input')
    tier='standard' if input_tokens<=pricing['standard_max_length'] else 'long_context'
    rates=pricing[tier]
    buckets={'input':plain,'cache_read':read,'cache_write':write,'output':usage.get('completion_tokens',0)}
    components={k:buckets[k]*rates[k]/1000000 for k in buckets}
    return tier,buckets,components,sum(components.values())


def audit(root,pricing=None):
    root=Path(root).resolve();pricing=pricing or {};tasks=[];call_rows=[]
    for seed in sorted(root.glob('*/*/seed.json')):
        folder=seed.parent;state=json.loads((folder/'status.json').read_text());seen=set();usage=Counter();phases={};starts=[];ends=[];latencies=Counter();phase_costs=Counter();tiers=Counter();cost=0.0 if pricing else None
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
            if pricing:
                tier,buckets,components,call_cost=price_usage(u,pricing)
                cost+=call_cost;phase_costs[phase]+=call_cost;tiers[tier]+=1
                call_rows.append({'task':folder.name,'phase':phase,'response_id':rid,'response_file':str(path),'tier':tier,**{k+'_tokens':v for k,v in buckets.items()},**{k+'_usd':v for k,v in components.items()},'total_usd':call_cost,'api_reported_web_requests':current['api_reported_web_requests']})
            m=r.get('request_metrics',{})
            latencies[phase]+=m.get('elapsed_seconds',0)
            if m.get('started_at'):starts.append(timestamp(m['started_at']));ends.append(timestamp(m['finished_at']))
        start=min(starts) if starts else seed.stat().st_mtime
        terminal=state.get('state') in ('candidate_complete','error','needs_review')
        end=timestamp(state['updated_at']) if terminal else datetime.now(timezone.utc).timestamp()
        task={'task_id':folder.name,'state':state.get('state'),'started_at':datetime.fromtimestamp(start,timezone.utc).isoformat(),'finished_at':state.get('updated_at') if terminal else None,'wall_seconds':round(max(0,end-start),1),'usage':dict(usage),'phases':{k:dict(v) for k,v in phases.items()},'saved_api_elapsed_seconds_by_phase':{k:round(v,2) for k,v in latencies.items()},'model_cost_usd_estimate':cost,'phase_costs_usd_estimate':dict(phase_costs),'pricing_tiers':dict(tiers),'web_search_cost_usd':pricing.get('web_search_extra_charge') if pricing else None,'trajectory':state.get('trajectory')}
        if state.get('trajectory'):
            trace=Path(state['trajectory']);d=json.loads(trace.read_text());task['messages']=len(d['messages']);task['failed_tool_calls']=len(d.get('failed_tool_calls',[]));task['manual_acceptance']=state.get('manual_acceptance');task['training_ready']=state.get('training_ready')
            lines=['<!doctype html><meta charset="utf-8"><title>教师轨迹</title><style>body{font:15px system-ui;max-width:1000px;margin:40px auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f4f4;padding:14px}details{margin:12px 0}summary{cursor:pointer}</style>', '<h1>'+html.escape(folder.name)+'</h1>']
            for i,m in enumerate(d['messages']):
                lines.append('<details><summary>'+str(i)+' '+html.escape(m['role'])+'</summary><pre>'+html.escape(json.dumps({k:v for k,v in m.items() if k!='_responses_output'},ensure_ascii=False,indent=2))+'</pre></details>')
            (trace.parent/'trajectory.html').write_text('\n'.join(lines))
        tasks.append(task)
    totals=Counter()
    for t in tasks:totals.update(t['usage'])
    report={'generated_at':datetime.now(timezone.utc).isoformat(),'tasks':tasks,'total_usage':dict(totals),'pricing':pricing,'cost_status':'estimated model token costs only' if pricing else 'awaiting actual endpoint prices; usage recorded, no invented charges','timing_note':'Wall time includes source preparation, failed attempts, debugging interruptions and recovery. Summed API latencies are not wall time under concurrency.','exclusions':['requests without saved usage','billing reconciliation','local compute'],'batch_wall_seconds':round(max(timestamp(t['finished_at']) if t['finished_at'] else datetime.now(timezone.utc).timestamp() for t in tasks)-min(timestamp(t['started_at']) for t in tasks),1) if tasks else 0}
    report['total_model_cost_usd_estimate']=sum(t['model_cost_usd_estimate'] for t in tasks) if pricing else None
    report['web_search_extra_charge_usd']=pricing.get('web_search_extra_charge') if pricing else None
    save(root/'time_cost_report.json',report)
    if call_rows:
        with (root/'cost_calls.csv').open('w',newline='') as output:
            writer=csv.DictWriter(output,fieldnames=list(call_rows[0]));writer.writeheader();writer.writerows(call_rows)
    lines=['本批次耗时与用量','',f"批次墙钟时间 {report['batch_wall_seconds']/60:.1f} 分钟",'包含来源准备、失败尝试、联调中断和恢复时间','']
    for task in tasks:
        u=task['usage'];lines.extend([task['task_id'],f"状态 {task['state']}",f"墙钟时间 {task['wall_seconds']/60:.1f} 分钟",f"已保存响应 {u.get('calls',0)} 次",f"输入 token {u.get('input_tokens',0)}，其中缓存命中 {u.get('cached_input_tokens',0)}",f"输出 token {u.get('output_tokens',0)}",f"接口报告联网请求 {u.get('api_reported_web_requests',0)} 次",'模型费用 '+(str(task['model_cost_usd_estimate'])+' USD 估算' if task['model_cost_usd_estimate'] is not None else '待确认接口单价'),'联网额外费用 '+('0 USD，用户确认搜索不单独收费' if task['web_search_cost_usd']==0 else '待确认单价和计费单位'),''])
    if pricing:lines.extend(['模型费用合计 '+str(round(report['total_model_cost_usd_estimate'],6))+' USD 估算',''])
    lines.extend(['不等同于平台扣费账单','未保存 usage 的中断请求无法定价，另不含本地计算费用'])
    (root/'TIME_COST.txt').write_text('\n'.join(lines)+'\n')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root');p.add_argument('--pricing',type=Path);a=p.parse_args()
    r=audit(a.root,json.loads(a.pricing.read_text()) if a.pricing else None)
    print(json.dumps(r,ensure_ascii=False,indent=2))
