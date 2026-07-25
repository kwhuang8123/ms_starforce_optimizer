"""Sweep every equipment x start star x repair policy combination to a target star.

Writes two files into ``starforce/sim_data``: the full summaries as JSON, and a
flat CSV for spreadsheet analysis. Re-run this after editing
``data/volatile.json`` to refresh the dataset against new prices.
"""

from __future__ import annotations

import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from starforce import RepairPolicy, RunConfig, rules, simulate, volatile_data
from starforce.static_data import STAR_SCROLL_STARS
from starforce.stats import SimulationSummary
from starforce.units import to_yi

# ---------------------------------------------------------------------------
# SETTINGS - edit these
# ---------------------------------------------------------------------------

#: Every run in the sweep climbs to this star.
TARGET_STAR = 22

#: Starting stars to compare. 10-14 are omitted: those scrolls all cost the
#: same 0.2e and carry no destruction risk, so they barely differ from 15.
START_STARS: tuple[int, ...] = (15, 16, 17, 18, 19, 20)

#: Repair policies to compare.
POLICIES: tuple[RepairPolicy, ...] = (RepairPolicy.FULL, RepairPolicy.TO_12)

#: Trials per combination.
TRIALS = 50_000

#: Fixed so the stored dataset is reproducible.
SEED = 20260726

#: Percentiles recorded in the JSON. The CSV keeps the four in CSV_PERCENTILES.
PERCENTILES: tuple[int, ...] = (5, 10, 25, 50, 75, 90, 95, 99)

#: Percentiles given their own CSV columns.
CSV_PERCENTILES: tuple[int, ...] = (25, 50, 75, 90)

#: Where the dataset lands. Created if it does not exist.
OUTPUT_DIR = Path(__file__).resolve().parent / "starforce" / "sim_data"

#: How many cheapest approaches to print per equipment.
TOP_N = 3

# ---------------------------------------------------------------------------


def run_sweep(
    target_star: int = TARGET_STAR,
    start_stars: Sequence[int] = START_STARS,
    policies: Sequence[RepairPolicy] = POLICIES,
    trials: int = TRIALS,
    seed: int | None = SEED,
    percentiles: Sequence[int] = PERCENTILES,
) -> list[SimulationSummary]:
    """Simulate every catalogue equipment against every start star and policy."""
    names = volatile_data.known_names()
    total = len(names) * len(start_stars) * len(policies)
    print(
        f"{len(names)} equipment x {len(start_stars)} start stars x "
        f"{len(policies)} policies = {total} combinations, "
        f"{trials:,} trials each\n"
    )

    summaries: list[SimulationSummary] = []
    started = time.perf_counter()
    for name in names:
        for start_star in start_stars:
            for policy in policies:
                config = RunConfig.for_equipment(
                    name, start_star, target_star, repair_policy=policy
                )
                summary = simulate(
                    config, trials=trials, seed=seed, percentiles=percentiles
                )
                summaries.append(summary)
                print(
                    f"[{len(summaries):>3}/{total}] {name:<6} "
                    f"{start_star}->{target_star} {policy.value:<6} "
                    f"total {to_yi(summary.total_cost.mean):>10,.1f}e  "
                    f"({time.perf_counter() - started:6.1f}s)"
                )
    print(f"\nswept {total} combinations in {time.perf_counter() - started:.1f}s")
    return summaries


def build_meta(
    summaries: Sequence[SimulationSummary],
    target_star: int,
    trials: int,
    seed: int | None,
    percentiles: Sequence[int],
) -> dict:
    """Record what the dataset was generated from, prices included.

    Prices move, so a dataset without the prices behind it cannot be checked
    later. This snapshot makes the numbers reproducible.
    """
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target_star": target_star,
        "trials": trials,
        "seed": seed,
        "percentiles": list(percentiles),
        "combinations": len(summaries),
        "prices": {
            "source": str(volatile_data.SOURCE_PATH),
            "star_scroll_cost": {
                str(star): rules.star_scroll_cost(star) for star in STAR_SCROLL_STARS
            },
            "equipment": [
                {"name": item.name, "level": item.level, "price": item.price}
                for item in volatile_data.CATALOG.values()
            ],
        },
    }


def write_json(summaries: Sequence[SimulationSummary], path: Path, meta: dict) -> None:
    payload = {"meta": meta, "results": [s.to_dict() for s in summaries]}
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote {len(summaries)} results to {path} ({path.stat().st_size:,} bytes)")


def write_csv(
    summaries: Sequence[SimulationSummary],
    path: Path,
    csv_percentiles: Sequence[int] = CSV_PERCENTILES,
) -> None:
    """Flat one-row-per-combination table. Cost columns are in 億."""
    header = [
        "equipment",
        "level",
        "equipment_price_e",
        "start_star",
        "target_star",
        "policy",
        "trials",
        "total_cost_mean_e",
        *[f"total_cost_p{p}_e" for p in csv_percentiles],
        "meso_mean_e",
        "equipment_cost_mean_e",
        "equipment_qty_mean",
        "scrolls_mean",
        "destroys_mean",
        "attempts_mean",
    ]

    # utf-8-sig so Excel on Windows reads the Chinese names correctly.
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for summary in summaries:
            config = summary.config
            writer.writerow(
                [
                    config.equipment_name,
                    config.level,
                    round(to_yi(config.equipment_price), 4),
                    config.start_star,
                    config.target_star,
                    config.repair_policy.value,
                    summary.trials,
                    round(to_yi(summary.total_cost.mean), 4),
                    *[
                        round(to_yi(summary.total_cost.percentiles[p]), 4)
                        for p in csv_percentiles
                    ],
                    round(to_yi(summary.meso.mean), 4),
                    round(to_yi(summary.equipment_cost.mean), 4),
                    round(summary.equipment.mean, 4),
                    round(summary.scrolls.mean, 4),
                    round(summary.destroys.mean, 4),
                    round(summary.attempts.mean, 4),
                ]
            )
    print(f"wrote {len(summaries)} rows to {path} ({path.stat().st_size:,} bytes)")


def print_ranking(summaries: Sequence[SimulationSummary], top_n: int = TOP_N) -> None:
    """Cheapest approaches per equipment, ranked by mean total cost."""
    by_equipment: dict[str, list[SimulationSummary]] = {}
    for summary in summaries:
        name = summary.config.equipment_name or f"level {summary.config.level}"
        by_equipment.setdefault(name, []).append(summary)

    width = 96
    print("\n" + "=" * width)
    print(f"cheapest {top_n} approaches per equipment, by mean total cost")
    print("=" * width)
    header = (
        f"{'equipment':<10}{'lv':>4}{'price':>10}  {'#':<3}{'start':>6}"
        f"{'policy':>8}{'mean':>12}{'p50':>12}{'meso':>11}{'equip$':>11}"
    )
    print(header)
    print("-" * width)
    for name, group in by_equipment.items():
        ranked = sorted(group, key=lambda s: s.total_cost.mean)
        for rank, summary in enumerate(ranked[:top_n], start=1):
            config = summary.config
            label = name if rank == 1 else ""
            level = f"{config.level}" if rank == 1 else ""
            price = (
                f"{to_yi(config.equipment_price):,.1f}e" if rank == 1 else ""
            )
            print(
                f"{label:<10}{level:>4}{price:>10}  {rank:<3}"
                f"{config.start_star:>6}{config.repair_policy.value:>8}"
                f"{to_yi(summary.total_cost.mean):>11,.1f}e"
                f"{to_yi(summary.total_cost.percentiles[50]):>11,.1f}e"
                f"{to_yi(summary.meso.mean):>10,.1f}e"
                f"{to_yi(summary.equipment_cost.mean):>10,.1f}e"
            )
        print("-" * width)


def main(
    target_star: int = TARGET_STAR,
    start_stars: Sequence[int] = START_STARS,
    policies: Sequence[RepairPolicy] = POLICIES,
    trials: int = TRIALS,
    seed: int | None = SEED,
    percentiles: Sequence[int] = PERCENTILES,
    output_dir: Path = OUTPUT_DIR,
    top_n: int = TOP_N,
) -> list[SimulationSummary]:
    output_dir.mkdir(parents=True, exist_ok=True)

    summaries = run_sweep(
        target_star=target_star,
        start_stars=start_stars,
        policies=policies,
        trials=trials,
        seed=seed,
        percentiles=percentiles,
    )

    meta = build_meta(summaries, target_star, trials, seed, percentiles)
    write_json(summaries, output_dir / "simulations.json", meta)
    write_csv(summaries, output_dir / "summary.csv")
    print_ranking(summaries, top_n)
    return summaries


if __name__ == "__main__":
    main(
        target_star=TARGET_STAR,
        start_stars=START_STARS,
        policies=POLICIES,
        trials=TRIALS,
        seed=SEED,
        percentiles=PERCENTILES,
        output_dir=OUTPUT_DIR,
        top_n=TOP_N,
    )
