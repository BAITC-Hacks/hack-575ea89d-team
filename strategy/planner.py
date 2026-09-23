"""Starting baseline; multi-channel/adaptive exploration is future work."""
import math
from research.candidates import build_candidates

FILTERS = ("filter_current_tariff", "filter_arpu_segment", "filter_data_segment", "filter_call_segment")


def select_segment(profile, campaign):
    result = profile
    for key in FILTERS:
        value = campaign.get(key)
        if value is None:
            continue
        column = key.removeprefix("filter_")
        if key == "filter_current_tariff":
            result = result[result[column].isin(str(value).split(";"))]
        else:
            result = result[result[column] == value]
    return result.sort_values("ID_NUMBER")


def plan_campaigns(env) -> list[dict]:
    candidates = build_candidates(env.customer_profile, env.tariffs)
    channel = "sms"
    cost = float(env.channels[channel]["cost_per_contact"])
    observations = []
    for candidate in candidates:
        if len(observations) >= 12 or env.pilots_left <= 0:
            break
        filters = {key: candidate[key] for key in FILTERS if candidate.get(key) is not None}
        segment = select_segment(env.customer_profile, filters)
        n = min(150, len(segment))
        if n < 10 or n + len(segment) > env.remaining_contacts:
            continue
        if (n + len(segment)) * cost > env.remaining_budget:
            continue
        try:
            result = env.run_pilot(target_tariff=candidate["target_tariff"], channel=channel,
                                   n_customers=n, **filters)
        except RuntimeError:
            break
        ratio = float(result["observed_lift_ratio"])
        if not math.isfinite(ratio) or result["n_customers"] <= 0:
            continue
        # Heuristic caution margin, not a calibrated confidence interval.
        cautious_ratio = ratio - 1.0 / math.sqrt(result["n_customers"])
        value = float(segment.predicted_arpu.sum())
        observations.append({
            "campaign": {**filters, "target_tariff": candidate["target_tariff"], "channel": channel},
            "segment": segment, "estimate": cautious_ratio * value - len(segment) * cost,
            "observed_net": ratio * value - len(segment) * cost,
        })
    observations.sort(key=lambda o: (-o["estimate"], -o["observed_net"]))
    budget, contacts = env.remaining_budget, env.remaining_contacts
    selected, used_ids = [], set()
    for item in observations:
        segment = item["segment"]
        ids = set(segment.ID_NUMBER)
        if item["estimate"] <= 0 or ids & used_ids:
            continue
        if len(segment) > min(5000, contacts) or len(segment) * cost > budget:
            continue
        selected.append({"campaign_name": f"baseline_{len(selected) + 1}", **item["campaign"]})
        used_ids.update(ids)
        contacts -= len(segment)
        budget -= len(segment) * cost
        if len(selected) == 10:
            break
    # The task requires >=1 final campaign. If every noisy estimate is poor,
    # choose the feasible tested candidate with least observed loss.
    # This is a documented risk, not a guarantee of positive hidden profit.
    if not selected:
        for item in sorted(observations, key=lambda o: -o["observed_net"]):
            n = len(item["segment"])
            if n <= min(5000, contacts) and n * cost <= budget:
                selected.append({"campaign_name": "baseline_fallback", **item["campaign"]})
                break
    return selected
