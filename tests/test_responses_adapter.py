import unittest
from workfactory.models.responses import request_payload, normalize

class ResponsesTests(unittest.TestCase):
    def test_reasoning_and_tool_results_replay(self):
        raw={'status':'completed','output':[{'type':'reasoning','id':'r','summary':[],'encrypted_content':'opaque'}, {'type':'function_call','call_id':'c','name':'read_text','arguments':'{}'}], 'usage':{'input_tokens':7,'output_tokens':3,'total_tokens':10}}
        result=normalize(raw)
        messages=[{'role':'user','content':'read'},result['choices'][0]['message'],{'role':'tool','tool_call_id':'c','content':'ok'}]
        payload=request_payload({'OPENAI_MODEL':'gpt-6.1-sol'},messages,100,[{'type':'function','function':{'name':'read_text','parameters':{'type':'object'}}}])
        self.assertEqual(payload['input'][1:3],raw['output'])
        self.assertEqual(payload['input'][3]['call_id'],'c')
        self.assertFalse(payload['tools'][0]['strict'])
        self.assertEqual(result['usage']['prompt_tokens'],7)
    def test_incomplete_rejected(self):
        with self.assertRaises(RuntimeError):normalize({'status':'incomplete','incomplete_details':{'reason':'max_output_tokens'}})
