"""Controlled missing-permissions sheet test, without changing the accepted environment."""
import argparse
import copy
import shutil
from pathlib import Path
from contracts import ROOT
from pilot import read_json,load_config,save
from tool_runtime import Broker,inventory,run_agent
from environment_pilot import environment


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();dest=Path(a.output).resolve();dest.mkdir(parents=True,exist_ok=False)
    source=ROOT/'runs/environment-pilot-v3'
    root=dest/'environment';shutil.copytree(source/'environment',root)
    shutil.copyfile(source/'initial_plan.json',dest/'initial_plan.json')
    shutil.copyfile(source/'constraints.json',dest/'constraints.json')
    plan=read_json(dest/'initial_plan.json');before=inventory(root)
    spec=read_json(source/'04_build/tools/workbook-002/spec.json')
    sheets=[s for s in copy.deepcopy(spec['sheets']) if s['name']!='处理权限']
    assert len(sheets)==len(spec['sheets'])-1
    broker=Broker(root,dest/'fault_injection_tools',('inputs',))
    broker.workbook(root/'inputs/synthetic_po_data.xlsx',sheets)
    save(dest/'fault_injection.json',{'method':'remove exactly the 处理权限 sheet from a copied workbook',
        'expected_behavior':'probe reports a blocker for assigning required responsibility roles without provided authorization rules',
        'source_run':str(source.relative_to(ROOT)),'before':before,'after':inventory(root)})
    probe_root=dest/'probe_workspace';shutil.copytree(root,probe_root)
    result=run_agent('06_probe',{'task_id':'pilot_skill_001','environment':environment(root,plan),
        'workspace':{'root':'/task','read_only_inputs':['REQUEST.txt','inputs'],'output_directory':'outputs'}},
        probe_root,dest/'06_probe',load_config(a.config),('outputs',))
    passed=bool(result and result['status']=='ok' and any(f['severity']=='blocker' for f in result['result']['findings']))
    save(dest/'summary.json',{'negative_probe_detected_blocker':passed,'probe':result})


if __name__=='__main__':main()
