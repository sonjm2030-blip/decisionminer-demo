"""Offline checks of source alignment, export contracts, and demo routes."""
import importlib.util
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / '09_code'))
from audit_baseline import audit

class BaselineDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = audit(ROOT)

    def test_independent_sources_align(self):
        r = self.report
        self.assertEqual((r['locked_cases'], r['qa_rows'], r['unique_qa_ids']), (22, 990, 990))
        self.assertEqual((r['raw_qa_case_count'], r['raw_qa_count']), (22, 990))
        self.assertEqual(r['missing_sidecars'], [])
        self.assertEqual((r['review_rows'], r['raw_review_rows']), (100, 100))
        self.assertEqual(sum(r['metadata_rows'].values()), 88)

    def test_metric_definitions_remain_separate(self):
        self.assertEqual(self.report['legacy_agreement']['strict_matches'], 55)
        self.assertEqual(self.report['legacy_agreement']['historical_direction_matches'], 88)
        self.assertEqual(self.report['legacy_agreement']['binary_matches'], 99)
        self.assertEqual(self.report['final_static_agreement']['binary_matches'], 98)

    def test_existing_export_contract(self):
        import export_tiers
        case = next(p for p in sorted((ROOT / '04_raw_outputs').iterdir()) if (p / 'qa_list.json').exists())
        with tempfile.TemporaryDirectory() as temp:
            result = export_tiers.export_tiers(case, temp, label_source='static')
            self.assertEqual(sum(result['counts'][key] for key in ['적합', '검토', '부적합']), 45)
            self.assertEqual(result['label_source_used'], {'static': 45, 'grounding': 0})
            self.assertTrue((Path(temp) / 'eval_gold.json').is_file())

@unittest.skipUnless(importlib.util.find_spec('flask') and importlib.util.find_spec('anthropic'),
                     'Install web_demo/requirements.txt for offline demo checks')
class DemoRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('decisionminer_baseline_demo', ROOT / 'web_demo/server.py')
        cls.server = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'baseline-test-key-not-valid',
                                     'DM_INDEX': str(ROOT / 'web_demo/index.html')}):
            spec.loader.exec_module(cls.server)
        cls.client = cls.server.app.test_client()

    def test_bundled_page_is_served(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(hashlib.sha256(response.data).hexdigest(),
                         hashlib.sha256((ROOT / 'web_demo/index.html').read_bytes()).hexdigest())
        response.close()

    def test_rule_validation_does_not_call_model(self):
        with patch.object(self.server._client.messages, 'create', side_effect=AssertionError('No model calls')):
            response = self.client.post('/api/validate', json={})
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.get_json(), dict)

    def test_missing_pdf_is_rejected_without_model(self):
        with patch.object(self.server._client.messages, 'create', side_effect=AssertionError('No model calls')):
            response = self.client.post('/api/decompose')
        self.assertEqual(response.status_code, 400)

if __name__ == '__main__':
    unittest.main()
