"""Compare generators under ONE current Agent/planner, not whole historical agents.

Use --plan to supply preregistered seeds and --output for a NEW evidence file.
The original generator is loaded from the plan's actual Git ref; no fixed label.
Historical research/mock_comparison.json is intentionally left untouched.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys
import time
import types
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.provenance import git, manifest, sha256, verify_unchanged, write_new_json

VARIANTS = ('original', 'current', 'median')
METRICS = ('net_arpu_gain', 'total_cost', 'total_contacts', 'n_campaigns', 'n_pilots')


def load_builder(source, filename):
    module = types.ModuleType('experiment_candidates')
    module.__file__ = str(filename)
    exec(compile(source, str(filename), 'exec'), module.__dict__)
    def builder(profile, tariffs):
        return module.build_candidates(profile, tariffs, ROOT / 'data/change_tariff.csv')
    return builder


def describe(values):
    return {'mean': statistics.mean(values), 'median': statistics.median(values),
            'min': min(values), 'max': max(values)} if values else None


def summarize(rows, seed_groups):
    summary = {}
    for group, seeds in seed_groups.items():
        selected = [r for r in rows if r['seed'] in seeds]
        by_variant = {}
        for name in VARIANTS:
            good = [r['variants'][name] for r in selected if 'error' not in r['variants'][name]]
            by_variant[name] = {'completed': len(good), 'failed': len(selected) - len(good),
                                **{key: describe([r[key] for r in good]) for key in (*METRICS, 'seconds')}}
        comparisons = {}
        for left, right in (('current', 'original'), ('median', 'original'), ('current', 'median')):
            paired = [r for r in selected if all('error' not in r['variants'][v] for v in (left, right))]
            deltas = [r['variants'][left]['net_arpu_gain'] - r['variants'][right]['net_arpu_gain'] for r in paired]
            comparisons[f'{left}_minus_{right}'] = {
                'paired_count': len(paired), 'delta_net': describe(deltas),
                'improvements': sum(d > 1e-9 for d in deltas), 'worsenings': sum(d < -1e-9 for d in deltas),
                'ties': sum(abs(d) <= 1e-9 for d in deltas),
                'worse_seeds': [r['seed'] for r, d in zip(paired, deltas) if d < -1e-9]}
        summary[group] = {'seeds': seeds, 'variants': by_variant, 'paired': comparisons}
    return summary


def benchmark(plan_path):
    plan_path = Path(plan_path).resolve()
    plan = json.loads(plan_path.read_text(encoding='utf-8-sig'))
    if plan['comparison_kind'] != 'candidate_generators_fixed_planner':
        raise ValueError('This runner only compares generators with a fixed planner; full-agent comparison requires isolated complete checkouts.')
    seeds = [seed for group in plan['seed_groups'].values() for seed in group]
    if len(seeds) != len(set(seeds)):
        raise ValueError('Seed groups must not overlap')
    if plan['variants'] != list(VARIANTS):
        raise ValueError('Expected original, current and median variants')
    ref = git('rev-parse', plan['original_ref'] + '^{commit}').decode().strip()
    original = git('show', f"{ref}:{plan['original_path']}")
    source_paths = [ROOT / p for p in ('agent.py', 'strategy/planner.py', 'research/candidates.py',
                                      'research/median_candidates.py', 'research/provenance.py',
                                      'tests/test_research_benchmark.py')]
    evidence = manifest(source_paths, [plan_path])
    evidence['original_generator'] = {'resolved_commit': ref, 'path': plan['original_path'],
                                       'git_blob_oid': git('rev-parse', f"{ref}:{plan['original_path']}").decode().strip(),
                                       'sha256': sha256(original), 'source_utf8': original.decode('utf-8')}
    sources = {'original': original.decode('utf-8'),
               'current': evidence['sources']['research/candidates.py']['source_utf8'],
               'median': evidence['sources']['research/median_candidates.py']['source_utf8']}
    builders = {name: load_builder(source, ROOT / 'research' / f'{name}_snapshot.py') for name, source in sources.items()}
    # Public evaluator only; no model effects are inspected or fed to research.
    from agent import Agent
    from local_eval import evaluate_agent
    rows = []
    started_at = datetime.now(timezone.utc).isoformat()
    for index, seed in enumerate(seeds):
        order = VARIANTS[index % 3:] + VARIANTS[:index % 3]
        row = {'seed': seed, 'run_order': list(order), 'variants': {}}
        for name in order:
            started = time.perf_counter()
            try:
                with patch('strategy.planner.build_candidates', builders[name]):
                    metrics = evaluate_agent(Agent(), seed=seed, verbose=False)
                result = {key: metrics[key] for key in METRICS}
            except Exception as exc:
                result = {'error': f'{type(exc).__name__}: {exc}'}
            result['seconds'] = time.perf_counter() - started
            row['variants'][name] = result
        rows.append(row)
        print(f'Completed seed {seed} ({index + 1}/{len(seeds)})', flush=True)
    verify_unchanged(evidence)
    return {'schema_version': 2, 'mode': 'mock', 'comparison_kind': plan['comparison_kind'],
            'full_agent_comparison': False, 'started_at_utc': started_at, 'plan': plan,
            'seed_list': seeds, 'provenance': evidence, 'rows': rows,
            'summary': summarize(rows, plan['seed_groups']),
            'limits': ['Same seed need not produce identical pilot samples after actions diverge.',
                       'Wall time is descriptive, sequential rotating order, no process isolation.',
                       'Historical full-agent numbers cannot be reproduced by swapping only a generator.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists; choose a new path. Historical evidence is immutable.')
    write_new_json(args.output, benchmark(args.plan))
