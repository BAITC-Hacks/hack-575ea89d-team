"""Explicit paired mock benchmark, not imported by runtime research.

python tests/test_research_benchmark.py --baseline ../baseline_candidates.py --output research/mock_comparison.json
Baseline source: git show 7c2257cf53fb045148ac3652c1f68abbe8216415:research/candidates.py
"""
import argparse
import importlib.util
import json
from pathlib import Path
import platform
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
from agent import Agent
from local_eval import evaluate_agent
from research.candidates import build_candidates


def benchmark(baseline_path, variant="current"):
    spec = importlib.util.spec_from_file_location("baseline_candidates", baseline_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Its default data path depended on its original location in research/.
    def baseline(profile, tariffs):
        return module.build_candidates(profile, tariffs, ROOT / "data/change_tariff.csv")
    builder_research = build_candidates
    if variant == "median":
        from research.median_candidates import build_candidates as builder_research
    rows = []
    for seed in [*range(10), 42]:
        row = {"seed": seed}
        for name, builder in (("baseline", baseline), ("research", builder_research)):
            started = time.perf_counter()
            with patch("strategy.planner.build_candidates", builder):
                metrics = evaluate_agent(Agent(), seed=seed, verbose=False)
            row[name] = {key: metrics[key] for key in
                         ("net_arpu_gain", "total_cost", "total_contacts", "n_campaigns", "n_pilots")}
            row[name]["seconds"] = time.perf_counter() - started
        row["delta_net"] = row["research"]["net_arpu_gain"] - row["baseline"]["net_arpu_gain"]
        rows.append(row)
    return {"mode": "mock", "variant": variant, "baseline_commit": "7c2257cf53fb045148ac3652c1f68abbe8216415",
            "python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__,
            "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variant", choices=["current", "median"], default="current")
    args = parser.parse_args()
    args.output.write_text(json.dumps(benchmark(args.baseline, args.variant), indent=2, allow_nan=False) + "\n", encoding="utf-8")
