"""Public observations drive bounded exploration and overlap-aware allocation.

History orders hypotheses only. No local evaluator or hidden model is used here.
"""
import math
from dataclasses import dataclass, field

import numpy as np

from research.candidates import build_candidates

FILTERS = ("filter_current_tariff", "filter_arpu_segment", "filter_data_segment", "filter_call_segment")


def select_segment(profile, campaign):
    result = profile
    for key in FILTERS:
        value = campaign.get(key)
        if value is None or (isinstance(value, float) and math.isnan(value)):
            continue
        column = key.removeprefix("filter_")
        if key == "filter_current_tariff":
            result = result[result[column].isin([v.strip() for v in str(value).split(";")])]
        else:
            result = result[result[column] == value]
    return result.sort_values("ID_NUMBER")


@dataclass
class Arm:
    campaign: dict
    positions: np.ndarray
    arpu: np.ndarray
    cost: float
    samples: list = field(default_factory=list)

    @property
    def size(self):
        return len(self.positions)

    @property
    def n(self):
        return sum(n for n, _ in self.samples)

    @property
    def mean(self):
        return sum(n * r for n, r in self.samples) / self.n if self.n else 0.0

    @property
    def error(self):
        # Conservative unit-scale working noise model, not a calibrated CI.
        # Repeated observations may increase, but never decrease, this floor.
        variance = 1.0
        if len(self.samples) > 1:
            variance = max(variance, sum(n * (r - self.mean) ** 2 for n, r in self.samples)
                           / (len(self.samples) - 1))
        return math.sqrt(variance / self.n) if self.n else float("inf")

    @property
    def decision_ratio(self):
        # Weak neutral shrinkage for expected-net allocation. Confidence bounds
        # guide further measurement, not a significance gate that discards
        # all moderately positive but noisy opportunities.
        return self.mean * self.n / (self.n + 20)

    @property
    def lower(self):
        return self.mean - self.error


def pilot_credit(arms, count):
    """Upper approximation to already earned positive lift, with unknown IDs.

    Public pilot results do not expose sampled IDs. Summing expected coverage
    credits (capped at the best observed ratio) is deliberately conservative
    for overlapping/repeated pilots; it is not an exact deduplication model.
    """
    credit, ceiling = np.zeros(count), np.zeros(count)
    for arm in arms:
        if not arm.n:
            continue
        ratio = max(0.0, arm.mean)
        credit[arm.positions] += ratio * min(1.0, arm.n / arm.size)
        ceiling[arm.positions] = np.maximum(ceiling[arm.positions], ratio)
    return np.minimum(credit, ceiling)


def allocate(arms, count, budget, contacts):
    """Compare deterministic greedy packings using marginal net value.

    Full audiences consume contacts/cost, even when overlapping. Only the
    improvement over prior contacts contributes value. Several resource prices
    avoid a single expensive arm crowding out multiple better combinations.
    """
    credit = pilot_credit(arms, count)
    tested = [a for a in arms if a.n and a.size <= min(5000, contacts)
              and a.size * a.cost <= budget]
    best, best_value = [], -float("inf")
    for penalty in (0.0, 0.5, 1.0, 2.0):
        chosen, covered, left_budget, left_contacts = [], credit.copy(), budget, contacts
        value = 0.0
        while len(chosen) < 10:
            options = []
            for index, arm in enumerate(tested):
                if index in chosen or arm.size > left_contacts or arm.size * arm.cost > left_budget:
                    continue
                gain = float((np.maximum(0.0, arm.decision_ratio - covered[arm.positions]) * arm.arpu).sum()) - arm.size * arm.cost
                if gain <= 0 or arm.decision_ratio <= 0:
                    continue
                resource = arm.size / max(1, contacts) + arm.size * arm.cost / max(1, budget)
                options.append((gain / (1.0 + penalty * resource * 10), -index, gain))
            if not options:
                break
            _, minus_index, gain = max(options)
            index = -minus_index
            arm = tested[index]
            chosen.append(index)
            value += gain
            covered[arm.positions] = np.maximum(covered[arm.positions], arm.decision_ratio)
            left_budget -= arm.size * arm.cost
            left_contacts -= arm.size
        if value > best_value:
            best, best_value = [tested[i] for i in chosen], value
    if not best and tested:
        # Required >=1 campaign: least estimated loss among feasible tested arms.
        # A negative series can still lose money; there is no guaranteed profit.
        best = [max(tested, key=lambda a: float((a.mean * a.arpu).sum()) - a.size * a.cost)]
    return best, max(0.0, best_value)


def plan_campaigns(env) -> list[dict]:
    profile = env.customer_profile.reset_index(drop=True)
    candidates = build_candidates(env.customer_profile, env.tariffs)
    channels = sorted(env.channels, key=lambda c: (float(env.channels[c]["cost_per_contact"]), c))
    if not channels:
        return []
    initial_channel = "sms" if "sms" in channels else channels[0]
    arms, hypotheses, seen = [], [], set()
    for candidate in candidates:
        campaign = {key: candidate[key] for key in FILTERS if candidate.get(key) is not None}
        campaign["target_tariff"] = candidate["target_tariff"]
        signature = tuple(str(campaign.get(k)) for k in (*FILTERS, "target_tariff"))
        if signature in seen:
            continue
        seen.add(signature)
        segment = select_segment(profile, campaign)
        if not 10 <= len(segment) <= 5000:
            continue
        hypotheses.append((campaign, segment.index.to_numpy(), segment.predicted_arpu.to_numpy(dtype=float)))

    def make_arm(hypothesis, channel):
        campaign, positions, arpu = hypothesis
        return Arm({**campaign, "channel": channel}, positions, arpu,
                   float(env.channels[channel]["cost_per_contact"]))

    initial_budget, initial_contacts = float(env.remaining_budget), int(env.remaining_contacts)
    exploration_budget = initial_budget * 0.20
    exploration_contacts = min(3000, int(initial_contacts * 0.20))
    attempts, next_hypothesis = 0, 0

    def sample(arm, requested, selected):
        nonlocal attempts
        spent = initial_budget - env.remaining_budget
        used = initial_contacts - env.remaining_contacts
        # Preserve the current complete plan, or at least the tested campaign.
        reserve_contacts = sum(a.size for a in selected) if selected else arm.size
        reserve_budget = sum(a.size * a.cost for a in selected) if selected else arm.size * arm.cost
        available = min(env.remaining_contacts - reserve_contacts,
                        exploration_contacts - used, arm.size, requested, 200)
        if arm.cost:
            available = min(available, (env.remaining_budget - reserve_budget) // arm.cost,
                            (exploration_budget - spent) // arm.cost)
        # On a tiny residual environment, allow one initial pilot and one final
        # campaign instead of enforcing the discretionary 20% envelope.
        if not arms:
            available = min(requested, arm.size, 200, env.remaining_contacts - arm.size)
            if arm.cost:
                available = min(available, (env.remaining_budget - arm.size * arm.cost) // arm.cost)
        n = int(available)
        if n < 10:
            return False
        attempts += 1
        try:
            result = env.run_pilot(n_customers=n, **arm.campaign)
        except RuntimeError:
            return False
        ratio, actual = float(result["observed_lift_ratio"]), int(result["n_customers"])
        if actual > 0 and math.isfinite(ratio):
            arm.samples.append((actual, ratio))
            if not any(a is arm for a in arms):
                arms.append(arm)
        return True

    typical_value = float(np.median([h[2].sum() for h in hypotheses[:12]])) if hypotheses else 1.0
    typical_value = max(1.0, typical_value)
    # Initial coverage of diverse hypotheses, in the research module's order.
    # More ARPU at stake warrants better precision; sample size is bounded.
    while next_hypothesis < min(12, len(hypotheses)) and env.pilots_left > 0 and attempts < 20:
        arm = make_arm(hypotheses[next_hypothesis], initial_channel)
        next_hypothesis += 1
        selected, _ = allocate(arms, len(profile), env.remaining_budget, env.remaining_contacts)
        sample(arm, min(200, max(80, int(80 * math.sqrt(float(arm.arpu.sum()) / typical_value)))), selected)

    while env.pilots_left > 0 and attempts < 20 and arms:
        selected, value = allocate(arms, len(profile), env.remaining_budget, env.remaining_contacts)
        actions = []
        # If a segment's first offer is unconvincing, investigate the next
        # research hypothesis for that same audience before abandoning it.
        # Typical measured lift is only an exploration scale, not a predicted
        # effect of the untested tariff; a direct pilot is always required.
        typical_lift = float(np.median([max(0.0, a.mean) for a in arms]))
        for hypothesis in hypotheses[next_hypothesis:]:
            proposal = make_arm(hypothesis, initial_channel)
            if any(a.campaign == proposal.campaign for a in arms):
                continue
            same_audience = [a for a in arms if np.array_equal(a.positions, proposal.positions)]
            if not same_audience or any(a.lower > 0 for a in same_audience):
                continue
            incumbent = max(0.0, max(a.decision_ratio for a in same_audience))
            uncertainty = min(a.error for a in same_audience)
            score = (typical_lift + uncertainty - incumbent) * float(proposal.arpu.sum())
            score -= proposal.size * proposal.cost
            actions.append((score, "alternative", proposal, 80))
        for arm in list(arms):
            others = [a for a in arms if a is not arm and a.n
                      and np.array_equal(a.positions, arm.positions)]
            competitor = max([0.0] + [a.lower - a.cost / max(1.0, float(a.arpu.mean())) for a in others])
            net_upper = arm.mean + arm.error - arm.cost / max(1.0, float(arm.arpu.mean()))
            net_lower = arm.lower - arm.cost / max(1.0, float(arm.arpu.mean()))
            if arm.n < 400 and net_lower <= competitor < net_upper:
                # Resolve sign or close alternatives; clear losers are retired.
                reduction = 1.0 - math.sqrt(arm.n / (arm.n + min(200, max(80, arm.n))))
                score = min(2 * arm.error, net_upper - competitor) * reduction * float(arm.arpu.sum())
                actions.append((score, "repeat", arm, min(200, max(80, arm.n))))
            if arm.lower <= 0:
                continue
            for channel in channels:
                if any(a.campaign == {**arm.campaign, "channel": channel} for a in arms):
                    continue
                other = Arm({**arm.campaign, "channel": channel}, arm.positions, arm.arpu,
                            float(env.channels[channel]["cost_per_contact"]))
                if other.size * other.cost > env.remaining_budget:
                    continue
                source_multiplier = env.channels[arm.campaign["channel"]].get("conversion_multiplier", 1.0)
                target_multiplier = env.channels[channel].get("conversion_multiplier", 1.0)
                factor = target_multiplier / max(float(source_multiplier), 1e-9)
                # Saturation means multiplier ratios are only optimistic bounds.
                # Final decisions always require a direct pilot of this channel.
                optimistic = max(1.0, factor) * (arm.mean + arm.error)
                incumbent = max([0.0] + [a.lower - a.cost / max(1.0, float(a.arpu.mean()))
                                        for a in [arm, *others]])
                score = (optimistic - incumbent) * float(arm.arpu.sum()) - other.size * other.cost
                actions.append((score, "channel", other, 80))
        performed = False
        for score, kind, arm, n in sorted(actions, key=lambda a: -a[0]):
            # Stop when plausible decision improvement is below the information
            # purchase plus 1% of the current conservative portfolio value.
            opportunity = n * (arm.cost + value / max(1, env.remaining_contacts))
            if score <= max(0.01 * value, opportunity):
                continue
            if sample(arm, n, selected):
                performed = True
                break
        if not performed:
            break
    selected, _ = allocate(arms, len(profile), env.remaining_budget, env.remaining_contacts)
    return [{"campaign_name": f"adaptive_{i + 1}", **arm.campaign} for i, arm in enumerate(selected)]
