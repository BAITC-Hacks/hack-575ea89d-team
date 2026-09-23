"""Read-only public CSV audit: python -m research.audit. No environment imports."""
import json
from pathlib import Path

import pandas as pd

from research.candidates import build_candidates, _fit, _history_stats, _median


ROOT = Path(__file__).resolve().parents[1]


def audit():
    files = {
        "customer_profile.csv": ["ID_NUMBER"],
        "data/change_tariff.csv": ["ID_NUMBER", "TIME_KEY"],
        "data/traffic.csv": ["ID_NUMBER", "time_key"],
        "data/arpu_monthly.csv": ["ID_NUMBER", "TIME_KEY"],
        "data/dict_tariff.csv": ["tariff_plan_code"],
        "tariff_dictionary.csv": ["tariff_plan_code"],
        "feature_dictionary.csv": ["feature"],
    }
    frames = {name: pd.read_csv(ROOT / name) for name in files}
    report = {}
    for name, df in frames.items():
        report[name] = {
            "rows": len(df), "columns": len(df.columns),
            "duplicate_rows": int(df.duplicated().sum()),
            "duplicate_keys": int(df.duplicated(files[name]).sum()),
            "missing": {k: int(v) for k, v in df.isna().sum().items() if v},
        }
        if "ID_NUMBER" in df:
            report[name]["unique_ids"] = int(df.ID_NUMBER.nunique())
            report[name]["profile_id_overlap"] = len(set(df.ID_NUMBER) & set(frames["customer_profile.csv"].ID_NUMBER))
        for col in ("time_key", "TIME_KEY"):
            if col in df:
                report[name]["months"] = sorted(df[col].unique().tolist())
    p, h = frames["customer_profile.csv"], frames["data/change_tariff.csv"]
    sizes = p.groupby(["current_tariff", "arpu_segment"], observed=True).size()
    pairs = h.groupby(["tariff_plan_code_from", "tariff_plan_code_to"]).size()
    change = h.AVG_ARPU_NEXT_3M / h.AVG_ARPU_PREV_3M.where(h.AVG_ARPU_PREV_3M > 0) - 1
    report["summary"] = {
        "predicted_arpu_sum": float(p.predicted_arpu.sum()),
        "segment_sizes": {str(k): int(v) for k, v in sizes.items()},
        "arpu_segments": p.arpu_segment.value_counts().to_dict(),
        "data_segments": p.data_segment.value_counts().to_dict(),
        "call_segments": p.call_segment.value_counts().to_dict(),
        "history_pairs": len(pairs), "pair_support_quantiles": pairs.quantile([0, .25, .5, .75, 1]).to_dict(),
        "history_prev_below_100": int((h.AVG_ARPU_PREV_3M < 100).sum()),
        "history_prev_nonpositive": int((h.AVG_ARPU_PREV_3M <= 0).sum()),
        "history_change_quantiles": change.quantile([0, .01, .5, .9, .99, 1]).to_dict(),
        "history_above_3": int((change > 3).sum()),
        "profile_lte_above_total": int((p.LTE_DATA_VOLUME > p.DATA_VOLUME).sum()),
        "traffic_lte_above_total": int((frames["data/traffic.csv"].LTE_DATA_VOLUME > frames["data/traffic.csv"].DATA_VOLUME).sum()),
        "tariff_dictionaries_match": frames["data/dict_tariff.csv"].sort_values("tariff_plan_code").reset_index(drop=True).equals(frames["tariff_dictionary.csv"].drop(columns="description").sort_values("tariff_plan_code").reset_index(drop=True)),
    }
    tariffs = frames["tariff_dictionary.csv"]
    stats = _history_stats(ROOT / "data/change_tariff.csv", set(tariffs.tariff_plan_code))
    report["summary"].update({
        "eligible_history_records": sum(v[1] for v in stats.values()),
        "historical_arpu_cells": len(stats),
        "historical_cells_under_10": sum(v[1] < 10 for v in stats.values()),
        "candidate_cells_10_to_5000": int(sizes.between(10, 5000).sum()),
        "candidate_cells_under_10": int((sizes < 10).sum()),
        "candidate_cells_above_5000": int((sizes > 5000).sum()),
        "historical_traffic_id_overlap": len(set(h.ID_NUMBER) & set(frames["data/traffic.csv"].ID_NUMBER)),
        "historical_monthly_id_overlap": len(set(h.ID_NUMBER) & set(frames["data/arpu_monthly.csv"].ID_NUMBER)),
    })
    report["hypotheses"] = []
    for candidate in build_candidates(p, tariffs)[:10]:
        group = p
        for key, value in candidate.items():
            if key.startswith("filter_"):
                group = group.loc[group[key[7:]] == value]
        tariff = tariffs.set_index("tariff_plan_code").loc[candidate["target_tariff"]]
        key = (candidate["filter_current_tariff"], candidate["filter_arpu_segment"], candidate["target_tariff"])
        prior, n, margin = stats.get(key, (0, 0, 0))
        report["hypotheses"].append({
            **candidate, "customers": len(group), "predicted_arpu_sum": float(group.predicted_arpu.sum()),
            "data_mb_median": _median(group, "DATA_VOLUME"),
            "offnet_min_median": _median(group, "OUT_LOC_OFFNET_MIN"),
            "data_package_mb": float(tariff.Data_in_PKG),
            "offnet_package_min": float(tariff.Min_another_operator_in_PKG),
            "shared_package_min": float(tariff.Min_another_operator_and_city_in_PKG),
            "price": float(tariff.price_tariff), "fit": _fit(group, tariff),
            "caution_margin": margin,
            "winsorized_change": prior * (n + 20) / n if n else None,
        })
    return report


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2, ensure_ascii=False, allow_nan=False))
