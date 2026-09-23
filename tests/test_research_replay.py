"""Replay one saved fixed-planner comparison; refuse a changed runtime/data stack."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.provenance import fingerprint, sha256, write_new_json

spec = importlib.util.spec_from_file_location('replay_benchmark', ROOT / 'tests/test_research_benchmark.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def validate_stack(evidence):
    import numpy as np
    import pandas as pd
    if evidence['comparison_kind'] != 'candidate_generators_fixed_planner':
        raise ValueError('Only fixed-planner evidence can be replayed by this runner')
    runtime = evidence['provenance']['runtime']
    for key, actual in [('numpy', np.__version__), ('pandas', pd.__version__), ('python', sys.version)]:
        if runtime[key] != actual:
            raise ValueError(f'Runtime differs: {key}')
    sources = evidence['provenance']['sources']
    for path in ('agent.py', 'strategy/planner.py'):
        if fingerprint(ROOT / path)['lf_sha256'] != sources[path]['lf_sha256']:
            raise ValueError(f'Runtime source differs: {path}')
    for path, record in evidence['provenance']['inputs'].items():
        if fingerprint(ROOT / path)['lf_sha256'] != record['lf_sha256']:
            raise ValueError(f'Input differs: {path}')
    for name in ('research/candidates.py', 'research/median_candidates.py'):
        if sha256(sources[name]['source_utf8'].encode()) != sources[name]['lf_sha256']:
            raise ValueError(f'Embedded generator source differs: {name}')
    original = evidence['provenance']['original_generator']
    if sha256(original['source_utf8'].encode()) != original['sha256']:
        raise ValueError('Embedded original source differs')


def replay(path, seed):
    evidence = json.loads(Path(path).read_text(encoding='utf-8'))
    validate_stack(evidence)
    row = next((row for row in evidence['rows'] if row['seed'] == seed), None)
    if row is None:
        raise ValueError('Seed absent from saved evidence')
    from agent import Agent
    from local_eval import evaluate_agent
    sources = evidence['provenance']['sources']
    source_texts = {'original': evidence['provenance']['original_generator']['source_utf8'],
                    'current': sources['research/candidates.py']['source_utf8'],
                    'median': sources['research/median_candidates.py']['source_utf8']}
    outcomes = {}
    for name in row['run_order']:
        builder = runner.load_builder(source_texts[name], ROOT / 'research/replay_snapshot.py')
        with patch('strategy.planner.build_candidates', builder):
            actual = evaluate_agent(Agent(), seed=seed, verbose=False)
        outcomes[name] = {key: actual[key] for key in runner.METRICS}
        for key in runner.METRICS:
            if abs(actual[key] - row['variants'][name][key]) > 1e-8:
                raise AssertionError(f'Replay mismatch: {name}/{key}')
    return {'schema_version': 1, 'mode': 'mock', 'kind': 'saved_generator_comparison_replay',
            'evidence_sha256': fingerprint(path)['sha256'], 'seed': seed,
            'replay_runner': fingerprint(Path(__file__)), 'metrics_match': True,
            'metrics': outcomes, 'timing_replayed': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new output path; existing evidence is never overwritten.')
    write_new_json(args.output, replay(args.evidence, args.seed))
