import tempfile
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from research.candidates import _history_stats
from research.stability import draw_events, summarize_draws, eligible_events


def candidate(target, support=20):
    return {'filter_current_tariff': 'a', 'filter_arpu_segment': 'MID',
            'target_tariff': target, 'history_support': support, 'prior_lift_ratio': .2}


class StabilityTests(unittest.TestCase):
    def test_resampled_multiplicity_survives_deduplication(self):
        events = pd.DataFrame({'ID_NUMBER': [10, 11], 'TIME_KEY': ['2026-10'] * 2,
                               'tariff_plan_code_from': ['a'] * 2, 'tariff_plan_code_to': ['b'] * 2,
                               'AVG_ARPU_PREV_3M': [2000, 3000], 'AVG_ARPU_NEXT_3M': [2200, 3500]})
        original = events.copy(deep=True)
        class RepeatedDraw:
            def integers(self, low, high, size):
                return np.zeros(size, dtype=int)
        sampled = draw_events(events, RepeatedDraw())
        self.assertEqual(sampled.ID_NUMBER.nunique(), 2)
        self.assertEqual(sampled.AVG_ARPU_PREV_3M.tolist(), [2000, 2000])
        pd.testing.assert_frame_equal(events, original)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'sample.csv'
            sampled.to_csv(path, index=False)
            self.assertEqual(_history_stats(path, ['a', 'b'])[('a', 'MID', 'b')][1], 2)

    def test_seeded_resampling_is_deterministic(self):
        events = pd.DataFrame({'ID_NUMBER': range(10), 'value': range(10)})
        pd.testing.assert_frame_equal(draw_events(events, np.random.default_rng(12)),
                                      draw_events(events, np.random.default_rng(12)))

    def test_stability_denominator_includes_absent_pairs(self):
        base = [candidate('b'), candidate('c')]
        summary = summarize_draws(base, [[candidate('b'), candidate('c')], [candidate('c')]], 1)
        rows = {r['key'].split('|')[-1]: r for r in summary['candidates']}
        self.assertEqual(rows['b']['top_k_fraction'], .5)
        self.assertEqual(rows['b']['absent_count'], 1)
        self.assertEqual(rows['b']['rank_quantiles_when_present']['median'], 1.)
        self.assertEqual(summary['first_choice_counts_by_cell']['a|MID|*|*'], {'b': 1, 'c': 1})
        self.assertEqual(summary['top_k_jaccard']['mean'], .5)

    def test_leave_one_out_eligibility_matches_boundaries_and_validity(self):
        events = pd.DataFrame({'tariff_plan_code_from': ['a'] * 7,
                               'tariff_plan_code_to': ['b'] * 7,
                               'AVG_ARPU_PREV_3M': [99, 999, 1000, 5000, 5001, 2000, 2000],
                               'AVG_ARPU_NEXT_3M': [100, 1100, 1200, 6000, 6000, np.inf, -1]})
        self.assertEqual(eligible_events(events, candidate('b')).tolist(), [2, 3])


if __name__ == '__main__':
    unittest.main()
