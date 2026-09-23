"""Export a factual mock report for the third laptop's demo."""
import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent import Agent
from local_eval import evaluate_agent


def json_safe(value):
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def build_report(seed=42):
    class RecordedAgent:
        campaigns = None
        pilots = None

        def act(self, env):
            self.campaigns = Agent().act(env)
            self.pilots = [dict(pilot) for pilot in env.pilot_history]
            return self.campaigns

    recorded = RecordedAgent()
    metrics = evaluate_agent(recorded, seed=seed, verbose=False)
    if metrics is None or recorded.campaigns is None:
        raise RuntimeError("Agent failed to produce a report; inspect evaluator output")
    return json_safe({
        "schema_version": 1, "mode": "mock", "seed": seed,
        "metrics": metrics, "final_campaigns": recorded.campaigns,
        "pilot_history": recorded.pilots,
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=Path("artifacts/report.json"))
    args = parser.parse_args()
    report = build_report(args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Mock report: {args.output}; final campaigns: {len(report['final_campaigns'])}")


if __name__ == "__main__":
    main()
