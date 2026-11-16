"""Continue an accepted probe through bounded repair and an independent teacher pilot."""
import argparse
import copy
import shutil
from pathlib import Path

from environment_pilot import environment, checks
from pilot import load_config, read_json, save
from contracts import ROOT
from tool_runtime import inventory, run_agent


def accepted(response):
    return response is not None and response['status']=='ok'


def accepted_review(response):
    return accepted(response) and response['result']['verdict']=='pass'


def prefixed(env, prefix):
    result=copy.deepcopy(env)
    for f in result['reference_files']:f['path']=prefix+'/'+f['path']
    return result


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--config',required=True);p.add_argument('--run',required=True)
    p.add_argument('--skip-teacher',action='store_true')
    a=p.parse_args();dest=Path(a.run).resolve();config=load_config(a.config)
    case=read_json(ROOT/'fixtures/pilot_cases.json')[1];task_id=case['task_id']
    plan=read_json(dest/'initial_plan.json')
    intent=read_json(ROOT/'runs/skill-retry-v2/pilot_skill_001/01b_skill/parsed.json')['result']
    root=dest/'environment';original=environment(root,plan)
    probe=read_json(dest/'06_probe/parsed.json')
    if not read_json(dest/'06_probe/validation.json')['pass'] or not accepted(probe):
        raise RuntimeError('initial probe is not accepted')
    state={'case':task_id,'repair_rounds':[],'teacher_model':config['OPENAI_MODEL'],
           'scope':'one pilot teacher; not SFT filtering, rejection sampling, or full paper reproduction'}
    for round_no in range(1,4):
        blockers=[f for f in probe['result']['findings'] if f['severity']=='blocker']
        if not blockers:break
        folder=dest/f'repair-{round_no}';folder.mkdir()
        repaired=folder/'environment';shutil.copytree(root,repaired)
        repair=run_agent('07_repair',{'task_id':task_id,'original_intent':intent,'initial_plan':plan,
            'constraints':case['constraints'],'environment':environment(repaired,plan),'probe_report':probe['result'],
            'workspace':{'root':'/task','writable_paths':['REQUEST.txt','inputs']}},repaired,folder/'07_repair',config,('inputs','REQUEST.txt'))
        if not accepted(repair):
            state['outcome']='repair_not_accepted';save(dest/'continuation_summary.json',state);return
        program=checks(repaired,plan);save(folder/'program_checks.json',program)
        if not program['exact_file_set'] or not program['nonempty']:
            state['outcome']='repair_file_structure_failed';save(dest/'continuation_summary.json',state);return
        env=environment(repaired,plan)
        review=run_agent('05_construction_review',{'task_id':task_id,'plan':plan,'environment':env,'program_checks':program},
                         repaired,folder/'05_construction_review',config)
        comparison=folder/'comparison';comparison.mkdir()
        shutil.copytree(dest/'environment',comparison/'original')
        shutil.copytree(repaired,comparison/'revised')
        preserve=run_agent('08_preservation_review',{'task_id':task_id,'original_intent':intent,'initial_plan':plan,
            'original_environment':prefixed(original,'original'),'revised_environment':prefixed(env,'revised'),
            'repair_report':repair['result'],'program_checks':program},comparison,folder/'08_preservation_review',config)
        state['repair_rounds'].append({'round':round_no,'construction_pass':accepted_review(review),
                                      'preservation_pass':accepted_review(preserve)})
        if not accepted_review(review) or not accepted_review(preserve):
            state['outcome']='repair_review_failed_discard';save(dest/'continuation_summary.json',state);return
        root=repaired
        probe_root=folder/'probe_workspace';shutil.copytree(root,probe_root)
        probe=run_agent('06_probe',{'task_id':task_id,'environment':env,'workspace':{'root':'/task',
            'read_only_inputs':['REQUEST.txt','inputs'],'output_directory':'outputs'}},probe_root,folder/'06_probe',config,('outputs',))
        if not accepted(probe):
            state['outcome']='probe_not_accepted';save(dest/'continuation_summary.json',state);return
    if any(f['severity']=='blocker' for f in probe['result']['findings']) or probe['result']['completion']!='complete':
        state['outcome']='probe_incomplete';save(dest/'continuation_summary.json',state);return
    if a.skip_teacher:
        state.update(outcome='probe_complete_after_repair',clean_environment=str(root.relative_to(dest)))
        save(dest/'continuation_summary.json',state);return
    teacher_root=dest/'teacher_workspace';shutil.copytree(root,teacher_root)
    env=environment(root,plan)
    teacher=run_agent('09_teacher',{'task_id':task_id,'environment':env,'workspace':{'root':'/task',
        'read_only_inputs':['REQUEST.txt','inputs'],'output_directory':'outputs'}},teacher_root,dest/'09_teacher',config,('outputs',))
    existing=[];missing=[]
    if accepted(teacher):
        for name in teacher['result']['deliverables']:
            relative=name.removeprefix('/task/')
            file=(teacher_root/relative).resolve()
            if not file.is_relative_to(teacher_root/'outputs') or not file.is_file():missing.append(name)
            else:existing.append(relative)
    state.update(outcome='teacher_files_created' if accepted(teacher) and not missing else 'teacher_not_accepted',
                 clean_environment=str(root.relative_to(dest)),teacher_deliverables=existing,
                 missing_deliverables=missing,teacher_workspace_sha256=inventory(teacher_root))
    save(dest/'continuation_summary.json',state)


if __name__=='__main__':main()
