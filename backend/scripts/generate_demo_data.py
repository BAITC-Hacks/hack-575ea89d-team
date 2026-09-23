"""Generate reproducible, linked synthetic data for the hackathon demo.

Run from backend/: python scripts/generate_demo_data.py
Recent demo complaints receive timestamps relative to generation time so the
default 60-minute analysis window remains useful immediately after generation.
"""

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RNG = random.Random(575)
ISSUES = ["slow_internet", "no_connection", "dropped_calls", "weak_signal"]
TEXT = {
    "slow_internet": "Медленно работает мобильный интернет",
    "no_connection": "Пропадает мобильное соединение",
    "dropped_calls": "Обрываются звонки в районе",
    "weak_signal": "Слабый сигнал мобильной сети",
}


def write_json(name: str, value: object) -> None:
    (DATA / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_towers() -> tuple[list[dict], list[dict]]:
    areas = [f"Astana District {letter}" for letter in "XYZ"] + [f"Astana District {i}" for i in range(1, 10)]
    population = [
        {"area": area, "population": 18000 + index * 2300, "density_per_km2": 2400 + index * 170,
         "data_source": "synthetic"}
        for index, area in enumerate(areas)
    ]
    by_area = {row["area"]: row for row in population}
    towers = []
    for tower_id in range(1, 36):
        area = areas[(tower_id - 1) % len(areas)]
        lat = 51.10 + ((tower_id * 17) % 70) / 1000
        lon = 71.38 + ((tower_id * 23) % 80) / 1000
        load = 48 + (tower_id * 13) % 44
        capacity = 800 + (tower_id * 37) % 500
        towers.append({
            "id": tower_id, "area": area, "lat": round(lat, 6), "lon": round(lon, 6),
            "network_type": "5G" if tower_id % 5 == 0 else "4G", "capacity": capacity,
            "current_load_pct": load, "coverage_radius_km": round(1.2 + (tower_id % 7) * 0.15, 1),
            "status": "normal", "affected_users": round(by_area[area]["population"] * load / 1000),
            "data_source": "synthetic",
        })

    # Preserve the deliberately varied anchor scenarios used by the demo.
    overrides = {
        17: ("Astana District X", 51.128, 71.431, 1000, 96, 2.0, "degraded", 1823),
        23: ("Astana District Y", 51.145, 71.455, 900, 91, 1.8, "degraded", 640),
        31: ("Astana District Z", 51.105, 71.390, 1100, 68, 0.8, "coverage_issue", 210),
        8: ("Astana District X", 51.160, 71.400, 1200, 54, 2.2, "normal", 80),
    }
    for tower_id, values in overrides.items():
        area, lat, lon, capacity, load, radius, status, users = values
        tower = towers[tower_id - 1]
        tower.update(area=area, lat=lat, lon=lon, capacity=capacity, current_load_pct=load,
                     coverage_radius_km=radius, status=status, affected_users=users,
                     network_type="5G" if tower_id == 8 else "4G")
    return towers, population


def make_complaints(towers: list[dict]) -> list[dict]:
    now = datetime.now(timezone.utc)
    rows = []
    counters = {17: 347, 23: 80, 31: 25, 8: 12}
    for tower_id, count in counters.items():
        tower = towers[tower_id - 1]
        for index in range(count):
            minutes_ago = RNG.randrange(0, 55)
            issue = RNG.choice(ISSUES)
            rows.append({
                "id": f"CMP-{len(rows) + 1:05d}",
                "timestamp": (now - timedelta(minutes=minutes_ago, seconds=RNG.randrange(60))).isoformat(),
                "demo_age_minutes": minutes_ago,
                "area": tower["area"], "lat": round(tower["lat"] + RNG.uniform(-0.008, 0.008), 6),
                "lon": round(tower["lon"] + RNG.uniform(-0.008, 0.008), 6),
                "issue_type": issue, "text": TEXT[issue],
                "user_id": f"USR-{RNG.randrange(100000, 999999)}", "tower_id": tower_id,
                "data_source": "synthetic",
            })

    # Older background complaints bring the dataset to exactly 4,200 records.
    for index in range(4200 - len(rows)):
        tower = towers[RNG.randrange(len(towers))]
        issue = RNG.choice(ISSUES)
        days_ago = RNG.randrange(2, 31)
        rows.append({
            "id": f"CMP-{len(rows) + 1:05d}",
            "timestamp": (now - timedelta(days=days_ago, minutes=RNG.randrange(1440))).isoformat(),
            "area": tower["area"], "lat": round(tower["lat"] + RNG.uniform(-0.01, 0.01), 6),
            "lon": round(tower["lon"] + RNG.uniform(-0.01, 0.01), 6),
            "issue_type": issue, "text": TEXT[issue],
            "user_id": f"USR-{RNG.randrange(100000, 999999)}", "tower_id": tower["id"],
            "data_source": "synthetic",
        })
    RNG.shuffle(rows)
    return rows


def main() -> None:
    towers, population = make_towers()
    write_json("towers.json", towers)
    write_json("population.json", population)
    write_json("complaints.json", make_complaints(towers))
    print("Generated 35 synthetic towers, 12 population areas and 4,200 complaints.")


if __name__ == "__main__":
    main()
