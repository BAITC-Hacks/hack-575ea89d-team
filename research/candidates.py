"""Public-data pilot hypotheses. Historical switcher ratios are not conversion rates."""
import math
from pathlib import Path

import numpy as np
import pandas as pd

HISTORY_COLUMNS = ['tariff_plan_code_from', 'tariff_plan_code_to',
                   'AVG_ARPU_PREV_3M', 'AVG_ARPU_NEXT_3M']
SEGMENTS = {'arpu_segment': ('LOW', 'MID', 'HIGH'),
            'data_segment': ('NON_USER', 'LITE', 'HEAVY'),
            'call_segment': ('LOW', 'MEDIUM', 'HIGH')}
PRIOR_WEIGHT = 20


def _history_stats(path, known):
    """Return (shrunk ratio, valid record count, caution margin) per cell.

    Missing/empty history is a cold start. Malformed files raise an error.
    The margin is a ranking heuristic, NOT a calibrated confidence interval.
    """
    try:
        history = pd.read_csv(path)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return {}
    missing = set(HISTORY_COLUMNS) - set(history.columns)
    if missing:
        raise ValueError(f'History missing columns: {sorted(missing)}')
    # Equal measurements from different customers are independent records.
    if {'ID_NUMBER', 'TIME_KEY'}.issubset(history.columns):
        history = history.drop_duplicates()
    history = history.copy()
    for col in HISTORY_COLUMNS[2:]:
        history[col] = pd.to_numeric(history[col], errors='coerce')
    before, after = history.AVG_ARPU_PREV_3M, history.AVG_ARPU_NEXT_3M
    valid = (np.isfinite(before) & np.isfinite(after) & (before >= 100) & (after >= 0)
             & history.tariff_plan_code_from.isin(known)
             & history.tariff_plan_code_to.isin(known)
             & (history.tariff_plan_code_from != history.tariff_plan_code_to))
    history = history.loc[valid].copy()
    before = history.AVG_ARPU_PREV_3M
    # Guide: LOW <1000, MID 1000..5000 inclusive, HIGH >5000.
    history['arpu_segment'] = np.where(before < 1000, 'LOW', np.where(before <= 5000, 'MID', 'HIGH'))
    history['change'] = (history.AVG_ARPU_NEXT_3M / before - 1).clip(-1, 3)
    stats = {}
    for key, rows in history.groupby(['tariff_plan_code_from', 'arpu_segment', 'tariff_plan_code_to'], observed=True, sort=True):
        values = rows.change.sort_values().to_numpy()
        n = len(values)
        if n >= 10:
            values = np.clip(values, *np.quantile(values, [.1, .9]))
        mean = float(values.mean())
        shrunk = mean * n / (n + PRIOR_WEIGHT)
        # Regularized dispersion prevents singleton certainty.
        variance = (float(np.square(values - mean).sum()) + PRIOR_WEIGHT * .25) / (n + PRIOR_WEIGHT)
        margin = math.sqrt(variance / (n + PRIOR_WEIGHT))
        stats[key] = (shrunk, n, margin)
    return stats


def _cells(group, filters, columns=('data_segment', 'call_segment')):
    """Disjoint representable cells only; never truncate rows behind a filter."""
    if len(group) < 10:
        return
    if len(group) <= 5000:
        yield filters, group
        return
    alternatives = []
    for col in columns:
        if col not in group:
            continue
        children = []
        remaining = tuple(c for c in columns if c != col)
        for label in SEGMENTS[col]:
            child = group.loc[group[col] == label]
            children.extend(_cells(child, {**filters, f'filter_{col}': label}, remaining))
        alternatives.append(children)
    if alternatives:
        # Retain the largest legal audience, then prefer fewer fragments.
        yield from max(alternatives, key=lambda cells: (sum(len(g) for _, g in cells), -len(cells)))
    # No legal split remains: omit the oversized cell, never truncate IDs.


def _median(frame, column):
    if column not in frame:
        return None
    values = pd.to_numeric(frame[column], errors='coerce')
    values = values[np.isfinite(values) & (values >= 0)]
    return float(values.median()) if len(values) else None


def _fit(group, tariff):
    """Weak package/affordability tie breaker, not a response probability."""
    scores = []
    for usage, capacity in (('DATA_VOLUME', 'Data_in_PKG'),
                            ('OUT_LOC_OFFNET_MIN', 'Min_another_operator_in_PKG')):
        demand = _median(group, usage)
        cap = pd.to_numeric(tariff.get(capacity), errors='coerce')
        if usage == 'OUT_LOC_OFFNET_MIN':
            shared = pd.to_numeric(tariff.get('Min_another_operator_and_city_in_PKG'), errors='coerce')
            land = _median(group, 'OUT_LOC_LAND_MIN')
            if pd.notna(shared) and shared > 0:
                cap = (max(0.0, shared - land) + (cap if pd.notna(cap) else 0)
                       if land is not None else float('nan'))
        if demand is not None and pd.notna(cap) and np.isfinite(cap) and cap >= 0:
            scores.append(1.0 if demand == 0 else min(1.0, float(cap) / demand))
    value = _median(group, 'predicted_arpu')
    price = pd.to_numeric(tariff.get('price_tariff'), errors='coerce')
    if value is not None and pd.notna(price) and np.isfinite(price) and price >= 0:
        scores.append(1.0 if price == 0 else min(1.0, value / price))
    return float(np.mean(scores)) if scores else .5


def build_candidates(profile, tariffs, history_path=None) -> list[dict]:
    """Contract v1: 10..5000 rows, two alternatives per disjoint cell.

    One option from every cell precedes second options. Missing evidence has
    small exploration priority but a zero historical prior. No env access.
    """
    path = Path(history_path) if history_path is not None else Path(__file__).resolve().parents[1] / 'data/change_tariff.csv'
    tariff_rows = tariffs.dropna(subset=['tariff_plan_code']).copy()
    if tariff_rows.tariff_plan_code.duplicated().any():
        raise ValueError('tariff_plan_code must be unique')
    tariff_rows = tariff_rows.set_index('tariff_plan_code')
    known = sorted(tariff_rows.index.astype(str))
    stats = _history_stats(path, known)
    cells = []
    for (current, segment), group in profile.groupby(['current_tariff', 'arpu_segment'], observed=True, sort=True):
        if current not in known or segment not in SEGMENTS['arpu_segment']:
            continue
        filters = {'filter_current_tariff': str(current), 'filter_arpu_segment': str(segment)}
        for cell_filters, cell in _cells(group, filters):
            value = pd.to_numeric(cell.predicted_arpu, errors='coerce')
            # A public filter would still select malformed rows. Reject the
            # entire cell instead of silently pricing only its valid subset.
            if not (np.isfinite(value) & (value >= 0)).all():
                continue
            audience_value = float(value.sort_values().sum())
            options = []
            for target in known:
                if target == current:
                    continue
                prior, support, margin = stats.get((current, segment, target), (0.0, 0, 0.0))
                fit = _fit(cell, tariff_rows.loc[target])
                signal = max(prior - margin, 0.0) if support else .01
                options.append({**cell_filters, 'target_tariff': target,
                                'prior_lift_ratio': prior, 'history_support': support,
                                'priority': signal * audience_value * (.75 + .25 * fit)})
            options.sort(key=lambda c: (-c['priority'], -c['history_support'], c['target_tariff']))
            if options:
                cells.append(options)
    cells.sort(key=lambda options: (-options[0]['priority'], tuple(sorted((k, v) for k, v in options[0].items() if k.startswith('filter_')))))
    return [options[rank] for rank in range(2) for options in cells if len(options) > rank]
