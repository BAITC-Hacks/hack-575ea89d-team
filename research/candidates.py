"""Historical observations rank hypotheses; they do not reveal hidden effects.

The history contains switchers only. Its counts are not campaign conversion
rates. Priors here are only used to decide which pilots to run.
"""
from pathlib import Path
import pandas as pd


def build_candidates(profile, tariffs, history_path=None) -> list[dict]:
    path = Path(history_path) if history_path else Path(__file__).resolve().parents[1] / "data/change_tariff.csv"
    history = pd.read_csv(path)
    history = history[history.AVG_ARPU_PREV_3M >= 100].copy()
    history["arpu_segment"] = pd.cut(
        history.AVG_ARPU_PREV_3M, [-float("inf"), 1000, 5000, float("inf")],
        labels=["LOW", "MID", "HIGH"], right=False,
    )
    history["change"] = (history.AVG_ARPU_NEXT_3M / history.AVG_ARPU_PREV_3M - 1).clip(-1, 3)
    prior = history.groupby(
        ["tariff_plan_code_from", "arpu_segment", "tariff_plan_code_to"], observed=True
    )["change"].agg(["mean", "count"])
    known = sorted(tariffs.tariff_plan_code.astype(str))
    cells = []
    for (current, segment), group in profile.groupby(["current_tariff", "arpu_segment"], observed=True):
        # Laptop 2 can later split larger cells using supported filters.
        if len(group) < 10 or len(group) > 5000:
            continue
        options = []
        for target in known:
            if target == current:
                continue
            key = (current, segment, target)
            mean, support = (float(prior.loc[key, "mean"]), int(prior.loc[key, "count"])) if key in prior.index else (0.0, 0)
            shrunk = mean * support / (support + 20)
            options.append({
                "filter_current_tariff": str(current), "filter_arpu_segment": str(segment),
                "target_tariff": target, "prior_lift_ratio": shrunk, "history_support": support,
                "priority": max(shrunk, 0.0) * float(group.predicted_arpu.sum()),
            })
        options.sort(key=lambda c: (-c["priority"], -c["history_support"], c["target_tariff"]))
        if options:
            cells.append(options)
    cells.sort(key=lambda options: (-options[0]["priority"], options[0]["filter_current_tariff"], options[0]["filter_arpu_segment"]))
    return [options[rank] for rank in range(2) for options in cells if len(options) > rank]
