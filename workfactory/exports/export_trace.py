"""Export an auditable raw teacher candidate, without claiming SFT token masks."""
import argparse
import json
from pathlib import Path
from workfactory.clients.pilot import read_json,save


def main():
    p=argparse.ArgumentParser();p.add_argument('stage_directory');p.add_argument('--output',required=True)
    a=p.parse_args();root=Path(a.stage_directory)
    validation=read_json(root/'validation.json')
    if not validation['pass']:raise ValueError('cannot export a rejected stage as a candidate')
    requests=sorted(root.glob('[0-9][0-9]-request.json'))
    last=requests[-1];request=read_json(last)
    response=read_json(last.with_name(last.name.replace('request','response')))
    messages=[*request['messages'],response['choices'][0]['message']]
    failed=[]
    for index,message in enumerate(messages):
        if message['role']=='tool':
            result=json.loads(message['content'])
            if 'error' in result or result.get('exit_code',0)!=0:
                failed.append({'tool_call_id':message['tool_call_id'],'tool_result_message_index':index,
                               'error':result.get('error',result.get('stderr','nonzero exit code'))})
    save(Path(a.output),{'kind':'raw_teacher_trajectory_candidate','messages':messages,
        'tools':request['tools'],'requested_model':request['model'],'returned_model':response.get('model'),
        'final_result':read_json(root/'parsed.json'),'terminal_submission_accepted':True,
        'failed_tool_calls':failed,'artifact_hashes':validation['after'],
        'tokenized':False,'sft_loss_mask_generated':False,
        'training_ready':False,'limitations':['raw trace only','no tokenizer-specific loss mask','no length-tail rejection sampling or baseline blind comparison'],
        'source_stage':str(root)})


if __name__=='__main__':main()
