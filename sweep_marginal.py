"""Sweep the marginal cost of pushing an already-owned item further.

Answers "I already hold a 22 star item - what does 23, 24 or 25 cost me?",
which the from-scratch sweep in ``sweep.py`` cannot: it always starts by buying
a star scroll, and no scroll reaches 22 stars.

Destruction above 22 stars only ever leaves a 22 star trace, so both repair
policies resume from the same place and the runs differ purely in what a
destruction costs:

    FULL   22 star trace repair meso + 4 identical equipment
    TO_12  1 identical equipment + the cost of rebuilding to 22 stars

The rebuild figure is read from the from-scratch dataset - the cheapest mean
total cost of taking that same equipment to 22 stars - so ``sweep.py`` must
have run first. Using the mean as a flat constant keeps the mean total correct
but narrows the upper percentiles, because a rebuild that goes badly is priced
as if it went averagely.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Sequence

from starforce import (
    RepairPolicy,
    RunConfig,
    StartMode,
    load_rebuild_basis,
    simulate,
    volatile_data,
)
from starforce.sim_data_loader import RebuildBasis
from starforce.stats import SimulationSummary
from starforce.units import format_meso, to_yi
from sweep import build_meta, print_ranking, write_csv, write_json

# ---------------------------------------------------------------------------
# SETTINGS - edit these
# ---------------------------------------------------------------------------

#: Stars the item is already at. Must be at or above the rebuild star (22),
#: because that is what the rebuild cost is priced against.
START_STARS: tuple[int, ...] = (22, 23, 24)

#: Stars to push to. Every start below each target is simulated.
TARGET_STARS: tuple[int, ...] = (23, 24, 25)

#: Repair policies to compare.
POLICIES: tuple[RepairPolicy, ...] = (RepairPolicy.FULL, RepairPolicy.TO_12)

#: Trials per combination.
TRIALS = 50_000

#: Fixed so the stored dataset is reproducible.
SEED = 20260726

#: Percentiles recorded in the JSON.
PERCENTILES: tuple[int, ...] = (5, 10, 25, 50, 75, 90, 95, 99)

#: Where the dataset lands. Created if it does not exist.
OUTPUT_DIR = Path(__file__).resolve().parent / "starforce" / "sim_data"

#: How many cheapest approaches to print per equipment and target.
TOP_N = 3

# ---------------------------------------------------------------------------


def build_configs(
    basis: RebuildBasis,
    start_stars: Sequence[int],
    target_stars: Sequence[int],
    policies: Sequence[RepairPolicy],
) -> list[RunConfig]:
    """Every start/target pair with start below target, per equipment and policy."""
    configs = []
    for target_star in target_stars:
        for name in volatile_data.known_names():
            for start_star in start_stars:
                if start_star >= target_star:
                    continue
                for policy in policies:
                    rebuild = (
                        basis.cost(name) if policy is RepairPolicy.TO_12 else 0
                    )
                    configs.append(
                        RunConfig.for_equipment(
                            name,
                            start_star,
                            target_star,
                            repair_policy=policy,
                            start_mode=StartMode.OWNED,
                            rebuild_cost=rebuild,
                        )
                    )
    return configs


def print_rebuild_basis(basis: RebuildBasis) -> None:
    """Show which from-scratch result each rebuild cost came from."""
    print(f"rebuild costs from {basis.source}")
    print(f"  dataset generated_at: {basis.generated_at}")
    print(f"  priced against {basis.star} stars\n")
    for name, option in basis.options.items():
        print(
            f"  {name:<10}{format_meso(option.cost):>12}   "
            f"({option.start_star} start, {option.repair_policy})"
        )
    print()


def main(
    start_stars: Sequence[int] = START_STARS,
    target_stars: Sequence[int] = TARGET_STARS,
    policies: Sequence[RepairPolicy] = POLICIES,
    trials: int = TRIALS,
    seed: int | None = SEED,
    percentiles: Sequence[int] = PERCENTILES,
    output_dir: Path = OUTPUT_DIR,
    top_n: int = TOP_N,
    dataset_path: Path | None = None,
) -> list[SimulationSummary]:
    output_dir.mkdir(parents=True, exist_ok=True)

    basis = load_rebuild_basis(dataset_path)
    print_rebuild_basis(basis)

    configs = build_configs(basis, start_stars, target_stars, policies)
    print(f"{len(configs)} combinations, {trials:,} trials each\n")

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

        last = index == len(configs)
        if last or configs[index].target_star != config.target_star:
            print(f"  -- target {config.target_star} done, writing checkpoint")
            # No breakthrough policy is explored here: starforce.policy solves
            # SCROLL runs only, and an OWNED run's rebuild cost is itself a
            # measured figure. Passing an empty tuple says so, rather than
            # letting build_meta's default report sweep.py's targets - which
            # this dataset does not even carry rows for.
            meta = build_meta(
                summaries,
                target_stars,
                trials,
                seed,
                percentiles,
                breakthrough_targets=(),
            )
            meta["mode"] = "marginal"
            meta["start_stars"] = list(start_stars)
            meta["rebuild_basis"] = {
                "source": str(basis.source),
                "generated_at": basis.generated_at,
                "star": basis.star,
                "costs": {
                    name: {
                        "cost": option.cost,
                        "start_star": option.start_star,
                        "repair_policy": option.repair_policy,
                    }
                    for name, option in basis.options.items()
                },
            }
            write_json(summaries, output_dir / "marginal.json", meta)
            write_csv(summaries, output_dir / "marginal_summary.csv")

    print(f"\nswept {len(configs)} combinations in {time.perf_counter() - started:.1f}s")
    print_ranking(summaries, top_n)
    return summaries


if __name__ == "__main__":
    main(
        start_stars=START_STARS,
        target_stars=TARGET_STARS,
        policies=POLICIES,
        trials=TRIALS,
        seed=SEED,
        percentiles=PERCENTILES,
        output_dir=OUTPUT_DIR,
        top_n=TOP_N,
    )
