import io
import json
import unittest
from unittest.mock import patch
from workfactory.clients.pilot import collect_stream, complete, IncompleteStreamError


class StreamTests(unittest.TestCase):
    def test_tool_arguments_reasoning_and_usage_are_preserved(self):
        chunks=[{'id':'x','model':'m','choices':[{'index':0,'delta':{'reasoning_content':'reason','tool_calls':[{'index':0,'id':'call1','function':{'name':'read_text','arguments':'{"path"'}}]}}]},
                {'choices':[{'delta':{'tool_calls':[{'index':0,'function':{'arguments':':"REQUEST.txt"}'}}]},'finish_reason':'tool_calls'}]},
                {'choices':[],'usage':{'prompt_tokens':5,'completion_tokens':8}}]
        raw=''.join('data: '+json.dumps(c)+'\n\n' for c in chunks)+'data: [DONE]\n'
        r=collect_stream(io.BytesIO(raw.encode()))
        m=r['choices'][0]['message']
        self.assertEqual(json.loads(m['tool_calls'][0]['function']['arguments']),{'path':'REQUEST.txt'})
        self.assertEqual(m['reasoning_content'],'reason')
        self.assertEqual(r['usage']['completion_tokens'],8)

    def test_interrupted_stream_cannot_be_accepted(self):
        with self.assertRaises(RuntimeError):collect_stream(io.BytesIO(b'data: {"choices":[]}\n'))

    def test_incomplete_response_retries_identical_payload(self):
        config={'TRANSPORT_ATTEMPTS':'2','OPENAI_API_KEY':'test'}
        messages=[{'role':'user','content':'task'}]
        with patch('workfactory.clients.pilot.complete_once',side_effect=[IncompleteStreamError('truncated'),{'ok':True}]) as call, patch('workfactory.clients.pilot.time.sleep'):
            self.assertEqual(complete(config,messages,100),{'ok':True})
        self.assertEqual(call.call_count,2)
        self.assertEqual(call.call_args_list[0],call.call_args_list[1])


if __name__=='__main__':unittest.main()
