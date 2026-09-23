import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from research.median_candidates import build_candidates, HISTORY_COLUMNS
from strategy.planner import select_segment

ROOT = Path(__file__).resolve().parents[1]


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "history.csv"
        self.profile = pd.DataFrame({
            "ID_NUMBER": range(20), "current_tariff": ["tariff_1"] * 20,
            "arpu_segment": ["MID"] * 20, "predicted_arpu": [2000.] * 20,
            "DATA_VOLUME": [1500.] * 20, "OUT_LOC_OFFNET_MIN": [50.] * 20,
        })
        self.tariffs = pd.DataFrame({"tariff_plan_code": ["tariff_1", "tariff_2", "tariff_3"],
                                     "price_tariff": [1000, 1800, 9000],
                                     "Data_in_PKG": [100, 2048, 0],
                                     "Min_another_operator_in_PKG": [0, 80, 0]})

    def history(self, after):
        pd.DataFrame({"tariff_plan_code_from": ["tariff_1"] * len(after),
                      "tariff_plan_code_to": ["tariff_2"] * len(after),
                      "AVG_ARPU_PREV_3M": [2000.] * len(after),
                      "AVG_ARPU_NEXT_3M": after}).to_csv(self.path, index=False)

    def test_missing_empty_and_no_matching_history(self):
        missing = build_candidates(self.profile, self.tariffs, self.path)
        pd.DataFrame(columns=HISTORY_COLUMNS).to_csv(self.path, index=False)
        self.assertEqual(missing, build_candidates(self.profile, self.tariffs, self.path))
        self.path.write_text("")
        self.assertEqual(missing, build_candidates(self.profile, self.tariffs, self.path))
        self.history([float("nan"), float("inf"), -1])
        self.assertEqual(missing, build_candidates(self.profile, self.tariffs, self.path))
        self.assertEqual(missing[0]["target_tariff"], "tariff_2")
        self.assertTrue(all(c["history_support"] == 0 and c["prior_lift_ratio"] == 0 for c in missing))

    def test_outlier_resistance_and_rare_history_shrinkage(self):
        self.history([2200.] * 20)
        clean = build_candidates(self.profile, self.tariffs, self.path)[0]
        self.history([2200.] * 19 + [1e12])
        outlier = build_candidates(self.profile, self.tariffs, self.path)[0]
        self.assertAlmostEqual(clean["prior_lift_ratio"], outlier["prior_lift_ratio"])
        self.history([2200.])
        rare = next(c for c in build_candidates(self.profile, self.tariffs, self.path) if c["target_tariff"] == "tariff_2")
        self.assertLess(rare["prior_lift_ratio"], clean["prior_lift_ratio"])
        self.assertEqual(rare["history_support"], 1)

    def test_negative_history_is_not_positive_effect(self):
        self.history([1000.] * 30)
        candidate = next(c for c in build_candidates(self.profile, self.tariffs, self.path) if c["target_tariff"] == "tariff_2")
        self.assertLess(candidate["prior_lift_ratio"], 0)
        self.assertEqual(candidate["priority"], 0)

    def test_duplicate_events_do_not_inflate_support(self):
        self.history([2200.] * 20)
        history = pd.read_csv(self.path)
        history["ID_NUMBER"] = range(20)
        history["TIME_KEY"] = "2026-10-01"
        history.to_csv(self.path, index=False)
        first = build_candidates(self.profile, self.tariffs, self.path)
        pd.concat([history, history.iloc[:4]]).sample(frac=1, random_state=1).to_csv(self.path, index=False)
        self.assertEqual(first, build_candidates(self.profile, self.tariffs, self.path))

    def test_history_bin_edges(self):
        history = pd.DataFrame({
            "tariff_plan_code_from": ["tariff_1"] * 4,
            "tariff_plan_code_to": ["tariff_2"] * 4,
            "AVG_ARPU_PREV_3M": [999., 1000., 4999., 5000.],
            "AVG_ARPU_NEXT_3M": [1098.9, 1100., 5498.9, 5500.]})
        history.to_csv(self.path, index=False)
        result = build_candidates(self.profile, self.tariffs, self.path)
        candidate = next(c for c in result if c["target_tariff"] == "tariff_2")
        self.assertEqual(candidate["history_support"], 2)

    def test_split_large_audience_without_overlap_or_truncation(self):
        profile = pd.concat([self.profile] * 600, ignore_index=True)
        profile["ID_NUMBER"] = range(len(profile))
        profile["data_segment"] = ["HEAVY"] * 6000 + ["LITE"] * 6000
        profile["call_segment"] = ["LOW"] * 3000 + ["HIGH"] * 3000 + ["MEDIUM"] * 6000
        candidates = build_candidates(profile, self.tariffs, self.path)
        first_round = candidates[:2]
        ids = [set(select_segment(profile, c).ID_NUMBER) for c in first_round]
        self.assertEqual([len(s) for s in ids], [3000, 3000])
        self.assertFalse(ids[0] & ids[1])
        self.assertEqual(len(candidates), 4)  # unsplittable 6000-person leaf omitted
        for c in candidates:
            self.assertTrue(10 <= len(select_segment(profile, c)) <= 5000)

    def test_optional_columns_and_invalid_schema(self):
        result = build_candidates(self.profile, self.tariffs[["tariff_plan_code"]], self.path)
        self.assertEqual(len(result), 2)
        self.path.write_text("wrong\n1\n")
        with self.assertRaisesRegex(ValueError, "History missing columns"):
            build_candidates(self.profile, self.tariffs, self.path)
        with self.assertRaisesRegex(ValueError, "unique"):
            build_candidates(self.profile, pd.concat([self.tariffs] * 2), Path(self.temp.name) / "missing")

    def test_invalid_values_and_tiny_cells_do_not_leak(self):
        bad = self.profile.copy()
        bad.loc[0, "predicted_arpu"] = np.inf
        self.assertEqual(build_candidates(bad, self.tariffs, self.path), [])
        self.assertEqual(build_candidates(self.profile.iloc[:9], self.tariffs, self.path), [])
        self.assertEqual(build_candidates(self.profile.iloc[:0], self.tariffs, self.path), [])

    def test_real_data_contract_determinism_and_no_mutation(self):
        profile = pd.read_csv(ROOT / "customer_profile.csv")
        tariffs = pd.read_csv(ROOT / "data/dict_tariff.csv")
        before, catalogue = profile.copy(deep=True), tariffs.copy(deep=True)
        first = build_candidates(profile, tariffs)
        self.assertEqual(first, build_candidates(profile, tariffs))
        self.assertEqual(first, build_candidates(profile.sample(frac=1, random_state=11),
                                                  tariffs.sample(frac=1, random_state=12)))
        pd.testing.assert_frame_equal(profile, before)
        pd.testing.assert_frame_equal(tariffs, catalogue)
        json.dumps(first, allow_nan=False)
        self.assertTrue(first)
        filters = []
        for c in first:
            self.assertIn(c["target_tariff"], set(tariffs.tariff_plan_code))
            self.assertNotEqual(c["target_tariff"], c["filter_current_tariff"])
            self.assertTrue(10 <= len(select_segment(profile, c)) <= 5000)
            self.assertEqual(set(c) - {"prior_lift_ratio", "history_support", "priority", "target_tariff"},
                             {k for k in c if k in ("filter_current_tariff", "filter_arpu_segment",
                                                    "filter_data_segment", "filter_call_segment")})
            filters.append(tuple(sorted((k, v) for k, v in c.items() if k.startswith("filter_"))))
        self.assertEqual(len(set(filters[:12])), 12)


if __name__ == "__main__":
    unittest.main()
