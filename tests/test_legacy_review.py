"""Check metrics and tie handling used by the retrospective analysis."""
import importlib.util
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / 'research/legacy_review/analyze.py'
SPEC = importlib.util.spec_from_file_location('legacy_review_analysis', PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class LegacyReviewMetricsTests(unittest.TestCase):
    def test_imbalance_does_not_hide_missed_rejections(self):
        truth = ['적합'] * 98 + ['검토', '부적합']
        result = MODULE.metrics(truth, ['적합'] * 100)
        self.assertEqual(result['usable_binary_matches'], 99)
        self.assertEqual(result['strict_matches'], 98)
        self.assertAlmostEqual(result['balanced_accuracy'], 1/3)
        self.assertEqual(result['needs_review_detection']['recall'], 0)
        self.assertIsNone(result['per_class']['부적합']['precision'])

    def test_metrics_against_hand_computed_confusion(self):
        result = MODULE.metrics(['적합','적합','검토','부적합'], ['적합','검토','검토','검토'])
        self.assertEqual(result['confusion_rows_human_cols_rule'], [[1,1,0],[0,1,0],[0,1,0]])
        self.assertEqual(result['strict_agreement'], 0.5)
        self.assertEqual(result['balanced_accuracy'], 0.5)
        self.assertAlmostEqual(result['macro_f1'], (2/3+0.5)/3)

    def test_uniform_ties_ignore_input_order(self):
        items = [{'priority':[1,0,1], 'needs_review':x} for x in [True,False,True,False]]
        result = MODULE.budget_yield(items, 1)
        self.assertEqual(result, MODULE.budget_yield(list(reversed(items)), 1))
        self.assertEqual(result['expected_needs_review_found'], 0.5)
        self.assertEqual((result['tie_min'], result['tie_max']), (0,1))

    def test_content_change_excludes_id_match(self):
        row = [None, '일반국민', '하도급', '하도급법', '제3조', '같은 질문', '원답변']
        master = {'페르소나':'일반국민', '사건유형':'하도급', '적용법령':'하도급법',
                  '적용조문':'제3조', '질문':'같은 질문', '답변':'수정답변'}
        self.assertEqual(MODULE.shared_mismatches(row, master), ['답변'])


if __name__ == '__main__':
    unittest.main()
