import hashlib
import json
from pathlib import Path
import unittest

import pandas as pd

from agent import Agent
from make_submission import build_submission
from mock_environment import make_mock_env
from scoring_core import validate_strategy
from strategy.planner import select_segment
from tools.report import build_report, json_safe

ROOT = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    def test_original_materials_unchanged(self):
        manifest = json.loads((ROOT / "docs/organizer_manifest.json").read_text())
        for path, expected in manifest.items():
            with self.subTest(path=path):
                self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), expected)

    def test_campaigns_and_all_contacts_fit(self):
        for seed in (0, 9, 42):
            with self.subTest(seed=seed):
                env, _ = make_mock_env(seed=seed)
                campaigns = Agent().act(env)
                self.assertTrue(1 <= len(campaigns) <= 10)
                self.assertTrue(1 <= len(env.pilot_history) <= 20)
                validate_strategy(pd.DataFrame(campaigns), env.tariffs)
                contacts = sum(p["n_customers"] for p in env.pilot_history)
                cost = sum(p["cost"] for p in env.pilot_history)
                ids = set()
                for pilot in env.pilot_history:
                    self.assertTrue(10 <= pilot["n_customers"] <= 200)
                for campaign in campaigns:
                    segment = select_segment(env.customer_profile, campaign)
                    self.assertTrue(1 <= len(segment) <= 5000)
                    current_ids = set(segment.ID_NUMBER)
                    self.assertFalse(ids & current_ids)
                    ids |= current_ids
                    contacts += len(segment)
                    cost += len(segment) * env.channels[campaign["channel"]]["cost_per_contact"]
                self.assertLessEqual(contacts, 15000)
                self.assertLessEqual(cost, 100000)

    def test_submission_reproducible_and_matches_file(self):
        first = build_submission(Agent()).to_csv(index=False)
        second = build_submission(Agent()).to_csv(index=False)
        self.assertEqual(first, second)
        self.assertEqual(first, (ROOT / "submission.csv").read_text())

    def test_report_matches_real_evaluator(self):
        report = build_report(seed=42)
        self.assertEqual(report["mode"], "mock")
        self.assertEqual(report["metrics"]["n_pilots"], len(report["pilot_history"]))
        self.assertEqual(report["metrics"]["n_campaigns"],
                         len(report["final_campaigns"]) + len(report["pilot_history"]))
        self.assertAlmostEqual(report["metrics"]["net_arpu_gain"],
                               report["metrics"]["gross_arpu_lift"] - report["metrics"]["total_cost"])
        json.dumps(report, allow_nan=False)

    def test_nonfinite_metrics_are_json_null(self):
        self.assertEqual(json_safe({"roi": float("inf"), "missing": float("nan")}),
                         {"roi": None, "missing": None})


if __name__ == "__main__":
    unittest.main()
