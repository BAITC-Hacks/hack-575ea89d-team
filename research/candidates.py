"""Deterministic pilot hypotheses from public data, never campaign effects.

Switchers provide no exposure denominator. Median historical change is shrunk
towards zero; package fit adjusts exploration priority, not that estimate.
"""
from pathlib import Path

import numpy as np
import pandas as pd

HISTORY_COLUMNS = ["tariff_plan_code_from", "tariff_plan_code_to",
                   "AVG_ARPU_PREV_3M", "AVG_ARPU_NEXT_3M"]
SEGMENTS = {"arpu_segment": {"LOW", "MID", "HIGH"},
            "data_segment": {"NON_USER", "LITE", "HEAVY"},
            "call_segment": {"LOW", "MEDIUM", "HIGH"}}


def _history(path):
    """Missing/empty history is supported; malformed schemas remain visible."""
    try:
        history = pd.read_csv(path)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        history = pd.DataFrame(columns=HISTORY_COLUMNS)
    missing = set(HISTORY_COLUMNS) - set(history.columns)
    if missing:
        raise ValueError(f"History missing columns: {sorted(missing)}")
    # Only remove provably identical event records when event identifiers exist.
    # Equal ARPU values alone are not evidence of a duplicate observation.
    history = history.drop_duplicates().copy() if {"ID_NUMBER", "TIME_KEY"} <= set(history.columns) else history.copy()
    before = pd.to_numeric(history.AVG_ARPU_PREV_3M, errors="coerce")
    after = pd.to_numeric(history.AVG_ARPU_NEXT_3M, errors="coerce")
    valid = np.isfinite(before) & np.isfinite(after) & (before >= 100) & (after >= 0)
    history = history.loc[valid].copy()
    before, after = before.loc[valid], after.loc[valid]
    # Baseline's left-closed bins: 1000 is MID, 5000 is HIGH.
    history["arpu_segment"] = pd.cut(before, [-np.inf, 1000, 5000, np.inf],
                                     labels=["LOW", "MID", "HIGH"], right=False)
    history["change"] = (after / before - 1).clip(-1, 3)
    return history.groupby(
        ["tariff_plan_code_from", "arpu_segment", "tariff_plan_code_to"], observed=True
    )["change"].agg(["median", "count"])


def _cells(group, filters, dimensions=("data_segment", "call_segment")):
    """Disjoint leaves only: never truncate a segment or fabricate ID filters."""
    if len(group) < 10:
        return
    if len(group) <= 5000:
        yield filters, group
        return
    if not dimensions:
        return  # Identical allowed filters cannot express a smaller audience.
    column, *rest = dimensions
    if column not in group:
        yield from _cells(group, filters, rest)
        return
    for value, part in group.groupby(column, observed=True, sort=True):
        if value in SEGMENTS[column]:
            yield from _cells(part, {**filters, "filter_" + column: str(value)}, rest)


def _median(group, column):
    if column not in group:
        return None
    values = pd.to_numeric(group[column], errors="coerce")
    values = values[np.isfinite(values) & (values >= 0)]
    return float(values.median()) if len(values) else None


def _number(value):
    value = pd.to_numeric(value, errors="coerce")
    return float(value) if pd.notna(value) and np.isfinite(value) and value >= 0 else None


def _package_fit(group, tariff):
    """Bounded heuristic [0,1], not a conversion probability.

    DATA_VOLUME follows the dictionary. LTE is not added: described as a subset,
    it nevertheless often exceeds total data in this synthetic package.
    Voice allowances are alternatives: use their maximum, not their sum.
    """
    terms = []
    voice = [_number(tariff.get(c)) for c in
             ("Min_another_operator_in_PKG", "Min_another_operator_and_city_in_PKG")]
    voice = [v for v in voice if v is not None]
    for usage, allowance in (
        (_median(group, "DATA_VOLUME"), _number(tariff.get("Data_in_PKG"))),
        (_median(group, "OUT_LOC_OFFNET_MIN"), max(voice) if voice else None),
    ):
        if usage is not None and usage > 0 and allowance is not None:
            terms.append(min(allowance / usage, 1.0))
    price = _number(tariff.get("price_tariff"))
    arpu = _median(group, "predicted_arpu")
    if arpu is not None and arpu > 0 and price is not None:
        terms.append(min(arpu / price, 1.0) if price else 1.0)
    return float(np.mean(terms)) if terms else 0.5


def build_candidates(profile, tariffs, history_path=None) -> list[dict]:
    """Contract v1; two rounds across disjoint cells, strongest option first.

    No-history options carry a zero prior and a small exploration priority.
    Missing optional usage/package columns are neutral. Invalid required rows
    are not silently removed inside an otherwise selectable campaign.
    """
    path = Path(history_path) if history_path is not None else Path(__file__).resolve().parents[1] / "data/change_tariff.csv"
    prior = _history(path)
    if tariffs.tariff_plan_code.dropna().duplicated().any():
        raise ValueError("tariff_plan_code must be unique")
    catalogue = tariffs.dropna(subset=["tariff_plan_code"]).set_index("tariff_plan_code")
    known = sorted(catalogue.index.astype(str))
    cells = []
    for (current, segment), group in profile.groupby(["current_tariff", "arpu_segment"], observed=True, sort=True):
        if current not in known or segment not in SEGMENTS["arpu_segment"]:
            continue
        group = group.sort_values("ID_NUMBER") if "ID_NUMBER" in group else group
        filters = {"filter_current_tariff": str(current), "filter_arpu_segment": str(segment)}
        for filters, part in _cells(group, filters):
            values = pd.to_numeric(part.predicted_arpu, errors="coerce")
            if not (np.isfinite(values) & (values >= 0)).all():
                continue
            value = float(values.sum())
            options = []
            for target in known:
                if target == current:
                    continue
                key = (current, segment, target)
                median, support = (float(prior.loc[key, "median"]), int(prior.loc[key, "count"])) if key in prior.index else (0.0, 0)
                shrunk = median * support / (support + 20)
                fit = _package_fit(part, catalogue.loc[target])
                # This no-history floor is exploration, never a lift estimate.
                signal = max(shrunk, 0.0) if support else 0.01
                options.append({**filters, "target_tariff": target,
                                "prior_lift_ratio": shrunk, "history_support": support,
                                "priority": signal * value * (0.8 + 0.2 * fit)})
            options.sort(key=lambda c: (-c["priority"], -c["history_support"], c["target_tariff"]))
            if options:
                cells.append(options)
    cells.sort(key=lambda opts: (-opts[0]["priority"], tuple(sorted(
        (k, v) for k, v in opts[0].items() if k.startswith("filter_")))))
    return [options[rank] for rank in range(2) for options in cells if len(options) > rank]
