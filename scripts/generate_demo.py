"""Deterministic synthetic fixture generator. Never writes into team source data."""
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def generate(destination: Path, now: datetime | None = None) -> dict:
    destination = destination.resolve()
    source = ROOT / "backend" / "data"
    if destination == source.resolve() or source.resolve() in destination.parents:
        raise ValueError("Choose a separate directory; team data must not be overwritten")
    destination.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now(timezone.utc)
    rng = random.Random(575)
    towers = json.loads((source / "towers.json").read_text())
    incidents = json.loads((source / "incidents.json").read_text())
    solutions = json.loads((source / "solutions.json").read_text())
    towers = [dict(t) for t in towers]
    used = {t["id"] for t in towers}
    for tower_id in range(1, 100):
        if len(towers) >= 40:
            break
        if tower_id in used:
            continue
        area = ["Astana District X", "Astana District Y", "Astana District Z"][tower_id % 3]
        load = rng.randint(40, 94)
        towers.append({"id": tower_id, "area": area,
                       "lat": round(51.1 + rng.random() * .08, 6),
                       "lon": round(71.38 + rng.random() * .12, 6),
                       "network_type": "4G", "capacity": 1000,
                       "current_load_pct": load, "coverage_radius_km": 1.8,
                       "status": "degraded" if load >= 90 else "normal",
                       "affected_users": 200 + tower_id * 13})
    # Retain the three fixture counts and distribute the remainder reproducibly.
    counts = {item["tower_id"]: item["complaints_count"] for item in incidents}
    others = [t for t in towers if t["id"] not in counts]
    remaining = 4000 - sum(counts.values())
    if remaining < 0 or not others:
        raise ValueError("Team fixtures changed; review generator assumptions")
    for index, tower in enumerate(others):
        counts[tower["id"]] = remaining // len(others) + (index < remaining % len(others))
    complaints = []
    population = []
    for tower in towers:
        # A per-tower catchment estimate; areas are not summed to unique residents.
        population.append({"tower_id": tower["id"], "area": tower["area"],
                           "estimated_users": tower["affected_users"], "source": "synthetic_catchment"})
        for _ in range(counts[tower["id"]]):
            complaints.append({"id": f"CMP-{len(complaints) + 1:05}", "tower_id": tower["id"],
                               "area": tower["area"],
                               "timestamp": (now - timedelta(seconds=rng.randint(60, 2700))).isoformat(),
                               "issue_type": "weak_signal" if tower["status"] == "coverage_issue" else "slow_internet",
                               "text": "Синтетическая жалоба: нестабильная мобильная связь."})
    payloads = {"towers": towers, "incidents": incidents, "solutions": solutions,
                "complaints": complaints, "population": population}
    for name, values in payloads.items():
        path = destination / (name + ".json")
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(path)
    manifest = {"synthetic": True, "seed": 575, "generated_at": now.isoformat(),
                "counts": {name: len(values) for name, values in payloads.items()}}
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "backend" / ".demo-data")
    args = parser.parse_args()
    print(json.dumps(generate(args.output), ensure_ascii=False, indent=2))
