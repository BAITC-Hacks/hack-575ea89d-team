"""Adversarial allocation tests independent of mock tariff effects."""
import unittest

import numpy as np

from strategy.planner import Arm, allocate, pilot_credit
from strategy.portfolio import refine_portfolio


def arm(name, start, end, ratio, cost=0):
    return Arm({'target_tariff': name, 'channel': 'push' if cost == 0 else 'sms'},
               np.arange(start, end), np.full(end - start, 1000.), cost, [(10, ratio)])


def names(selected):
    return [a.campaign['target_tariff'] for a in selected]


class PortfolioTests(unittest.TestCase):
    def test_two_smaller_campaigns_escape_greedy_contact_trap(self):
        arms = [arm('large', 0, 600, .06), arm('small_a', 600, 1100, .0594),
                arm('small_b', 1100, 1600, .0594)]
        selected, _ = allocate(arms, 1600, 100000, 1000)
        self.assertEqual(names(selected), ['large'])
        improved = refine_portfolio(arms, selected, 1600, 100000, 1000, pilot_credit(arms, 1600))
        self.assertEqual(set(names(improved)), {'small_a', 'small_b'})
        self.assertEqual(sum(a.size for a in improved), 1000)

    def test_redundant_paid_contact_is_removed(self):
        low = arm('low', 0, 100, .6, 4)
        high = arm('high', 0, 100, .9, 4)
        arms = [low, high]
        improved = refine_portfolio(arms, arms, 100, 1000, 300, pilot_credit(arms, 100))
        self.assertEqual(names(improved), ['high'])

    def test_overlap_does_not_fabricate_value_for_a_duplicate(self):
        chosen = arm('chosen', 0, 100, .9, 4)
        duplicate = arm('duplicate', 0, 100, .9, 4)
        separate = arm('separate', 100, 200, .8, 4)
        arms = [chosen, duplicate, separate]
        improved = refine_portfolio(arms, [chosen], 200, 800, 200, pilot_credit(arms, 200))
        self.assertEqual(set(names(improved)), {'chosen', 'separate'})
        self.assertEqual(sum(a.size * a.cost for a in improved), 800)

    def test_expensive_replacement_cannot_exceed_budget(self):
        low = arm('low', 0, 100, .6, 4)
        expensive = arm('expensive', 0, 100, 5., 160)
        improved = refine_portfolio([low, expensive], [low], 100, 400, 100, np.zeros(100))
        self.assertEqual(names(improved), ['low'])

    def test_full_ten_slots_can_replace_a_weaker_campaign(self):
        arms = [arm(str(i), i * 100, (i + 1) * 100, .3) for i in range(10)]
        stronger = arm('stronger', 1000, 1100, .9)
        improved = refine_portfolio(arms + [stronger], arms, 1100, 1000, 1000, np.zeros(1100))
        self.assertEqual(len(improved), 10)
        self.assertIn('stronger', names(improved))
        self.assertEqual(names(improved)[0], 'stronger')

    def test_negative_mandatory_fallback_is_preserved(self):
        negative = arm('negative', 0, 100, -.5, 4)
        selected = [negative]
        self.assertIs(refine_portfolio(selected, selected, 100, 400, 100, np.zeros(100)), selected)

    def test_equal_value_keeps_original_choice(self):
        a, b = arm('a', 0, 100, .5), arm('b', 100, 200, .5)
        for _ in range(2):
            result = refine_portfolio([a, b], [a], 200, 1000, 100, np.zeros(200))
            self.assertEqual(names(result), ['a'])


if __name__ == '__main__':
    unittest.main()
