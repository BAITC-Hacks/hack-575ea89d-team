"""Reproducible public-data audit: python -m research.audit > audit.json.

Read-only; no environment, scoring or pilot imports.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.candidates import build_candidates

ROOT = Path(__file__).resolve().parents[1]


def audit():
    keys = {
        "customer_profile.csv": ["ID_NUMBER"],
        "data/change_tariff.csv": ["ID_NUMBER", "TIME_KEY"],
        "data/traffic.csv": ["ID_NUMBER", "time_key"],
        "data/arpu_monthly.csv": ["ID_NUMBER", "TIME_KEY"],
        "data/dict_tariff.csv": ["tariff_plan_code"],
        "tariff_dictionary.csv": ["tariff_plan_code"],
        "feature_dictionary.csv": ["feature"],
    }
    tables = {name: pd.read_csv(ROOT / name) for name in keys}
    result = {"tables": {}}
    for name, frame in tables.items():
        item = {"rows": len(frame), "columns": len(frame.columns),
                "duplicate_rows": int(frame.duplicated().sum()),
                "duplicate_keys": int(frame.duplicated(keys[name]).sum()),
                "nulls": {k: int(v) for k, v in frame.isna().sum().items() if v},
                "nonfinite_numeric": {k: int((~np.isfinite(v.dropna())).sum())
                                      for k, v in frame.select_dtypes("number").items()
                                      if (~np.isfinite(v.dropna())).any()}}
        if "ID_NUMBER" in frame:
            item["unique_ids"] = int(frame.ID_NUMBER.nunique())
        for column in ("TIME_KEY", "time_key"):
            if column in frame:
                item["months"] = frame[column].value_counts().sort_index().to_dict()
        result["tables"][name] = item
    profile, history, tariffs = (tables[n] for n in
                                 ("customer_profile.csv", "data/change_tariff.csv", "data/dict_tariff.csv"))
    known = set(tariffs.tariff_plan_code)
    result["unknown_tariff_rows"] = {
        f"{name}:{column}": int((frame[column].notna() & ~frame[column].isin(known)).sum())
        for name, frame in tables.items()
        for column in ("current_tariff", "tariff_plan_code", "tariff_plan_code_from", "tariff_plan_code_to")
        if column in frame
    }
    result["id_overlap_with_profile"] = {
        name: len(set(profile.ID_NUMBER) & set(frame.ID_NUMBER))
        for name, frame in tables.items() if "ID_NUMBER" in frame and name != "customer_profile.csv"
    }
    counts = profile.groupby(["current_tariff", "arpu_segment"], observed=True).size()
    result["base_cells"] = {"count": len(counts), "min": int(counts.min()),
                            "median": float(counts.median()), "max": int(counts.max()),
                            "under_10": int((counts < 10).sum()), "over_5000": int((counts > 5000).sum())}
    result["segment_counts"] = {c: profile[c].value_counts(dropna=False).rename(index={np.nan: "missing"}).to_dict()
                                for c in ("arpu_segment", "data_segment", "call_segment")}
    result["predicted_arpu_sum"] = float(profile.predicted_arpu.sum())
    result["lte_exceeds_data"] = {
        name: int((frame.LTE_DATA_VOLUME > frame.DATA_VOLUME).sum())
        for name, frame in tables.items() if "LTE_DATA_VOLUME" in frame
    }
    before, after = history.AVG_ARPU_PREV_3M, history.AVG_ARPU_NEXT_3M
    ratio = after / before.replace(0, np.nan) - 1
    pairs = history.groupby(["tariff_plan_code_from", "tariff_plan_code_to"]).size()
    result["history"] = {
        "pairs": len(pairs), "possible_directed_pairs": len(known) * (len(known) - 1),
        "pairs_under_20": int((pairs < 20).sum()), "self_transitions": int((history.tariff_plan_code_from == history.tariff_plan_code_to).sum()),
        "before_under_100": int((before < 100).sum()), "before_nonpositive": int((before <= 0).sum()),
        "after_negative": int((after < 0).sum()),
        "ratio_quantiles_positive_before": ratio[before > 0].quantile([0, .25, .5, .75, .95, 1]).to_dict(),
        "upsell_over_10pct": int((ratio > .1).sum()), "downsell_under_minus10pct": int((ratio < -.1).sum()),
    }
    hypotheses = []
    candidates = build_candidates(profile, tariffs)
    ids = set()
    for candidate in candidates:
        part = profile
        for key, value in candidate.items():
            if key.startswith("filter_"):
                part = part[part[key.removeprefix("filter_")] == value]
        ids.update(part.ID_NUMBER)
        if len(hypotheses) < 8:
            target = tariffs.set_index("tariff_plan_code").loc[candidate["target_tariff"]]
            hypotheses.append({**candidate, "audience": len(part),
                               "predicted_arpu_sum": float(part.predicted_arpu.sum()),
                               "median_data_mb": float(part.DATA_VOLUME.median()),
                               "median_offnet_minutes": float(part.OUT_LOC_OFFNET_MIN.median()),
                               "target_price": float(target.price_tariff),
                               "target_data_mb": int(target.Data_in_PKG)})
    result["candidates"] = {"count": len(candidates), "covered_ids": len(ids),
                             "excluded_ids": len(profile) - len(ids), "first_eight": hypotheses}
    return result


if __name__ == "__main__":
    print(json.dumps(audit(), ensure_ascii=False, indent=2, allow_nan=False))
