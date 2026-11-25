import unittest
from workfactory.pipeline.contracts import REQUIRED_CHECKS,output_errors

class FormatFitnessGateTests(unittest.TestCase):
    def review(self):
        return {'task_id':'t','status':'ok','result':{'verdict':'pass','checks':[{'criterion':c,'passed':True,'evidence':['inputs/policy.docx actual content'],'reason':'Work requires editable policy review'} for c in REQUIRED_CHECKS['05_construction_review']]},'issues':[]}
    def test_missing_format_review_cannot_pass(self):
        value=self.review();value['result']['checks']=[c for c in value['result']['checks'] if c['criterion']!='format_fitness']
        self.assertIn('review criteria incomplete or duplicated',output_errors('05_construction_review',value,{'task_id':'t'}))
    def test_format_failure_must_fail_overall_review(self):
        value=self.review()
        for c in value['result']['checks']:
            if c['criterion']=='format_fitness':c['passed']=False
        self.assertIn('verdict contradicts checks',output_errors('05_construction_review',value,{'task_id':'t'}))
        value['result']['verdict']='fail'
        self.assertFalse(output_errors('05_construction_review',value,{'task_id':'t'}))
