import unittest
from scripts.audit_run import price_usage

class CostBucketTests(unittest.TestCase):
    def setUp(self):
        self.pricing={'standard_max_length':272000,'standard':{'input':2,'output':10,'cache_read':.1,'cache_write':2.5},'long_context':{'input':4,'output':15,'cache_read':.2,'cache_write':5}}
    def test_cache_writes_are_not_also_charged_as_plain_input(self):
        tier,buckets,components,total=price_usage({'prompt_tokens':100000,'prompt_tokens_details':{'cached_tokens':60000,'cache_write_tokens':30000},'completion_tokens':1000},self.pricing)
        self.assertEqual(tier,'standard');self.assertEqual(buckets['input'],10000)
        self.assertAlmostEqual(total,.02+.006+.075+.01)
    def test_long_context_tier_is_applied_per_request(self):
        tier,_,_,total=price_usage({'prompt_tokens':300000,'completion_tokens':1000},self.pricing)
        self.assertEqual(tier,'long_context');self.assertAlmostEqual(total,1.215)
