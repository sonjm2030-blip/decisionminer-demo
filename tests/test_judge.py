"""Offline contract tests: evidence integrity, abstentions, and review routing."""
import importlib.util
import json
import unittest
from pathlib import Path

DIR = Path(__file__).resolve().parents[1]/'research/judge'
DEPS = bool(importlib.util.find_spec('anthropic') and importlib.util.find_spec('jsonschema'))


def load(name):
    spec = importlib.util.spec_from_file_location('judge_'+name, DIR/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(DEPS, 'Install research/judge/requirements.txt for judge contract checks')
class JudgeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.grader = load('run')
        cls.evaluate = load('evaluate')
        cls.schema = json.loads((DIR/'schema.json').read_text())
        cls.payload = {'sources':[{'chunk_id':'C01-p001-s01',
                                  'text':'피심인은 30일 이내에 모든 구성사업자에게 서면으로 통지하여야 한다.'}]}

    def record(self, quote, chunk='C01-p001-s01'):
        return {'verdict':'검토','summary':'통지 내용 확인 필요',
                'issues':[{'kind':'처분','target':'답변','explanation':'통지명령 누락 가능',
                           'evidence':[{'chunk_id':chunk,'quote':quote}]}]}

    def test_citation_checks_original_text_and_source_id(self):
        valid = self.record('모든 구성사업자에게 서면으로 통지하여야 한다.')
        self.assertEqual(self.grader.validate_review(valid,self.payload,self.schema), [])
        invented = self.record('모든 구성사업자에게 교육을 실시하여야 한다.')
        self.assertIn('quote_not_found_verbatim',self.grader.validate_review(invented,self.payload,self.schema))
        wrong_source = self.record('모든 구성사업자에게 서면으로 통지하여야 한다.', 'C99-p001-s01')
        self.assertIn('unknown_source_chunk',self.grader.validate_review(wrong_source,self.payload,self.schema))

    def test_negative_without_evidence_does_not_pass(self):
        review = {'verdict':'부적합','summary':'오류가 있음','issues':[]}
        self.assertIn('negative_verdict_without_issue',self.grader.validate_review(review,self.payload,self.schema))

    def test_whitespace_variants_allowed_but_short_quotes_rejected(self):
        review = self.record('모든 구성사업자에게\n 서면으로 통지하여야 한다.')
        self.assertEqual(self.grader.validate_review(review,self.payload,self.schema), [])
        self.assertIn('quote_not_found_verbatim',self.grader.validate_review(self.record('서면'),self.payload,self.schema))

    def test_abstentions_and_invalid_outputs_remain_visible(self):
        result = self.evaluate.summarize(['적합','검토','부적합'], ['적합','판단보류','출력검증실패'])
        self.assertEqual(result['definite_count'], 1)
        self.assertAlmostEqual(result['coverage'], 1/3)
        self.assertAlmostEqual(result['matching_definite_over_all'], 1/3)
        self.assertEqual(result['predictions']['판단보류'], 1)
        self.assertEqual(result['predictions']['출력검증실패'], 1)

    def test_hybrid_routes_uncertainty_and_model_rejection_to_review(self):
        for prediction in ['검토','부적합','판단보류','출력검증실패']:
            self.assertEqual(self.evaluate.hybrid('적합',prediction),'검토')
        self.assertEqual(self.evaluate.hybrid('적합','적합'),'적합')
        self.assertEqual(self.evaluate.hybrid('검토','적합'),'검토')

    def test_invalid_original_verdict_is_not_silently_scored(self):
        record = {'status':'invalid_response','review':{'verdict':'적합'}}
        self.assertEqual(self.evaluate.effective_prediction(record),'출력검증실패')

    def test_published_token_cost_includes_output(self):
        self.assertEqual(self.grader.dollars({'input_tokens':1_000_000,'output_tokens':1_000_000}),18)

    def test_quote_audit_distinguishes_wrong_chunk_from_missing_text(self):
        quote = '모든 구성사업자에게 서면으로 통지하여야 한다.'
        payload = {'sources':[{'chunk_id':'C01-p001-s01','text':'첫 번째 청크에는 일반현황만 있습니다.'},
                              {'chunk_id':'C01-p002-s01','text':quote}]}
        row = {'item_id':'J001','review':self.record(quote)}
        counts = self.evaluate.quote_audit([row],{'J001':{'payload':payload}})
        self.assertEqual(counts,{'present_in_different_provided_chunk':1})


if __name__=='__main__':
    unittest.main()
