"""Matched synthetic seeds, independent model-specific construction and teachers.

Uses the existing WorkFactory reproduction contracts and capability broker.
Every attempt is retained; final candidates are raw traces, not tokenized SFT.
"""
import argparse
import copy
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from workfactory.pipeline.contracts import ROOT
from workfactory.sources.source_artifacts import stage_reuse, verify_reuse
from workfactory.pipeline.continue_environment import accepted, accepted_review, prefixed
from workfactory.pipeline.environment_pilot import environment, checks
from workfactory.clients.pilot import load_config, read_json, run_stage, save
from workfactory.runtime.tool_runtime import inventory, run_agent
from workfactory.pipeline.pipeline_config import load_policy, source_cases, stage_config
from workfactory.runtime.preflight import check_runtime


def cases(policy=None):
    return source_cases(policy or load_policy())


class StageRejected(Exception):
    pass


def update(folder, **fields):
    p=folder/'status.json'
    state=read_json(p) if p.exists() else {}
    state.update(fields, updated_at=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
    tmp=p.with_suffix('.tmp');save(tmp,state);tmp.replace(p)


def text_stage(stage, inputs, folder, config):
    config=stage_config(config,stage)
    full_intent = stage in ('01a_occupation','01b_skill','01c_deliverable','02_intent_review')
    if full_intent:
        from workfactory.sources.source_artifacts import full_text_inputs
        inputs = full_text_inputs(inputs)
    existing=folder/stage
    for cached in [existing,*sorted(folder.glob(f'{stage}-retry-*/{stage}'))]:
        if (cached/'validation.json').exists():
            valid=read_json(cached/'validation.json')
            if valid['format_and_contract_pass'] and valid['status']=='ok':
                if full_intent and (not (cached/'input.json').exists() or read_json(cached/'input.json') != inputs):
                    raise ValueError('Cached intent input differs or predates full-text access; use a new output directory')
                return read_json(cached/'parsed.json')['result']
    dest=folder
    if existing.exists():
        for n in range(1,100):
            dest=folder/f'{stage}-retry-{n:02d}'
            if not dest.exists():dest.mkdir();break
    validation,result=run_stage(stage,inputs,dest,config,int(config.get('MAX_OUTPUT_TOKENS',65536)))
    if result is None:raise StageRejected(stage+' rejected '+json.dumps(validation['errors'],ensure_ascii=False))
    return result


def agent(stage, inputs, root, folder, config, writable=()):
    config=stage_config(config,stage)
    parent=folder.parent;pointer=parent/(stage+'_active.json')
    active=Path(read_json(pointer)['path']) if pointer.exists() else folder
    if (active/'validation.json').exists() and read_json(active/'validation.json')['pass']:
        cached=read_json(active/'parsed.json')
        if accepted(cached):return cached
    resume=None
    if active.exists():
        requests=sorted(active.glob('[0-9][0-9]-request.json'))
        if not requests:raise RuntimeError('Stage has no recoverable request '+str(active))
        last=requests[-1]
        if last.with_name(last.name.replace('request','response')).exists():
            raise RuntimeError('Interrupted stage has a response requiring tool-state audit '+str(active))
        resume=read_json(last)['messages']
        for n in range(1,100):
            resumed=parent/f'{stage}-resume-{n:02d}'
            if not resumed.exists():active=resumed;break
    save(pointer,{'path':str(active),'resumed_from_messages':resume is not None})
    update(parent,stage=stage,stage_directory=str(active))
    result=run_agent(stage,inputs,root,active,config,writable,
        max_turns=config.get('_POLICY',{}).get('max_agent_turns',250),resume_messages=resume)
    if not accepted(result):raise StageRejected(stage+' rejected; inspect '+str(folder))
    return result


def solver_inputs(case, env):
    return {'task_id':case['task_id'],'environment':env,'workspace':{
        'root':'/task','read_only_inputs':['REQUEST.txt','inputs'],'output_directory':'outputs'}}


def materialize(case, plan, folder, config):
    """Retry construction under the SAME plan; retain every failed build."""
    retries=config.get('_POLICY',{}).get('initial_build_retries',3)
    for index in range(retries+1):
        step=folder/f'materialization-sources-{index:02d}' if case.get('source_metadata',{}).get('mixed_inputs') else folder/f'materialization-{index:02d}'
        step.mkdir(exist_ok=True)
        if (step/'rejected.json').exists():continue
        root=step/'environment';root.mkdir(exist_ok=True)
        sources=step/'construction_sources';sources.mkdir(exist_ok=True)
        manifest=[]
        for i,material in enumerate(case.get('source_materials',[])):
            name=f'source-{i:02d}.json';save(sources/name,material)
            entry={'source_id':material['source_id'],'metadata_and_text':'/sources/'+name}
            snapshot=material.get('snapshot')
            if snapshot and Path(snapshot).is_file():
                raw=Path(snapshot);suffix='.pdf' if raw.read_bytes().startswith(b'%PDF-') else raw.suffix or '.bin'
                target=sources/(f'source-{i:02d}'+suffix);shutil.copyfile(raw,target)
                entry['original_file']='/sources/'+target.name
            manifest.append(entry)
        build_config={**config,'_CONSTRUCTION_SOURCES':str(sources.resolve())}
        try:
            reused=stage_reuse(plan,case.get('source_materials',[]),root)
            save(step/'reuse_manifest.json',reused)
            agent('04_build',{'task_id':case['task_id'],'plan':plan,'constraints':case['constraints'],
                'workspace':{'root':'/task','writable_paths':['inputs','REQUEST.txt'],
                             'reference_directory':'/task/inputs','request_path':'/task/REQUEST.txt','construction_source_manifest':manifest,'construction_sources_policy':'Read-only /sources is only available to the builder. Read actual source JSON or original files before reuse/adapt. It is not copied to solver workspaces.'}},
                  root,step/'04_build',build_config,('inputs','REQUEST.txt'))
            if not verify_reuse(reused,root):
                raise StageRejected('Reused source file was modified during construction')
            program=checks(root,plan);save(step/'program_checks.json',program)
            if not program['exact_file_set'] or not program['nonempty'] or not program['format_match']:
                raise StageRejected('Construction file checks failed')
            review=agent('05_construction_review',{'task_id':case['task_id'],'plan':plan,
                'environment':environment(root,plan),'program_checks':program},root,step/'05_construction_review',config)
            if not accepted_review(review):raise StageRejected('Construction semantic review failed')
            return root
        except StageRejected as exc:
            save(step/'rejected.json',{'reason':str(exc),'plan_preserved':True})
    raise StageRejected('Initial materialization exhausted under unchanged intent and plan')


def attempt(case, folder, config):
    base={k:case[k] for k in ('task_id','source_materials','constraints')}
    for stage in (case['stage'],'02_intent_review','03_plan'):
        update(folder,stage=stage)
        if stage==case['stage']:intent=text_stage(stage,base,folder,config)
        elif stage=='02_intent_review':
            review=text_stage(stage,{**base,'intent':intent},folder,config)
            if review['verdict']!='pass':raise StageRejected('intent review failed')
        else:plan=text_stage(stage,{'task_id':case['task_id'],'intent':intent,'source_materials':case['source_materials'],'constraints':case['constraints']},folder,config)
    save(folder/'initial_plan.json',plan)
    root=materialize(case,plan,folder,config)
    initial_root=root
    original=environment(root,plan)
    repair_limit=config.get('_POLICY',{}).get('repair_rounds',3)
    for round_no in range(repair_limit+1):
        step=folder if round_no==0 else folder/f'repair-{round_no}'
        program=checks(root,plan);save(step/'program_checks.json',program)
        if not program['exact_file_set'] or not program['nonempty'] or not program['format_match']:raise StageRejected('file checks failed')
        env=environment(root,plan)
        if round_no:
            review=agent('05_construction_review',{'task_id':case['task_id'],'plan':plan,'environment':env,'program_checks':program},root,step/'05_construction_review',config)
            if not accepted_review(review):raise StageRejected('construction review failed')
        if round_no:
            comparison=step/'comparison';comparison.mkdir(exist_ok=True)
            if not (comparison/'original').exists():shutil.copytree(initial_root,comparison/'original')
            if not (comparison/'revised').exists():shutil.copytree(root,comparison/'revised')
            preserved=agent('08_preservation_review',{'task_id':case['task_id'],'original_intent':intent,'initial_plan':plan,
                'original_environment':prefixed(original,'original'),'revised_environment':prefixed(env,'revised'),
                'repair_report':repair['result'],'program_checks':program},comparison,step/'08_preservation_review',config)
            if not accepted_review(preserved):raise StageRejected('preservation failed')
        probe_root=step/'probe_workspace'
        if not probe_root.exists():shutil.copytree(root,probe_root)
        probe=agent('06_probe',solver_inputs(case,env),probe_root,step/'06_probe',config,('outputs',))
        blockers=[f for f in probe['result']['findings'] if f['severity']=='blocker']
        if not blockers:
            if probe['result']['completion']!='complete':raise StageRejected('probe incomplete without environment blocker')
            break
        if round_no==repair_limit:raise StageRejected('repair rounds exhausted')
        next_step=folder/f'repair-{round_no+1}';next_step.mkdir(exist_ok=True)
        repaired=next_step/'environment'
        if not repaired.exists():shutil.copytree(root,repaired)
        repair=agent('07_repair',{'task_id':case['task_id'],'original_intent':intent,'initial_plan':plan,
            'constraints':case['constraints'],'environment':env,'probe_report':probe['result'],
            'workspace':{'root':'/task','writable_paths':['REQUEST.txt','inputs']}},repaired,next_step/'07_repair',config,('inputs','REQUEST.txt'))
        root=repaired
    from workfactory.exports.harbor_export import ensure_task
    harbor_task=folder/'harbor'/case['task_id']
    ensure_task(case['task_id'],root,harbor_task)
    update(folder,harbor_task=str(harbor_task),harbor_verifier='pending')
    teacher_root=folder/'teacher_workspace'
    if not teacher_root.exists():shutil.copytree(root,teacher_root)
    teacher=agent('09_teacher',solver_inputs(case,environment(root,plan)),teacher_root,folder/'09_teacher',config,('outputs',))
    for name in teacher['result']['deliverables']:
        file=(teacher_root/name.removeprefix('/task/')).resolve()
        if not file.is_relative_to((teacher_root/'outputs').resolve()) or not file.is_file() or not file.stat().st_size:
            raise StageRejected('missing or invalid teacher deliverable '+name)
    teacher_pointer=folder/'09_teacher_active.json'
    teacher_log=read_json(teacher_pointer)['path'] if teacher_pointer.exists() else str(folder/'09_teacher')
    subprocess.run([sys.executable,'-m','workfactory.exports.export_trace',teacher_log,'--output',str(folder/'trajectory.json')],check=True)
    update(folder,state='candidate_complete',clean_environment=str(root),teacher_directory=str(teacher_root),
        trajectory=str(folder/'trajectory.json'),deliverables=teacher['result']['deliverables'],
        harbor_task=str(harbor_task),harbor_verifier='pending',
        manual_acceptance='pending',training_ready=False)
    return str(folder/'trajectory.json')


def run_case(case, model_dir, config, max_attempts=3):
    dest=model_dir/case['task_id'];dest.mkdir(exist_ok=True)
    if (dest/'seed.json').exists() and read_json(dest/'seed.json')!=case:
        raise ValueError('Task configuration changed; use a new output directory to preserve prior attempts')
    if (dest/'status.json').exists() and read_json(dest/'status.json').get('state')=='candidate_complete':return
    save(dest/'seed.json',case)
    discovery = config.get('_POLICY', {}).get('skill_discovery', {})
    if discovery.get('enabled') and not case.get('source_metadata', {}).get('skill_discovery'):
        from workfactory.sources.skills_discovery import enrich_skills, DiscoveryRejected
        from workfactory.sources.source_artifacts import full_text_inputs
        update(dest, state='discovering_skills', model=config['OPENAI_MODEL'], pid=os.getpid())
        try:
            case = enrich_skills(full_text_inputs(case), dest/'skill_discovery', stage_config(config, case['stage']))
        except DiscoveryRejected as exc:
            update(dest, state='rejected', reason=str(exc))
            return
        except Exception as exc:
            update(dest, state='error', reason=str(exc).replace(config['OPENAI_API_KEY'], '[REDACTED]'))
            raise
    if config.get('_POLICY',{}).get('external_retrieval'):
        from workfactory.sources.source_retrieval import enrich_case
        update(dest,state='retrieving_sources',model=config['OPENAI_MODEL'],pid=os.getpid())
        try:case=enrich_case(case,dest/'source_retrieval',config)
        except Exception as exc:
            update(dest,state='error',reason=str(exc).replace(config['OPENAI_API_KEY'],'[REDACTED]'))
            raise
    for n in range(1,max_attempts+1):
        folder=dest/f'attempt-{n:02d}'
        if folder.exists():
            state=read_json(folder/'status.json') if (folder/'status.json').exists() else {}
            if state.get('state')=='rejected':continue
        else:folder.mkdir()
        update(dest,state='running',model=config['OPENAI_MODEL'],attempt=n,pid=os.getpid())
        try:
            trajectory=attempt(case,folder,config)
            update(dest,state='candidate_complete',trajectory=trajectory,
                   harbor_task=str(folder/'harbor'/case['task_id']),harbor_verifier='pending',
                   manual_acceptance='pending',training_ready=False)
            return
        except StageRejected as exc:
            update(folder,state='rejected',reason=str(exc));update(dest,state='retry_pending',reason=str(exc))
        except Exception as exc:
            update(folder,state='error',reason=str(exc).replace(config['OPENAI_API_KEY'],'[REDACTED]'))
            update(dest,state='error',reason=str(exc).replace(config['OPENAI_API_KEY'],'[REDACTED]'))
            raise
    update(dest,state='needs_review',reason=f'{max_attempts} attempts retained; inspect original failures')


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--output',required=True)
    p.add_argument('--model',required=True);p.add_argument('--workers',type=int)
    p.add_argument('--pipeline-config',default=str(ROOT/'config/pipeline.json'))
    p.add_argument('--max-attempts',type=int,default=3)
    a=p.parse_args();config=load_config(a.config);config['OPENAI_MODEL']=a.model
    policy=load_policy(a.pipeline_config);config['_POLICY']=policy
    check_runtime(policy)
    config['API_MAX_CONCURRENCY']=str(policy['api_max_concurrency'])
    config['API_LIMIT_SCOPE']=policy.get('api_limit_scope','model')
    batch_cases=cases(policy)
    if policy['external_retrieval']:
        if policy.get('retrieval',{}).get('backend')!='responses_web_search' or config.get('OPENAI_API_MODE')!='responses':
            raise ValueError('Configure Responses web search before enabling external_retrieval')
    config.setdefault('MAX_OUTPUT_TOKENS','65536')
    config.setdefault('STREAM_RESPONSES','1')
    config.setdefault('TRANSPORT_ATTEMPTS','3')
    dest=Path(a.output).resolve()/a.model;dest.mkdir(parents=True,exist_ok=True)
    lock=dest/'batch.lock'
    lock_handle=lock.open('a+')
    try:fcntl.flock(lock_handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('existing batch process for this output')
    lock_handle.seek(0);lock_handle.truncate();lock_handle.write(str(os.getpid()));lock_handle.flush()
    snapshot=dest/'pipeline_config.json'
    if snapshot.exists() and read_json(snapshot)!=policy:
        lock_handle.close()
        raise ValueError('Pipeline configuration changed; use a new output directory')
    save(snapshot,policy)
    save(dest/'seeds.json',batch_cases);update(dest,state='running',model=a.model,pid=os.getpid(),target=len(batch_cases))
    try:
        def one_case(case):
            try:run_case(case,dest,config,a.max_attempts)
            except Exception as exc:
                print(json.dumps({'task_id':case['task_id'],'recoverable_case_error':str(exc).replace(config['OPENAI_API_KEY'],'[REDACTED]')},ensure_ascii=False),flush=True)
        with ThreadPoolExecutor(a.workers or policy['task_workers']) as pool:
            list(pool.map(one_case,batch_cases))
        states={c['task_id']:read_json(dest/c['task_id']/'status.json') for c in batch_cases}
        count=sum(x['state']=='candidate_complete' for x in states.values())
        update(dest,state='candidates_complete' if count==len(batch_cases) else 'needs_review',completed=count,tasks=states)
        if count!=len(batch_cases):raise SystemExit(2)
    except Exception as exc:
        update(dest,state='error',reason=str(exc).replace(config['OPENAI_API_KEY'],'[REDACTED]'));raise
    finally:lock_handle.close()


if __name__=='__main__':main()
