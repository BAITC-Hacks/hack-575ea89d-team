"""Independent planner checks: no organizer model or local-effect assumptions."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from strategy.planner import Arm, allocate, plan_campaigns


class SyntheticEnv:
    def __init__(self, effects, channels=None, count=1000):
        self.customer_profile = pd.DataFrame({
            "ID_NUMBER": range(count), "current_tariff": ["a"] * count,
            "arpu_segment": ["MID"] * count, "predicted_arpu": [2000.] * count,
        })
        self.tariffs = pd.DataFrame({"tariff_plan_code": ["a", "b", "c"]})
        self.channels = channels or {"sms": {"cost_per_contact": 4}}
        self.remaining_budget, self.remaining_contacts, self.pilots_left = 100000, 15000, 20
        self.pilot_history, self.effects = [], effects

    def run_pilot(self, target_tariff, channel, n_customers, **filters):
        assert 10 <= n_customers <= 200
        cost = n_customers * self.channels[channel]["cost_per_contact"]
        assert cost <= self.remaining_budget and n_customers <= self.remaining_contacts
        self.remaining_budget -= cost
        self.remaining_contacts -= n_customers
        self.pilots_left -= 1
        ratio = self.effects[(target_tariff, channel)]
        row = dict(target_tariff=target_tariff, channel=channel,
                   observed_lift_ratio=ratio, n_customers=n_customers)
        self.pilot_history.append(row)
        return row


CANDIDATES = [{"filter_current_tariff": "a", "target_tariff": "b"}]


class PlannerTests(unittest.TestCase):
    @patch("strategy.planner.build_candidates", return_value=CANDIDATES)
    def test_ambiguous_effect_gets_rechecked_clear_effect_stops(self, _):
        clear = SyntheticEnv({("b", "sms"): 0.6})
        uncertain = SyntheticEnv({("b", "sms"): 0.02})
        plan_campaigns(clear)
        plan_campaigns(uncertain)
        self.assertEqual(len(clear.pilot_history), 1)
        self.assertGreater(len(uncertain.pilot_history), 1)
        self.assertLessEqual(len(uncertain.pilot_history), 20)
        self.assertLessEqual(sum(p['n_customers'] for p in uncertain.pilot_history), 3000)

    @patch("strategy.planner.build_candidates", return_value=CANDIDATES)
    def test_channel_choice_requires_observation_and_changes_with_it(self, _):
        channels = {"sms": {"cost_per_contact": 4, "conversion_multiplier": .65},
                    "digital_ads": {"cost_per_contact": 22, "conversion_multiplier": .85}}
        for digital, expected in [(0.9, "digital_ads"), (-0.5, "sms")]:
            env = SyntheticEnv({("b", "sms"): .4, ("b", "digital_ads"): digital}, channels)
            campaigns = plan_campaigns(env)
            self.assertEqual(campaigns[0]["channel"], expected)
            self.assertTrue(any(p['channel'] == expected for p in env.pilot_history))
            self.assertGreaterEqual(env.remaining_budget - sum(1000 * channels[c['channel']]['cost_per_contact']
                                                               for c in campaigns), 0)

    def test_overlap_is_charged_and_only_marginal_lift_counts(self):
        def arm(start, end, ratio, cost):
            return Arm({"target_tariff": str(ratio), "channel": "sms"},
                       np.arange(start, end), np.full(end - start, 1000.), cost, [(10, ratio)])
        first = arm(0, 100, .8, 4)
        duplicate = arm(0, 100, .7, 4)
        disjoint = arm(100, 200, .7, 4)
        selected, _ = allocate([first, duplicate, disjoint], 200, 800, 200)
        self.assertEqual(len(selected), 2)
        self.assertTrue(any(a is first for a in selected))
        self.assertTrue(any(a is disjoint for a in selected))
        self.assertFalse(any(a is duplicate for a in selected))

    def test_portfolio_respects_both_resources_and_campaign_count(self):
        arms = [Arm({"target_tariff": str(i), "channel": "sms"}, np.arange(i * 100, (i + 1) * 100),
                    np.full(100, 1000.), 22 if i % 2 else 4, [(10, .8)]) for i in range(15)]
        selected, _ = allocate(arms, 1500, 5000, 750)
        self.assertLessEqual(len(selected), 10)
        self.assertLessEqual(sum(a.size for a in selected), 750)
        self.assertLessEqual(sum(a.size * a.cost for a in selected), 5000)

    @patch("strategy.planner.build_candidates", return_value=CANDIDATES)
    def test_exhausted_pilot_api_stops_without_unbounded_retries(self, _):
        env = SyntheticEnv({("b", "sms"): .5})
        with patch.object(env, 'run_pilot', side_effect=RuntimeError('unavailable')) as pilot:
            self.assertEqual(plan_campaigns(env), [])
            self.assertLessEqual(pilot.call_count, 20)


if __name__ == '__main__':
    unittest.main()
