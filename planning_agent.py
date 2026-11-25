"""Free agentic stage 03 with version-bound review and fail-closed submission."""
import copy
import json
import time
from pathlib import Path
from pilot import complete
from contracts import PLAN, output_errors, ROOT


def save(p, x):
    p.write_text(json.dumps(x, ensure_ascii=False, indent=2) + '\n')


REVIEW_PROMPT = """独立审核03规划，不要求04实际文件存在。检查意图、必要前提、来源、答案泄漏、格式、依赖、公式单位、时间范围、薪资口径和跨载体一致性。允许业务合理的重复、重叠、旧版本。会改变计算结果、影响核对或迫使求解者猜测的歧义均是必须修复的问题，不能降为advisory。纯措辞或美观建议放suggestions，不阻断提交。修复必须落实到对应nodes及construction_spec，并保持user_request与文件规划一致，不能只加笼统优先条款掩盖错误。
只返回JSON，字段 verdict(pass或fail)、issues、closures、suggestions。issues每项包含id、description、evidence三个非空字符串，包含所有仍未解决和新发现的实质问题，沿用旧问题id。closures对previous_issues逐项返回id、status(resolved或open)、evidence，证据引用当前计划中的节点及具体修订内容。旧问题不能静默省略；只有issues为空且全部旧问题有确切修复证据才返回pass。"""


def review_errors(report, previous):
    errors = []
    if not isinstance(report, dict):
        return ['Review must be an object']
    if report.get('verdict') not in ('pass', 'fail'):
        errors.append('Invalid verdict')
    issues = report.get('issues')
    closures = report.get('closures')
    if not isinstance(issues, list) or not isinstance(closures, list) or not isinstance(report.get('suggestions'), list):
        return errors + ['Missing issues, closures or suggestions array']
    ids = []
    for item in issues:
        if not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k].strip() for k in ('id','description','evidence')):
            errors.append('Issue requires id, description and evidence')
        else:
            ids.append(item['id'])
    if len(ids) != len(set(ids)):
        errors.append('Duplicate issue IDs')
    closed = {}
    for item in closures:
        if not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k].strip() for k in ('id','status','evidence')) or item.get('status') not in ('resolved','open'):
            errors.append('Invalid closure evidence')
            continue
        if item['id'] in closed:
            errors.append('Duplicate closure ID')
        closed[item['id']] = item
    for item in previous:
        closure = closed.get(item['id'])
        if closure is None:
            errors.append('Previous issue omitted ' + item['id'])
        elif closure['status'] == 'open' and item['id'] not in ids:
            errors.append('Open issue missing from issues ' + item['id'])
    if report.get('verdict') == 'pass' and (issues or any(x['status'] != 'resolved' for x in closed.values())):
        errors.append('Pass with unresolved issues')
    return errors


def run_plan(inputs, destination, config, max_tokens):
    root = Path(destination) / '03_plan'
    root.mkdir(parents=True, exist_ok=False)
    cfg = {**config, 'NATIVE_WEB_SEARCH': '0'}
    base = copy.deepcopy(inputs)
    max_turns = int(cfg.get('_POLICY', {}).get('plan_max_turns', 20))
    if max_turns < 1:
        raise ValueError('plan_max_turns must be positive')
    save(root/'input.json', base)
    policy = (ROOT/'prompts/03_plan.txt').read_text()
    policy += '''\n由你自主决定规划顺序，无03A到03E的强制子阶段。你可直接设计整个计划、局部更新、检查、请求独立审核。业务合理的重复信息、不同版本、重叠文件和有背景的冗余允许保留，不为去重删除有用的核对材料；冲突必须有可判断的来源、日期、生效规则或合理的未决处理。职业资料通常留在构造侧。只规划，不生成04真实文件。使用工具保存计划和提交。save_plan接受完整六块计划；update_plan按顶层字段整体替换，只传需要改的字段。check_plan检查结构。review_plan独立评审当前版本。submit_plan只接受当前版本结构通过且独立审核通过的计划。版本修改后原审核失效。不要输出长段计划到普通文本，使用工具。达到控制器轮数上限仍不通过则保留失败。'''
    policy += '\n任何影响数值、可核对性或需要猜测的歧义必须修复才能提交。纯风格建议可保留。对审核问题修订相关节点和构建规格，保持所有表述一致。修订后必须再次独立审核，确认旧问题关闭且没有新的实质问题。达到轮数上限仍未通过则以needs_repair停止，不能作为成功提交。'
    save(root/'prompt.json', {'system':policy})
    def tool(name, desc, props, required):
        return {'type':'function','function':{'name':name,'description':desc,'parameters':{'type':'object','properties':props,'required':required,'additionalProperties':False}}}
    tools = [tool('save_plan','Save the complete planning artifact',{'plan':PLAN},['plan']),
             tool('update_plan','Replace selected top-level plan fields',{'changes':{'type':'object','properties':PLAN['properties'],'additionalProperties':False}},['changes'])]
    tools += [tool(n,d,{},[]) for n,d in [('check_plan','Check current plan schema and references'),('review_plan','Request independent semantic review of current plan'),('submit_plan','Submit current approved plan')]]
    messages=[{'role':'system','content':policy},{'role':'user','content':json.dumps(base,ensure_ascii=False)}]
    plan=None; version=0; reviewed=None; total_calls=0; started=time.monotonic(); usages=[]; accepted=False
    pending=[]; review_count=0
    def api(msgs, functions=None, label='planner'):
        nonlocal total_calls
        total_calls+=1; idx=total_calls
        save(root/f'call_{idx:02d}_request.json',{'role':label,'model':cfg['OPENAI_MODEL'],'messages':msgs,'tools':functions})
        t=time.monotonic(); r=complete(cfg,msgs,max_tokens,functions)
        save(root/f'call_{idx:02d}_response.json',r); usages.append(r.get('usage',{}))
        print(json.dumps({'call':idx,'role':label,'elapsed':round(time.monotonic()-t,2)}),flush=True)
        return r['choices'][0]['message']
    def check():
        if plan is None: return ['No saved plan']
        return output_errors('03_plan',{'task_id':base['task_id'],'status':'ok','result':plan,'issues':[]},base)
    try:
        for turn in range(max_turns):
            msg=api(messages,tools); messages.append(msg)
            calls=msg.get('tool_calls',[])
            if not calls:
                messages.append({'role':'user','content':'请调用工具继续规划或提交。只有submit_plan通过才完成。'})
            for tc in calls:
                name=tc['function']['name']
                try:
                    args=json.loads(tc['function']['arguments'])
                    if not isinstance(args, dict):
                        raise ValueError('Tool arguments must be an object')
                    if name in ('save_plan','update_plan'):
                        if name=='save_plan':
                            if not isinstance(args.get('plan'), dict): raise ValueError('plan must be an object')
                            plan=copy.deepcopy(args['plan'])
                        else:
                            if plan is None: raise ValueError('Save a plan first')
                            if not isinstance(args.get('changes'), dict): raise ValueError('changes must be an object')
                            plan.update(copy.deepcopy(args['changes']))
                        version+=1; reviewed=None
                        save(root/f'plan_v{version:02d}.json',plan)
                        result={'version':version,'saved':True}
                    elif name=='check_plan': result={'version':version,'errors':check()}
                    elif name=='review_plan':
                        errors=check()
                        if errors: result={'version':version,'errors':errors,'reviewed':False}
                        else:
                            reviewed=None
                            review_count+=1
                            audit=api([{'role':'system','content':REVIEW_PROMPT}, {'role':'user','content':json.dumps({'inputs':base,'plan':plan,'previous_issues':pending},ensure_ascii=False)}],label='independent_review')
                            result=json.loads(audit['content'])
                            errors=review_errors(result,pending)
                            save(root/f'review_{review_count:02d}_v{version:02d}.json',{'report':result,'validation_errors':errors})
                            reviewed=None
                            if not errors:
                                pending=result['issues']
                                if result['verdict']=='pass' and not pending:
                                    reviewed=version
                            result={'report':result,'validation_errors':errors,'submission_allowed':reviewed==version,'pending_issues':pending}
                    elif name=='submit_plan':
                        errors=check(); accepted=not errors and reviewed==version and not pending
                        result={'accepted':accepted,'errors':errors,'current_version_review_pass':reviewed==version}
                        if accepted: save(root/'final_plan.json',plan)
                    else: result={'error':'Unknown tool'}
                except (ValueError,KeyError,TypeError) as exc:
                    result={'error':str(exc)}
                messages.append({'role':'tool','tool_call_id':tc['id'],'content':json.dumps(result,ensure_ascii=False)})
                with (root/'events.jsonl').open('a') as f: f.write(json.dumps({'turn':turn+1,'tool':name,'version':version,'result':result},ensure_ascii=False)+'\n')
                print(json.dumps({'turn':turn+1,'tool':name,'version':version,'accepted':accepted}),flush=True)
                if accepted: break
            save(root/'messages.json',messages)
            if accepted: break
    except Exception as exc:
        save(root/'transport_error.json', {'error_type':type(exc).__name__, 'message':str(exc).replace(cfg.get('OPENAI_API_KEY','__NO_KEY__'),'[REDACTED]')})
        raise
    finally:
        usage = {
            'prompt_tokens':sum(u.get('prompt_tokens',0) for u in usages),
            'completion_tokens':sum(u.get('completion_tokens',0) for u in usages),
            'prompt_tokens_details':{'cached_tokens':sum(u.get('prompt_tokens_details',{}).get('cached_tokens',0) for u in usages)},
        }
        validation = {'stage':'03_plan', 'mode':'pure_agentic',
            'format_and_contract_pass':bool(accepted), 'status':'ok' if accepted else 'blocked',
            'errors':[] if accepted else ['Plan not accepted; inspect events and review evidence'],
            'elapsed_seconds':round(time.monotonic()-started,3), 'usage':usage,
            'model':cfg['OPENAI_MODEL'], 'calls':total_calls, 'versions':version,
            'pending_issues':pending}
        save(root/'validation.json',validation)
        if accepted:
            save(root/'parsed.json', {'task_id':base['task_id'],'status':'ok','result':plan,'issues':[]})
    return validation, plan if accepted else None
