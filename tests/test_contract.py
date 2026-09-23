import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import unittest

import pandas as pd

from agent import Agent
from make_submission import build_submission
from mock_environment import make_mock_env
from scoring_core import score_campaigns, validate_strategy
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
                    ids.update(segment.ID_NUMBER)
                    contacts += len(segment)
                    cost += len(segment) * env.channels[campaign["channel"]]["cost_per_contact"]
                self.assertLessEqual(contacts, 15000)
                self.assertLessEqual(cost, 100000)
                # Repeated audiences are allowed; each campaign's contacts still count.
                self.assertLessEqual(len(ids), contacts)

    def test_submission_reproducible_and_matches_file(self):
        first = build_submission(Agent()).to_csv(index=False, lineterminator="\n").encode("utf-8")
        second = build_submission(Agent()).to_csv(index=False, lineterminator="\n").encode("utf-8")
        # Reproducibility is a byte-for-byte property of two generations here.
        self.assertEqual(first, second)
        # read_text() uses universal newline translation, so compare against the
        # same canonical LF serialization independent of a CRLF checkout.
        checked_in = (ROOT / "submission.csv").read_text(encoding="utf-8")
        self.assertEqual(first.decode("utf-8"), checked_in)

    def test_official_scorer_charges_overlapping_contacts_but_deduplicates_lift(self):
        profile = pd.DataFrame({
            "ID_NUMBER": [1, 2], "current_tariff": ["tariff_1"] * 2,
            "arpu_segment": ["MID"] * 2, "predicted_arpu": [1000.0] * 2,
        })
        tariffs = pd.DataFrame({"tariff_plan_code": ["tariff_1", "tariff_2"]})
        impact = pd.DataFrame({
            "tariff_plan_code_from": ["tariff_1"], "tariff_plan_code_to": ["tariff_2"],
            "arpu_segment": ["MID"], "arpu_change_pct": [0.5], "conversion_rate": [1.0],
        })
        campaign = {
            "filter_current_tariff": "tariff_1", "filter_arpu_segment": "MID",
            "target_tariff": "tariff_2", "channel": "sms",
        }
        plan = pd.DataFrame([
            {"campaign_name": "first", **campaign},
            {"campaign_name": "repeat", **campaign},
        ])

        result = score_campaigns(
            plan, profile, impact, tariffs, baseline_total_arpu=2000.0,
            fallback_predict=lambda *_: (0.0, 1.0),
        )

        # Both two-person contacts are charged (4 contacts x 4 units), but each
        # subscriber contributes only their best 325-unit lift once.
        self.assertEqual([row["n_contacts"] for row in result["campaigns_detail"]], [2, 2])
        self.assertEqual(result["total_contacts"], 4)
        self.assertEqual(result["total_cost"], 16)
        self.assertEqual(result["unique_customers_targeted"], 2)
        self.assertAlmostEqual(result["gross_arpu_lift"], 650.0)
        self.assertAlmostEqual(result["net_arpu_gain"], 634.0)

    @unittest.skipUnless(shutil.which("node"), "Node.js is optional; run demo/app.test.js when available")
    def test_demo_report_loading_and_error_states(self):
        result = subprocess.run(
            ["node", "demo/app.test.js"], cwd=ROOT,
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("pass 5", result.stdout)

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
