"""Public-API boundary checks independent of organizer mock effects."""
import unittest

import numpy as np
import pandas as pd
from unittest.mock import patch

from strategy.planner import plan_campaigns, select_segment
from strategy.test_planner import CANDIDATES, SyntheticEnv


class StressTests(unittest.TestCase):
    @patch('strategy.planner.build_candidates', return_value=CANDIDATES)
    def test_free_channel_remains_usable_with_no_money(self, _):
        env = SyntheticEnv({('b', 'sms'): .3, ('b', 'push'): .2},
                           channels={'sms': {'cost_per_contact': 4}, 'push': {'cost_per_contact': 0}},
                           count=100)
        env.remaining_budget = 0
        campaigns = plan_campaigns(env)
        self.assertTrue(env.pilot_history)
        self.assertEqual(len(campaigns), 1)
        self.assertEqual(campaigns[0]['channel'], 'push')
        self.assertEqual(env.remaining_budget, 0)

    @patch('strategy.planner.build_candidates', return_value=CANDIDATES)
    def test_low_resources_reserve_minimum_legal_pilot_and_final(self, _):
        env = SyntheticEnv({('b', 'sms'): .3}, count=100)
        env.remaining_contacts = 110
        env.remaining_budget = 440
        campaigns = plan_campaigns(env)
        self.assertEqual(len(env.pilot_history), 1)
        self.assertEqual(env.pilot_history[0]['n_customers'], 10)
        self.assertEqual(len(campaigns), 1)
        self.assertEqual(env.remaining_contacts, 100)
        self.assertEqual(env.remaining_budget, 400)

    def test_seeded_noisy_scenarios_preserve_public_limits(self):
        # Noise scale and effects are deliberately independent of the organizer
        # environment; these scenarios test invariants, not a predicted score.
        channels = {'push': {'cost_per_contact': 0, 'conversion_multiplier': .5},
                    'sms': {'cost_per_contact': 4, 'conversion_multiplier': .65},
                    'digital_ads': {'cost_per_contact': 22, 'conversion_multiplier': .85},
                    'call': {'cost_per_contact': 160, 'conversion_multiplier': 1.2}}
        candidates = [{'filter_current_tariff': cell, 'target_tariff': target}
                      for target in ('b', 'c') for cell in ('a0', 'a1')]
        for seed in range(12):
            with self.subTest(seed=seed):
                rng = np.random.default_rng(seed)
                effects = {(target, channel): ratio * channels[channel]['conversion_multiplier']
                           for target, ratio in [('b', -.15 if seed % 2 else .25), ('c', .12)]
                           for channel in channels}
                env = SyntheticEnv(effects, channels=channels, count=600)
                env.customer_profile['current_tariff'] = ['a0'] * 300 + ['a1'] * 300
                env.tariffs = pd.DataFrame({'tariff_plan_code': ['a0', 'a1', 'b', 'c']})
                budget = env.remaining_budget = [0, 3000, 100000][seed % 3]
                contacts = env.remaining_contacts = [800, 1500, 15000][seed % 3]
                original_pilot = env.run_pilot
                def noisy_pilot(**kwargs):
                    self.assertLessEqual(kwargs['n_customers'],
                                         len(select_segment(env.customer_profile, kwargs)))
                    result = original_pilot(**kwargs)
                    result['observed_lift_ratio'] += float(rng.normal(0, 1.5 / np.sqrt(result['n_customers'])))
                    return result
                env.run_pilot = noisy_pilot
                with patch('strategy.planner.build_candidates', return_value=candidates):
                    campaigns = plan_campaigns(env)
                self.assertTrue(1 <= len(campaigns) <= 10)
                self.assertTrue(1 <= len(env.pilot_history) <= 20)
                final_contacts = final_cost = 0
                measured = {(p['target_tariff'], p['channel']) for p in env.pilot_history}
                for campaign in campaigns:
                    self.assertIn((campaign['target_tariff'], campaign['channel']), measured)
                    n = len(select_segment(env.customer_profile, campaign))
                    self.assertTrue(1 <= n <= 5000)
                    final_contacts += n
                    final_cost += n * channels[campaign['channel']]['cost_per_contact']
                self.assertLessEqual(final_contacts, env.remaining_contacts)
                self.assertLessEqual(final_cost, env.remaining_budget)
                self.assertLessEqual(contacts - env.remaining_contacts + final_contacts, contacts)
                self.assertLessEqual(budget - env.remaining_budget + final_cost, budget)

    @patch('strategy.planner.build_candidates', return_value=CANDIDATES)
    def test_extremely_negative_series_still_returns_one_feasible_campaign(self, _):
        env = SyntheticEnv({('b', 'sms'): -1.5})
        campaigns = plan_campaigns(env)
        self.assertEqual(len(campaigns), 1)
        self.assertGreater(len(env.pilot_history), 0)
        segment = select_segment(env.customer_profile, campaigns[0])
        self.assertLessEqual(len(segment), env.remaining_contacts)
        self.assertLessEqual(len(segment) * 4, env.remaining_budget)


if __name__ == '__main__':
    unittest.main()
