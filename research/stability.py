"""Sensitivity of public-data hypothesis rankings, NOT causal effect confidence.

python -m research.stability --plan <preregistered JSON> --output <new JSON>
No environment/evaluator imports; only public CSVs and the current generator.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

from research.candidates import build_candidates, _history_stats
from research.provenance import ROOT, manifest, verify_unchanged, write_new_json

FILTERS = ('filter_current_tariff', 'filter_arpu_segment', 'filter_data_segment', 'filter_call_segment')


def cell_key(candidate):
    return '|'.join(str(candidate.get(key, '*')) for key in FILTERS)


def candidate_key(candidate):
    return cell_key(candidate) + '|' + candidate['target_tariff']


def draw_events(events, rng):
    """A sampled event's multiplicity must survive runtime exact-deduplication."""
    sampled = events.iloc[rng.integers(0, len(events), size=len(events))].copy().reset_index(drop=True)
    sampled['ID_NUMBER'] = np.arange(len(sampled))
    return sampled


def first_choices(candidates):
    result = {}
    for candidate in candidates:
        result.setdefault(cell_key(candidate), candidate['target_tariff'])
    return result


def summarize_draws(base, draws, top_k):
    ranks = defaultdict(list)
    top_counts = Counter()
    choices = defaultdict(Counter)
    base_set = {candidate_key(c) for c in base[:top_k]}
    overlaps = []
    for candidates in draws:
        keys = [candidate_key(c) for c in candidates]
        selected = set(keys[:top_k])
        top_counts.update(selected)
        for rank, key in enumerate(keys, 1):
            ranks[key].append(rank)
        for cell, target in first_choices(candidates).items():
            choices[cell][target] += 1
        overlaps.append(len(base_set & selected) / len(base_set | selected) if base_set | selected else 1.)
    keys_to_report = set(top_counts) | base_set
    base_map = {candidate_key(c): (i, c) for i, c in enumerate(base, 1)}
    rows = []
    for key in sorted(keys_to_report):
        seen_ranks = ranks[key]
        original = base_map.get(key)
        rows.append({'key': key, 'baseline_rank': original[0] if original else None,
                     'baseline_support': original[1]['history_support'] if original else None,
                     'baseline_prior': original[1]['prior_lift_ratio'] if original else None,
                     'top_k_count': top_counts[key], 'top_k_fraction': top_counts[key] / len(draws),
                     'present_count': len(seen_ranks), 'absent_count': len(draws) - len(seen_ranks),
                     'rank_quantiles_when_present': dict(zip(('p10', 'median', 'p90'), map(float, np.quantile(seen_ranks, [.1, .5, .9])))) if seen_ranks else None})
    return {'candidates': sorted(rows, key=lambda row: (-row['top_k_count'], row['key'])),
            'first_choice_counts_by_cell': {cell: dict(counts.most_common()) for cell, counts in sorted(choices.items())},
            'top_k_jaccard': {'mean': float(np.mean(overlaps)), 'min': min(overlaps),
                              'median': float(np.median(overlaps)), 'max': max(overlaps)}}


def eligible_events(history, candidate):
    before = pd.to_numeric(history.AVG_ARPU_PREV_3M, errors='coerce')
    after = pd.to_numeric(history.AVG_ARPU_NEXT_3M, errors='coerce')
    segment = np.where(before < 1000, 'LOW', np.where(before <= 5000, 'MID', 'HIGH'))
    return history.index[(history.tariff_plan_code_from == candidate['filter_current_tariff'])
                         & (history.tariff_plan_code_to == candidate['target_tariff'])
                         & (segment == candidate['filter_arpu_segment'])
                         & np.isfinite(before) & np.isfinite(after) & (before >= 100) & (after >= 0)]


def analyze(plan_path):
    plan_path = Path(plan_path).resolve()
    plan = json.loads(plan_path.read_text(encoding='utf-8-sig'))
    config = plan['bootstrap']
    evidence = manifest([ROOT / p for p in ('research/candidates.py', 'research/stability.py', 'research/provenance.py')], [plan_path])
    profile = pd.read_csv(ROOT / 'customer_profile.csv')
    tariffs = pd.read_csv(ROOT / 'tariff_dictionary.csv')
    raw = pd.read_csv(ROOT / 'data/change_tariff.csv')
    events = raw.drop_duplicates().reset_index(drop=True)
    if events.duplicated(['ID_NUMBER', 'TIME_KEY']).any():
        raise ValueError('Conflicting event keys require an explicit resampling unit decision')
    base = build_candidates(profile, tariffs)
    rng = np.random.default_rng(config['rng_seed'])
    draws, raw_draws, influences = [], [], []
    started = datetime.now(timezone.utc).isoformat()
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'sample.csv'
        for index in range(config['replicates']):
            draw_events(events, rng).to_csv(path, index=False)
            candidates = build_candidates(profile, tariffs, path)
            draws.append(candidates)
            raw_draws.append({'replicate': index, 'top_k': [candidate_key(c) for c in candidates[:config['top_k']]]})
            if (index + 1) % 10 == 0:
                print(f'Bootstrap {index + 1}/{config["replicates"]}', flush=True)
        for candidate in base[:config['top_k']]:
            if not 1 <= candidate['history_support'] <= 30:
                continue
            indices = eligible_events(events, candidate)
            if len(indices) != candidate['history_support']:
                raise AssertionError('Leave-one-out support differs from generator support')
            cases = []
            key = candidate_key(candidate)
            cell = cell_key(candidate)
            for index in indices:
                events.drop(index=index).to_csv(path, index=False)
                candidates = build_candidates(profile, tariffs, path)
                keys = [candidate_key(c) for c in candidates]
                rank = keys.index(key) + 1 if key in keys else None
                cases.append({'removed_event_row': int(index), 'rank': rank,
                              'first_choice_target': first_choices(candidates).get(cell),
                              'in_top_k': rank is not None and rank <= config['top_k']})
            influences.append({'key': key, 'support': len(indices), 'cases': cases,
                               'top_k_losses': sum(not c['in_top_k'] for c in cases),
                               'first_choice_changes': sum(c['first_choice_target'] != candidate['target_tariff'] for c in cases)})
            print(f'Leave-one-out {key}: {len(cases)} events', flush=True)
    verify_unchanged(evidence)
    return {'schema_version': 1, 'analysis_kind': 'conditional_history_ranking_stability',
            'started_at_utc': started, 'plan': plan, 'provenance': evidence,
            'raw_rows': len(raw), 'deduplicated_events': len(events),
            'baseline_top_k': base[:config['top_k']], 'replicate_top_k': raw_draws,
            'bootstrap_summary': summarize_draws(base, draws, config['top_k']),
            'leave_one_out': influences,
            'limitations': ['Empirical event resampling does not identify causal campaign effects or population transfer.',
                           'Target profile and tariff catalogue stay fixed; absent transition cells stay absent.',
                           'All historical events are from one month; no temporal or customer-population holdout.',
                           'Rank quantiles condition on the pair being returned; absent counts are reported separately.',
                           'Single-event deletion covers only top-k historical cells with at most 30 observations.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists; choose a new path.')
    write_new_json(args.output, analyze(args.plan))
