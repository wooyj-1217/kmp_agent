import copy
import unittest
from harness.qa import RESULT_SCHEMA,validate_result


def result():
    platform={'platform':'server','result':'PASS','environment':'local Python CLI','command_or_steps':'python3 src/greet.py Ada','expected':'Hello, Ada!','observed':'Hello, Ada!','doctor':'PASS','drive':'PASS','cleanup':'PASS','evidence':['qa-tools/trace.json']}
    return {'criteria':[{'criterion_id':'AC','result':'PASS','observation':'CLI executed','evidence':'qa-tools/trace.json','platform_results':[platform]}],'findings':[],'recommendation':'PASS','summary':'local actual observation fixture','reviewed_issue_ids':[]}


class PlatformSchemaTests(unittest.TestCase):
    def test_model_schema_constrains_exact_status_tokens(self):
        properties=RESULT_SCHEMA['properties']['criteria']['items']['properties']['platform_results']['items']['properties']
        for key in ('result','doctor','drive','cleanup'):
            self.assertEqual(set(properties[key]['enum']),{'PASS','FAIL','BLOCKED','NOT_RUN'})
        self.assertEqual(validate_result(result()),result())

    def test_observed_actual_model_pass_explanation_is_rejected(self):
        for key in ('doctor','drive','cleanup'):
            value=result();value['criteria'][0]['platform_results'][0][key]='PASS: child exited and evidence reopened'
            with self.assertRaisesRegex(ValueError,'exact token'):validate_result(value)

    def test_malformed_or_duplicate_platforms_rejected(self):
        for kind in ('nonlist','missing','duplicate','badplatform','evidence','blank'):
            value=result();row=value['criteria'][0];item=row['platform_results'][0]
            if kind=='nonlist':row['platform_results']='PASS'
            elif kind=='missing':item.pop('cleanup')
            elif kind=='duplicate':row['platform_results'].append(copy.deepcopy(item))
            elif kind=='badplatform':item['platform']='mobile'
            elif kind=='evidence':item['evidence']=[]
            else:item['observed']=''
            with self.subTest(kind=kind),self.assertRaises(ValueError):validate_result(value)
