import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.provenance import ROOT, fingerprint, verify_unchanged, write_new_json

spec = importlib.util.spec_from_file_location('benchmark_under_test', ROOT / 'tests/test_research_benchmark.py')
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class BenchmarkEvidenceTests(unittest.TestCase):
    def test_summary_is_paired_and_retains_losses(self):
        rows = []
        for seed, values in enumerate(((10., 12., 9.), (20., 15., 18.))):
            variants = {name: dict(zip(benchmark.METRICS, [value, 4., 10, 2, 1]), seconds=.5)
                        for name, value in zip(benchmark.VARIANTS, values)}
            rows.append({'seed': seed, 'variants': variants})
        summary = benchmark.summarize(rows, {'control': [0, 1]})['control']
        self.assertEqual(summary['variants']['current']['net_arpu_gain']['mean'], 13.5)
        pair = summary['paired']['current_minus_original']
        self.assertEqual((pair['improvements'], pair['worsenings'], pair['worse_seeds']), (1, 1, [1]))
        rows[0]['variants']['current'] = {'error': 'deliberate failure', 'seconds': .1}
        summary = benchmark.summarize(rows, {'control': [0, 1]})['control']
        self.assertEqual(summary['variants']['current']['failed'], 1)
        self.assertEqual(summary['paired']['current_minus_original']['paired_count'], 1)

    def test_historical_output_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'evidence.json'
            write_new_json(path, {'original': 1})
            with self.assertRaises(FileExistsError):
                write_new_json(path, {'replacement': 2})
            self.assertEqual(json.loads(path.read_text()), {'original': 1})

    def test_hashes_detect_content_change_and_label_line_endings(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'source.py'
            path.write_bytes(b'x=1\r\n')
            first = fingerprint(path)
            path.write_bytes(b'x=1\n')
            second = fingerprint(path)
            self.assertNotEqual(first['sha256'], second['sha256'])
            self.assertEqual(first['lf_sha256'], second['lf_sha256'])
            with patch('research.provenance.ROOT', Path(folder)):
                with self.assertRaisesRegex(RuntimeError, 'changed during run'):
                    verify_unchanged({'sources': {'source.py': first}, 'inputs': {}})

    def test_builder_source_is_actual_and_history_path_is_explicit(self):
        source = 'def build_candidates(profile, tariffs, history_path=None):\n    return [str(history_path), 123]\n'
        builder = benchmark.load_builder(source, ROOT / 'research/snapshot.py')
        self.assertEqual(builder(None, None), [str(ROOT / 'data/change_tariff.csv'), 123])

    def test_full_agent_comparison_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'plan.json'
            path.write_text(json.dumps({'comparison_kind': 'full_agents'}))
            with self.assertRaisesRegex(ValueError, 'full-agent comparison'):
                benchmark.benchmark(path)


if __name__ == '__main__':
    unittest.main()
