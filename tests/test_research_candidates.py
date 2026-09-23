import json
import math
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from research.candidates import build_candidates, _history_stats, _fit

ROOT = Path(__file__).resolve().parents[1]


def select(profile, candidate):
    result = profile
    for key, value in candidate.items():
        if key.startswith('filter_'):
            result = result[result[key[7:]] == value]
    return result


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'history.csv'
        self.profile = pd.DataFrame({'ID_NUMBER': range(20), 'current_tariff': ['a'] * 20,
                                     'arpu_segment': ['MID'] * 20, 'predicted_arpu': [2000.] * 20})
        self.tariffs = pd.DataFrame({'tariff_plan_code': ['a', 'b', 'c']})

    def history(self, changes, target='b', before=2000):
        return pd.DataFrame({'ID_NUMBER': range(len(changes)), 'TIME_KEY': ['2026-10'] * len(changes),
                             'tariff_plan_code_from': ['a'] * len(changes),
                             'tariff_plan_code_to': [target] * len(changes),
                             'AVG_ARPU_PREV_3M': [before] * len(changes),
                             'AVG_ARPU_NEXT_3M': [before * (1 + x) for x in changes]})

    def write(self, frame):
        frame.to_csv(self.path, index=False)

    def test_real_contract_determinism_and_input_immutability(self):
        p = pd.read_csv(ROOT / 'customer_profile.csv')
        t = pd.read_csv(ROOT / 'tariff_dictionary.csv')
        p_before, t_before = p.copy(deep=True), t.copy(deep=True)
        first = build_candidates(p, t)
        self.assertEqual(first, build_candidates(p, t))
        self.assertEqual(first, build_candidates(p.sample(frac=1, random_state=1), t.iloc[::-1]))
        pd.testing.assert_frame_equal(p, p_before)
        pd.testing.assert_frame_equal(t, t_before)
        self.assertTrue(first)
        json.dumps(first, allow_nan=False)
        seen, distinct = set(), set()
        for c in first:
            self.assertIn(c['target_tariff'], set(t.tariff_plan_code))
            self.assertNotEqual(c['target_tariff'], c['filter_current_tariff'])
            self.assertLessEqual(set(c), {'filter_current_tariff', 'filter_arpu_segment',
                                          'filter_data_segment', 'filter_call_segment',
                                          'target_tariff', 'prior_lift_ratio', 'history_support', 'priority'})
            group = select(p, c)
            self.assertTrue(10 <= len(group) <= 5000)
            filters = tuple(sorted((k, v) for k, v in c.items() if k.startswith('filter_')))
            if filters not in distinct:
                self.assertFalse(seen & set(group.ID_NUMBER))
                seen.update(group.ID_NUMBER)
                distinct.add(filters)
        self.assertEqual(len({tuple(sorted((k, v) for k, v in c.items() if k.startswith('filter_'))) for c in first[:12]}), 12)

    def test_missing_empty_and_header_only_history(self):
        for mode in ('missing', 'empty', 'headers'):
            with self.subTest(mode=mode):
                if mode == 'empty':
                    self.path.write_text('')
                if mode == 'headers':
                    self.write(self.history([]))
                result = build_candidates(self.profile, self.tariffs, self.path)
                self.assertEqual(len(result), 2)
                self.assertTrue(all(c['history_support'] == 0 and c['prior_lift_ratio'] == 0 for c in result))

    def test_malformed_history_is_not_silently_ignored(self):
        self.path.write_text('wrong\n1\n')
        with self.assertRaisesRegex(ValueError, 'History missing columns'):
            build_candidates(self.profile, self.tariffs, self.path)

    def test_sparse_evidence_is_shrunk_and_duplicates_do_not_inflate_it(self):
        one = self.history([.5])
        self.write(pd.concat([one, one]))
        small = _history_stats(self.path, ['a', 'b'])[('a', 'MID', 'b')]
        self.assertEqual(small[1], 1)
        self.assertGreater(small[2], 0)
        self.write(self.history([.5] * 100))
        large = _history_stats(self.path, ['a', 'b'])[('a', 'MID', 'b')]
        self.assertGreater(large[0], small[0])
        self.assertLess(large[2], small[2])

    def test_outlier_cannot_dominate_stable_evidence(self):
        self.write(self.history([.2] * 99 + [1000000]))
        ratio, support, margin = _history_stats(self.path, ['a', 'b'])[('a', 'MID', 'b')]
        self.assertEqual(support, 100)
        self.assertAlmostEqual(ratio, .2 * 100 / 120)
        self.assertTrue(math.isfinite(margin))

    def test_invalid_measurements_and_exact_arpu_boundaries(self):
        frames = [self.history([.2], before=v).assign(ID_NUMBER=i) for i, v in enumerate([0, 99, 100, 999, 1000, 5000, 5001, float('inf')])]
        frames += [self.history([float('nan')]), self.history([-2])]
        self.write(pd.concat(frames))
        stats = _history_stats(self.path, ['a', 'b'])
        self.assertEqual({key[1]: value[1] for key, value in stats.items()}, {'LOW': 2, 'MID': 2, 'HIGH': 1})

    def test_negative_history_is_preserved_and_cold_start_can_be_explored(self):
        self.write(self.history([-.5] * 30))
        result = build_candidates(self.profile, self.tariffs, self.path)
        self.assertEqual(result[0]['target_tariff'], 'c')
        negative = next(c for c in result if c['target_tariff'] == 'b')
        self.assertLess(negative['prior_lift_ratio'], 0)
        self.assertEqual(negative['priority'], 0)

    def test_large_cells_split_without_overlapping_or_truncating(self):
        p = pd.concat([self.profile] * 600, ignore_index=True)
        p['ID_NUMBER'] = range(len(p))
        p['data_segment'] = ['HEAVY'] * 6000 + ['LITE'] * 6000
        p['call_segment'] = (['LOW'] * 3000 + ['HIGH'] * 3000) * 2
        result = build_candidates(p, self.tariffs, self.path)
        groups = [set(select(p, c).ID_NUMBER) for c in result[:4]]
        self.assertEqual(len(result), 8)
        self.assertEqual(sum(map(len, groups)), len(p))
        self.assertEqual(len(set.union(*groups)), len(p))
        self.assertTrue(all(10 <= len(g) <= 5000 for g in groups))

    def test_unsplittable_and_tiny_cells_are_omitted(self):
        for n in (9, 5001):
            p = self.profile.iloc[[0] * n].copy()
            p['data_segment'], p['call_segment'] = 'HEAVY', 'HIGH'
            self.assertEqual(build_candidates(p, self.tariffs, self.path), [])
        for n in (10, 5000):
            self.assertTrue(build_candidates(self.profile.iloc[[0] * n], self.tariffs, self.path))

    def test_missing_data_labels_can_use_call_only_partition(self):
        p = self.profile.iloc[[0] * 6000].copy()
        p['data_segment'] = None
        p['call_segment'] = ['LOW'] * 3000 + ['HIGH'] * 3000
        result = build_candidates(p, self.tariffs, self.path)
        self.assertEqual(len(result), 4)
        self.assertTrue(all('filter_call_segment' in c and 'filter_data_segment' not in c for c in result))

    def test_packages_and_value_affect_priority_without_fabricating_lift(self):
        p = self.profile.assign(DATA_VOLUME=8000., OUT_LOC_OFFNET_MIN=100.)
        t = self.tariffs.assign(Data_in_PKG=[0, 10000, 0],
                                 Min_another_operator_in_PKG=[0, 100, 0], price_tariff=[0, 2000, 10000])
        result = build_candidates(p, t, self.path)
        self.assertEqual(result[0]['target_tariff'], 'b')
        self.assertEqual(result[0]['prior_lift_ratio'], 0)
        doubled = build_candidates(p.assign(predicted_arpu=4000.), t, self.path)
        self.assertGreater(doubled[0]['priority'], result[0]['priority'])
        self.assertGreater(_fit(p, t.iloc[1]), _fit(p, t.iloc[2]))
        shared = pd.Series({'Min_another_operator_and_city_in_PKG': 300})
        self.assertAlmostEqual(_fit(p.assign(OUT_LOC_LAND_MIN=250), shared), .5)
        self.assertAlmostEqual(_fit(p.assign(OUT_LOC_LAND_MIN=0), shared), 1.0)
        self.assertAlmostEqual(_fit(p, shared), .5)  # Unknown city demand is neutral.

    def test_invalid_labels_and_unknown_tariffs_are_omitted(self):
        self.assertEqual(build_candidates(self.profile.assign(arpu_segment='INVALID'), self.tariffs, self.path), [])
        self.assertEqual(build_candidates(self.profile.assign(current_tariff='unknown'), self.tariffs, self.path), [])
        self.assertEqual(build_candidates(self.profile.iloc[:0], self.tariffs, self.path), [])


if __name__ == '__main__':
    unittest.main()
