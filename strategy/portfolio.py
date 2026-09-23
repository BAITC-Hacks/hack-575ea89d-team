"""Bounded local improvement of a measured final campaign portfolio.

Only public pilot estimates are passed here. This is an expected-net objective,
not a call to the organizer's evaluator and not a promise of optimal profit.
"""
from itertools import combinations

import numpy as np


def refine_portfolio(arms, selected, count, budget, contacts, credit, max_passes=2):
    """Try removal, insertion and one-for-one/one-for-two swaps, charging every contact.

    A greedy choice can consume a slot or budget needed by a better combination.
    Evaluate each change against the *whole* portfolio, deduplicating customer
    benefit by maximum effect. Accept only strict improvements, so ties retain
    the previous deterministic plan. At most two passes run after exploration.
    """
    candidates = [a for a in arms if a.n and a.decision_ratio > 0
                  and a.size <= min(5000, contacts) and a.size * a.cost <= budget]
    lookup = {id(a): i for i, a in enumerate(candidates)}
    if not selected or any(id(a) not in lookup for a in selected):
        # Preserve the mandatory least-loss fallback, including negative effects.
        return selected
    current = tuple(lookup[id(a)] for a in selected)
    values = np.zeros(count)
    lifts = np.zeros((len(candidates), count))
    for i, arm in enumerate(candidates):
        values[arm.positions] = arm.arpu
        lifts[i, arm.positions] = arm.decision_ratio * arm.arpu
    earned = credit * values
    costs = np.array([a.size * a.cost for a in candidates])
    sizes = np.array([a.size for a in candidates])

    def objective(indices):
        if not 1 <= len(indices) <= 10:
            return -float('inf')
        indices = list(indices)
        total_cost = float(costs[indices].sum())
        if total_cost > budget or sizes[indices].sum() > contacts:
            return -float('inf')
        gain = np.maximum(0.0, lifts[indices].max(axis=0) - earned).sum()
        return float(gain) - total_cost

    score = objective(current)
    if not np.isfinite(score):
        return selected
    for _ in range(max_passes):
        best, best_score = current, score
        remaining = [i for i in range(len(candidates)) if i not in current]
        alternatives = [current + (i,) for i in remaining] if len(current) < 10 else []
        for position in range(len(current)):
            without = current[:position] + current[position + 1:]
            alternatives.append(without)
            alternatives.extend(without + (i,) for i in remaining)
            if len(without) <= 8:
                alternatives.extend(without + pair for pair in combinations(remaining, 2))
        for proposal in alternatives:
            candidate_score = objective(proposal)
            if candidate_score > best_score + 1e-9 * max(1.0, abs(best_score)):
                best, best_score = proposal, candidate_score
        if best == current:
            break
        current, score = best, best_score

    # Put the largest marginal gains first without altering the chosen set.
    # Full resources already fit; this also makes the campaign order legible.
    ordered, covered = [], earned.copy()
    pending = list(current)
    while pending:
        index = max(pending, key=lambda i: (
            float(np.maximum(0.0, lifts[i] - covered).sum()) - costs[i], -i))
        ordered.append(candidates[index])
        covered = np.maximum(covered, lifts[index])
        pending.remove(index)
    return ordered
