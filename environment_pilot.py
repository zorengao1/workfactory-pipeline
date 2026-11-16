"""Actual file build and review for one saved synthetic skill task."""
import argparse
import json
import shutil
from zipfile import ZipFile
from pathlib import Path

from contracts import ROOT
from pilot import load_config, read_json, save
from tool_runtime import Broker, inventory, run_agent, TOOLS


PLAN_SOURCE='runs/skill-name-retest-v1/03_plan/parsed.json'


def environment(root, plan):
    return {'user_request':(root/'REQUEST.txt').read_text(),
            'reference_files':[{'id':f['id'],'path':f['path'],'format':f['format']} for f in plan['reference_files']],
            'resources':{'tools':[t['function']['name'] for t in TOOLS],
                         'network':False,'input_policy':'reference files and request are read-only for solver',
                         'output_directory':'outputs'}}


def checks(root, plan):
    expected={'REQUEST.txt',*(f['path'] for f in plan['reference_files'])}
    actual=set(inventory(root))
    formats=[]
    for item in plan['reference_files']:
        p=root/item['path'];fmt=item['format'].lower().lstrip('.')
        valid=p.suffix.lower()=='.'+fmt and p.is_file()
        if valid and fmt in {'docx','xlsx','pptx'}:
            try:
                with ZipFile(p) as z:
                    prefix={'docx':'word/','xlsx':'xl/','pptx':'ppt/'}[fmt]
                    valid='[Content_Types].xml' in z.namelist() and any(n.startswith(prefix) for n in z.namelist())
            except Exception:valid=False
        if valid and fmt=='pdf':
            with p.open('rb') as stream:valid=stream.read(5)==b'%PDF-'
        formats.append({'path':item['path'],'format':fmt,'valid':valid})
    return {'expected_files':sorted(expected),'actual_files':sorted(actual),
            'exact_file_set':actual==expected,'nonempty':all((root/p).stat().st_size>0 for p in actual),
            'format_match':all(f['valid'] for f in formats),'format_checks':formats,
            'sha256':inventory(root)}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--resume-review',action='store_true')
    args=parser.parse_args()
    dest=Path(args.output).resolve()
    config=load_config(args.config)
    case=read_json(ROOT/'fixtures/pilot_cases.json')[1]
    plan=read_json(ROOT/PLAN_SOURCE)['result']
    root=dest/'environment'
    if not args.resume_review:
        dest.mkdir(parents=True,exist_ok=False);root.mkdir()
        save(dest/'initial_plan.json',plan)
        save(dest/'constraints.json',case['constraints'])
        workspace={'root':'/task','writable_directory':'/task/inputs','reference_directory':'/task/inputs','request_path':'/task/REQUEST.txt'}
        built=run_agent('04_build',{'task_id':case['task_id'],'plan':plan,'constraints':case['constraints'],'workspace':workspace},root,dest/'04_build',config,('inputs','REQUEST.txt'))
        if not built or built['status']!='ok':
            save(dest/'summary.json',{'reached':'04_build','outcome':'build_not_accepted'});return
    check=checks(root,plan)
    save(dest/'program_checks.json',check)
    if not check['exact_file_set'] or not check['nonempty']:
        save(dest/'summary.json',{'reached':'program_checks','outcome':'failed'});return
    env=environment(root,plan)
    review=run_agent('05_construction_review',{'task_id':case['task_id'],'plan':plan,'environment':env,'program_checks':check},root,dest/'05_construction_review',config)
    if not review or review['status']!='ok' or review['result']['verdict']!='pass':
        save(dest/'summary.json',{'reached':'05_construction_review','outcome':'not_accepted'});return
    probe_root=dest/'probe_workspace'
    shutil.copytree(root,probe_root)
    probe=run_agent('06_probe',{'task_id':case['task_id'],'environment':env,'workspace':{'root':'/task','read_only_inputs':['REQUEST.txt','inputs'],'output_directory':'outputs'}},probe_root,dest/'06_probe',config,('outputs',))
    save(dest/'summary.json',{'reached':'06_probe','probe':probe,'environment_sha256':inventory(root)})


if __name__=='__main__':main()
