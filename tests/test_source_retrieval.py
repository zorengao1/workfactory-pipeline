import json
import unittest
from source_retrieval import source_urls, parse_research
from responses_adapter import request_payload

class MixedInputTests(unittest.TestCase):
    def test_native_search_has_required_tool_and_auditable_sources(self):
        p=request_payload({'OPENAI_MODEL':'gpt','NATIVE_WEB_SEARCH':'1'},[{'role':'user','content':'find'}],7000,None)
        self.assertEqual(p['tool_choice'],'required')
        self.assertIn('web_search_call.action.sources',p['include'])
        self.assertEqual(p['tools'][0]['type'],'web_search')
        self.assertFalse(p['stream'])
        self.assertEqual(source_urls({'output':[{'type':'web_search_call','action':{'sources':[{'url':'https://example.org/report'}]}}]}),['https://example.org/report'])
    def test_missing_real_artifact_rejected(self):
        with self.assertRaises(ValueError):parse_research('{}')
