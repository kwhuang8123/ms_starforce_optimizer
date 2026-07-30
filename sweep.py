"""Sweep every equipment x start star x repair policy combination to each target.

Writes two files into ``starforce/sim_data``: the full summaries as JSON, and a
flat CSV for spreadsheet analysis. Re-run this after editing
``data/volatile.json`` to refresh the dataset against new prices.

Both files are rewritten after every target star finishes, so interrupting a
long run still leaves the targets that already completed on disk.
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

#: Target stars to sweep. Cost climbs steeply past 22: destruction runs at 18%
#: from 23 stars up, and a 23+ star item only ever leaves a 22 star trace, so
#: every destruction there costs the whole 22 -> target climb again.
#:
#: 24 stars is deliberately not swept from scratch. It is by far the dearest
#: combination to measure - the 15 -> 24 climb repairing to 12 stars averages 972
#: attempts per trial, against 40 for 15 -> 22 - and the question it answers is
#: better answered by sweep_marginal.py: reach 22, then price 22 -> 24 on its
#: own. Note that composing the two gives the right mean but not the right
#: percentiles, because percentiles do not add.
TARGET_STARS: tuple[int, ...] = (22, 23)

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

#: How many cheapest approaches to print per equipment and target.
TOP_N = 3

# ---------------------------------------------------------------------------


def build_configs(
    target_stars: Sequence[int],
    start_stars: Sequence[int],
    policies: Sequence[RepairPolicy],
) -> list[RunConfig]:
    """Every combination, ordered so each target star finishes before the next."""
    return [
        RunConfig.for_equipment(name, start_star, target_star, repair_policy=policy)
        for target_star in target_stars
        for name in volatile_data.known_names()
        for start_star in start_stars
        for policy in policies
    ]


def build_meta(
    summaries: Sequence[SimulationSummary],
    target_stars: Sequence[int],
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
        "target_stars": list(target_stars),
        "targets_completed": sorted({s.config.target_star for s in summaries}),
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
    print(f"  wrote {len(summaries)} results to {path.name} ({path.stat().st_size:,} bytes)")


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
        "start_mode",
        "policy",
        "rebuild_cost_e",
        "trials",
        "total_cost_mean_e",
        *[f"total_cost_p{p}_e" for p in csv_percentiles],
        "meso_mean_e",
        "equipment_cost_mean_e",
        "rebuild_cost_mean_e",
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
                    config.start_mode.value,
                    config.repair_policy.value,
                    round(to_yi(config.rebuild_cost), 4),
                    summary.trials,
                    round(to_yi(summary.total_cost.mean), 4),
                    *[
                        round(to_yi(summary.total_cost.percentiles[p]), 4)
                        for p in csv_percentiles
                    ],
                    round(to_yi(summary.meso.mean), 4),
                    round(to_yi(summary.equipment_cost.mean), 4),
                    round(to_yi(summary.rebuild_cost.mean), 4),
                    round(summary.equipment.mean, 4),
                    round(summary.scrolls.mean, 4),
                    round(summary.destroys.mean, 4),
                    round(summary.attempts.mean, 4),
                ]
            )
    print(f"  wrote {len(summaries)} rows to {path.name} ({path.stat().st_size:,} bytes)")


def print_ranking(summaries: Sequence[SimulationSummary], top_n: int = TOP_N) -> None:
    """Cheapest approaches per equipment, ranked by mean total cost, per target."""
    by_target: dict[int, dict[str, list[SimulationSummary]]] = {}
    for summary in summaries:
        config = summary.config
        name = config.equipment_name or f"level {config.level}"
        by_target.setdefault(config.target_star, {}).setdefault(name, []).append(summary)

    width = 96
    for target_star, by_equipment in sorted(by_target.items()):
        print("\n" + "=" * width)
        print(f"target {target_star} stars - cheapest {top_n} approaches per equipment")
        print("=" * width)
        print(
            f"{'equipment':<10}{'lv':>4}{'price':>10}  {'#':<3}{'start':>6}"
            f"{'policy':>8}{'mean':>12}{'p50':>12}{'meso':>11}{'equip$':>11}"
        )
        print("-" * width)
        for name, group in by_equipment.items():
            ranked = sorted(group, key=lambda s: s.total_cost.mean)
            for rank, summary in enumerate(ranked[:top_n], start=1):
                config = summary.config
                label = name if rank == 1 else ""
                level = f"{config.level}" if rank == 1 else ""
                price = f"{to_yi(config.equipment_price):,.1f}e" if rank == 1 else ""
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
    target_stars: Sequence[int] = TARGET_STARS,
    start_stars: Sequence[int] = START_STARS,
    policies: Sequence[RepairPolicy] = POLICIES,
    trials: int = TRIALS,
    seed: int | None = SEED,
    percentiles: Sequence[int] = PERCENTILES,
    output_dir: Path = OUTPUT_DIR,
    top_n: int = TOP_N,
) -> list[SimulationSummary]:
    output_dir.mkdir(parents=True, exist_ok=True)

    configs = build_configs(target_stars, start_stars, policies)
    names = volatile_data.known_names()
    print(
        f"{len(names)} equipment x {len(start_stars)} start stars x "
        f"{len(policies)} policies x {len(target_stars)} targets = "
        f"{len(configs)} combinations, {trials:,} trials each\n"
    )

    summaries: list[SimulationSummary] = []
    started = time.perf_counter()
    for index, config in enumerate(configs, start=1):
        summary = simulate(config, trials=trials, seed=seed, percentiles=percentiles)
        summaries.append(summary)
        print(
            f"[{index:>3}/{len(configs)}] {config.equipment_name:<6} "
            f"{config.start_star}->{config.target_star} "
            f"{config.repair_policy.value:<6} "
            f"total {to_yi(summary.total_cost.mean):>10,.1f}e  "
            f"({time.perf_counter() - started:7.1f}s)"
        )

        # Checkpoint whenever the target star is about to change, so a long run
        # that gets interrupted still leaves the finished targets on disk.
        last = index == len(configs)
        if last or configs[index].target_star != config.target_star:
            print(f"  -- target {config.target_star} done, writing checkpoint")
            meta = build_meta(summaries, target_stars, trials, seed, percentiles)
            write_json(summaries, output_dir / "simulations.json", meta)
            write_csv(summaries, output_dir / "summary.csv")

    print(f"\nswept {len(configs)} combinations in {time.perf_counter() - started:.1f}s")
    print_ranking(summaries, top_n)
    return summaries


if __name__ == "__main__":
    main(
        target_stars=TARGET_STARS,
        start_stars=START_STARS,
        policies=POLICIES,
        trials=TRIALS,
        seed=SEED,
        percentiles=PERCENTILES,
        output_dir=OUTPUT_DIR,
        top_n=TOP_N,
    )
