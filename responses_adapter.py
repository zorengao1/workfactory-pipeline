"""Responses transport with replayable reasoning and function-call history."""
import json
import urllib.request
import urllib.error


def request_payload(config, messages, max_tokens, tools):
    items=[]
    for message in messages:
        if message.get('_responses_output') is not None:
            items.extend(message['_responses_output'])
        elif message['role']=='tool':
            items.append({'type':'function_call_output','call_id':message['tool_call_id'],'output':message['content']})
        else:
            items.append({'role':message['role'],'content':message.get('content') or ''})
    payload={'model':config['OPENAI_MODEL'],'input':items,'max_output_tokens':max_tokens,
             'store':False,'include':['reasoning.encrypted_content']}
    if tools is not None:
        payload['tools']=[{'type':'function',**tool['function'],'strict':False} for tool in tools]
    if config.get('REASONING_EFFORT'):
        payload['reasoning']={'effort':config['REASONING_EFFORT']}
    return payload


def normalize(result):
    if result.get('status')!='completed':
        raise RuntimeError('Responses request not completed '+json.dumps(result.get('error') or result.get('incomplete_details')))
    output=result.get('output',[])
    message={'role':'assistant','content':'','_responses_output':output}
    calls=[]
    for item in output:
        if item['type']=='message':
            message['content']+=''.join(c.get('text','') for c in item.get('content',[]) if c['type']=='output_text')
        elif item['type']=='function_call':
            calls.append({'id':item['call_id'],'type':'function','function':{'name':item['name'],'arguments':item['arguments']}})
    if calls:message['tool_calls']=calls
    usage=result.get('usage',{})
    return {'id':result.get('id'),'model':result.get('model'),'created':result.get('created_at'),
            'usage':{'prompt_tokens':usage.get('input_tokens',0),'completion_tokens':usage.get('output_tokens',0),
                     'total_tokens':usage.get('total_tokens',0),'prompt_tokens_details':usage.get('input_tokens_details',{}),
                     'completion_tokens_details':usage.get('output_tokens_details',{})},
            'choices':[{'index':0,'message':message,'finish_reason':'tool_calls' if calls else 'stop'}],
            'responses_raw':result}


def complete_responses(config,messages,max_tokens,tools):
    from pilot import NoRedirect, TransientAPIError
    payload=request_payload(config,messages,max_tokens,tools)
    request=urllib.request.Request(config['OPENAI_BASE_URL'].rstrip('/')+'/responses',
        data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+config['OPENAI_API_KEY']})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request,timeout=600) as response:
            result=json.load(response)
    except urllib.error.HTTPError as exc:
        body=exc.read(16384).decode(errors='replace').replace(config['OPENAI_API_KEY'],'[REDACTED]')
        error=TransientAPIError if exc.code in {429,500,502,503,504} else RuntimeError
        raise error('Responses HTTP '+str(exc.code)+' '+body) from None
    result=json.loads(json.dumps(result).replace(config['OPENAI_API_KEY'],'[REDACTED]'))
    return normalize(result)
