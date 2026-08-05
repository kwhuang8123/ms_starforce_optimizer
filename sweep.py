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
from starforce.policy import NONE, sweep_policies
from starforce.static_data import BREAKTHROUGH_SCROLLS, STAR_SCROLL_STARS, breakthrough_id
from starforce.stats import SimulationSummary
from starforce.units import to_yi

# ---------------------------------------------------------------------------
# SETTINGS - edit these
# ---------------------------------------------------------------------------

#: Target stars to sweep, from the cheapest breakpoint worth measuring up to 22.
#:
#: 22 is where this sweep stops. Past it the question changes shape: destruction
#: runs at 18% from 23 stars up and a 23+ star item only ever leaves a 22 star
#: trace, so every destruction costs the whole 22 -> target climb again. That is
#: sweep_marginal.py's question - hold a 22 star item, then price the next star
#: on its own - and it is answered there rather than here.
#:
#: Composing the two ("nothing to 22" plus "22 to 23") gives the right mean but
#: not the right percentiles, because percentiles do not add. Anything past 22
#: therefore has to be read from the marginal dataset, not assembled.
TARGET_STARS: tuple[int, ...] = (17, 18, 19, 20, 21, 22)

#: Starting stars to compare. 10-14 are omitted: those scrolls all cost the
#: same 0.2e and carry no destruction risk, so they barely differ from 15.
#:
#: Not every start star reaches every target - a 20 star item is already past a
#: 19 star target - and build_configs drops the combinations that cannot happen.
START_STARS: tuple[int, ...] = (15, 16, 17, 18, 19, 20)

#: Repair policies to compare.
POLICIES: tuple[RepairPolicy, ...] = (RepairPolicy.FULL, RepairPolicy.TO_12)

#: Targets whose breakthrough scroll policies are explored: all of them.
#:
#: The choice space is far too large to sweep - a 15 to 22 climb has seven
#: decision points - so starforce.policy solves for the cheapest policy instead
#: and names the two or three worth measuring. What it cannot solve is
#: percentiles, which is why those still get simulated here.
#:
#: Derived from TARGET_STARS rather than listed again, so the two cannot drift.
#: A target past 23 would need the solver's model extended first, and
#: starforce.policy raises rather than answering for one - see its _check.
BREAKTHROUGH_TARGETS: tuple[int, ...] = TARGET_STARS

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
    breakthrough_targets: Sequence[int] = BREAKTHROUGH_TARGETS,
) -> list[RunConfig]:
    """Every combination, ordered so each target star finishes before the next.

    A target in ``breakthrough_targets`` is measured once per breakthrough
    policy worth comparing; every other target is measured enhance-only. The
    policies come from starforce.policy, which derives them rather than
    enumerating - see BREAKTHROUGH_TARGETS.

    Start stars at or above the target are skipped rather than rejected: with
    several targets in one sweep the two lists cannot both be exhaustive, and an
    item that is already at 20 stars has nothing to do about a 19 star target.
    """
    configs: list[RunConfig] = []
    for target_star in target_stars:
        for name in volatile_data.known_names():
            item = volatile_data.lookup(name)
            for start_star in start_stars:
                if start_star >= target_star:
                    continue
                for policy in policies:
                    if target_star in breakthrough_targets:
                        chosen = sweep_policies(
                            item.level, start_star, target_star, item.price, policy
                        )
                    else:
                        chosen = [NONE]
                    configs.extend(
                        RunConfig.for_equipment(
                            name,
                            start_star,
                            target_star,
                            repair_policy=policy,
                            breakthrough_policy=breakthrough,
                        )
                        for breakthrough in chosen
                    )
    return configs


def build_meta(
    summaries: Sequence[SimulationSummary],
    target_stars: Sequence[int],
    trials: int,
    seed: int | None,
    percentiles: Sequence[int],
    breakthrough_targets: Sequence[int] = BREAKTHROUGH_TARGETS,
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
        # Which targets had their breakthrough policies explored. Any target not
        # listed was swept enhance-only, and the front end says so rather than
        # presenting the two on the same footing.
        "breakthrough_targets": list(breakthrough_targets),
        "combinations": len(summaries),
        "prices": {
            "source": str(volatile_data.SOURCE_PATH),
            "star_scroll_cost": {
                str(star): rules.star_scroll_cost(star) for star in STAR_SCROLL_STARS
            },
            "breakthrough_scroll_cost": {
                breakthrough_id(cap, success): rules.breakthrough_cost(cap, success)
                for cap, success in BREAKTHROUGH_SCROLLS
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
        "breakthrough",
        "breakthrough_scrolls",
        "rebuild_cost_e",
        "trials",
        "total_cost_mean_e",
        *[f"total_cost_p{p}_e" for p in csv_percentiles],
        "meso_mean_e",
        "equipment_cost_mean_e",
        "rebuild_cost_mean_e",
        "equipment_qty_mean",
        "scrolls_mean",
        "breakthroughs_mean",
        "destroys_mean",
        "attempts_mean",
    ]

    # utf-8-sig so Excel on Windows reads the Chinese names correctly.
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for summary in summaries:
            config = summary.config
            breakthrough = config.breakthrough_policy
            writer.writerow(
                [
                    config.equipment_name,
                    config.level,
                    round(to_yi(config.equipment_price), 4),
                    config.start_star,
                    config.target_star,
                    config.start_mode.value,
                    config.repair_policy.value,
                    "none" if breakthrough is None else breakthrough.name,
                    ""
                    if breakthrough is None
                    else breakthrough.describe().split(": ", 1)[1],
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
                    round(summary.breakthroughs.mean, 4),
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

    width = 118
    for target_star, by_equipment in sorted(by_target.items()):
        print("\n" + "=" * width)
        print(f"target {target_star} stars - cheapest {top_n} approaches per equipment")
        print("=" * width)
        print(
            f"{'equipment':<10}{'lv':>4}{'price':>10}  {'#':<3}{'start':>6}"
            f"{'repair':>8}{'mean':>12}{'p50':>12}{'p95':>12}  breakthrough"
        )
        print("-" * width)
        for name, group in by_equipment.items():
            ranked = sorted(group, key=lambda s: s.total_cost.mean)
            for rank, summary in enumerate(ranked[:top_n], start=1):
                config = summary.config
                label = name if rank == 1 else ""
                level = f"{config.level}" if rank == 1 else ""
                price = f"{to_yi(config.equipment_price):,.1f}e" if rank == 1 else ""
                breakthrough = config.breakthrough_policy
                shown = "-" if breakthrough is None else breakthrough.describe()
                print(
                    f"{label:<10}{level:>4}{price:>10}  {rank:<3}"
                    f"{config.start_star:>6}{config.repair_policy.value:>8}"
                    f"{to_yi(summary.total_cost.mean):>11,.1f}e"
                    f"{to_yi(summary.total_cost.percentiles[50]):>11,.1f}e"
                    f"{to_yi(summary.total_cost.percentiles[95]):>11,.1f}e"
                    f"  {shown}"
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
    base = len(names) * len(start_stars) * len(policies) * len(target_stars)
    print(
        f"{len(names)} equipment x {len(start_stars)} start stars x "
        f"{len(policies)} repair policies x {len(target_stars)} targets = {base} "
        f"combinations, expanded to {len(configs)} by the breakthrough policies "
        f"worth comparing for targets {list(BREAKTHROUGH_TARGETS)}, "
        f"{trials:,} trials each\n"
    )

    summaries: list[SimulationSummary] = []
    started = time.perf_counter()
    for index, config in enumerate(configs, start=1):
        summary = simulate(config, trials=trials, seed=seed, percentiles=percentiles)
        summaries.append(summary)
        breakthrough = config.breakthrough_policy
        print(
            f"[{index:>4}/{len(configs)}] {config.equipment_name:<6} "
            f"{config.start_star}->{config.target_star} "
            f"{config.repair_policy.value:<6} "
            f"{('none' if breakthrough is None else breakthrough.name):<8}"
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
