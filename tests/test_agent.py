import unittest
from unittest.mock import patch

import pandas as pd

from strategy.planner import plan_campaigns


class PilotEnv:
    def __init__(self, effects, budget=100000, contacts=15000):
        self.customer_profile = pd.DataFrame({
            "ID_NUMBER": range(20), "current_tariff": ["tariff_1"] * 20,
            "arpu_segment": ["MID"] * 20, "predicted_arpu": [2000.0] * 20,
        })
        self.tariffs = pd.DataFrame({"tariff_plan_code": ["tariff_1", "tariff_2", "tariff_3"]})
        self.channels = {"sms": {"cost_per_contact": 4}}
        self.remaining_budget, self.remaining_contacts, self.pilots_left = budget, contacts, 20
        self.pilot_history, self.effects = [], effects

    def run_pilot(self, target_tariff, channel, n_customers, **filters):
        self.remaining_budget -= n_customers * 4
        self.remaining_contacts -= n_customers
        self.pilots_left -= 1
        result = {"observed_lift_ratio": self.effects[target_tariff], "n_customers": n_customers}
        self.pilot_history.append(result)
        return result


CANDIDATES = [
    {"filter_current_tariff": "tariff_1", "filter_arpu_segment": "MID", "target_tariff": target}
    for target in ("tariff_2", "tariff_3")
]


class AgentTests(unittest.TestCase):
    @patch("strategy.planner.build_candidates", return_value=CANDIDATES)
    def test_pilot_observations_change_choice(self, _):
        a = plan_campaigns(PilotEnv({"tariff_2": 0.8, "tariff_3": -0.2}))
        b = plan_campaigns(PilotEnv({"tariff_2": -0.2, "tariff_3": 0.8}))
        self.assertEqual(a[0]["target_tariff"], "tariff_2")
        self.assertEqual(b[0]["target_tariff"], "tariff_3")

    @patch("strategy.planner.build_candidates", return_value=CANDIDATES)
    def test_negative_pilots_have_explicit_fallback(self, _):
        selected = plan_campaigns(PilotEnv({"tariff_2": -0.8, "tariff_3": -0.1}))
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["target_tariff"], "tariff_3")

    @patch("strategy.planner.build_candidates", return_value=CANDIDATES)
    def test_reserves_resources_for_final_campaign(self, _):
        env = PilotEnv({"tariff_2": 0.8, "tariff_3": 0.9}, budget=160, contacts=40)
        selected = plan_campaigns(env)
        self.assertEqual(len(env.pilot_history), 1)
        self.assertEqual(len(selected), 1)
        self.assertEqual(env.remaining_budget, 80)
        self.assertEqual(env.remaining_contacts, 20)


if __name__ == "__main__":
    unittest.main()
