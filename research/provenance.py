"""Read-only provenance for research experiments; no environment introspection."""
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(
        ['git', '-c', f'safe.directory={ROOT.as_posix()}', *args], cwd=ROOT)


def fingerprint(path):
    path = Path(path)
    raw = path.read_bytes()
    return {'sha256': sha256(raw), 'lf_sha256': sha256(raw.replace(b'\r\n', b'\n')),
            'bytes': len(raw)}


def source_record(path):
    path = Path(path)
    relative = path.relative_to(ROOT).as_posix()
    return {'path': relative, **fingerprint(path),
            'last_path_commit': git('log', '-1', '--format=%H', '--', relative).decode().strip() or None,
            'source_utf8': path.read_text(encoding='utf-8-sig')}


def manifest(source_paths, extra_paths=()):
    # Hashing organizer bytes is only provenance, never reading model parameters.
    paths = sorted(set([*ROOT.glob('*.csv'), *ROOT.glob('data/*.csv'),
                        *(ROOT / p for p in ('environment.py', 'mock_environment.py', 'scoring_core.py', 'local_eval.py', 'requirements.txt')),
                        *(Path(p) for p in extra_paths)]))
    return {'git_head': git('rev-parse', 'HEAD').decode().strip(),
            'git_status': git('status', '--porcelain').decode(),
            'sources': {str(Path(p).relative_to(ROOT).as_posix()): source_record(p) for p in source_paths},
            'inputs': {p.relative_to(ROOT).as_posix(): fingerprint(p) for p in paths},
            'runtime': {'python': sys.version, 'implementation': platform.python_implementation(),
                        'platform': platform.platform(), 'numpy': np.__version__, 'pandas': pd.__version__}}


def verify_unchanged(evidence):
    for section in ('sources', 'inputs'):
        for name, record in evidence[section].items():
            if fingerprint(ROOT / name)['sha256'] != record['sha256']:
                raise RuntimeError(f'Experiment input changed during run: {name}')


def write_new_json(path, value):
    """Exclusive create: historical outputs can never be silently overwritten."""
    path = Path(path)
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    with path.open('x', encoding='utf-8', newline='\n') as out:
        out.write(payload)
