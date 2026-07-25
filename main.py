"""Editable entry point: adjust the SETTINGS block below, then run this file.

VS Code runs this straight from the repo root, so ``import starforce`` resolves
with no extra configuration. Every setting is also a ``main()`` keyword, so
``main(equipment="控制核心", runs=[(19, 25)])`` works without editing the file.

Prices come from ``data/volatile.json``; edit that file to reprice scrolls or
equipment without touching code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from starforce import RepairPolicy, RunConfig, rules, simulate, volatile_data
from starforce.stats import SimulationSummary
from starforce.units import format_meso, to_yi

# ---------------------------------------------------------------------------
# SETTINGS - edit these
# ---------------------------------------------------------------------------

#: Equipment name, alias, or digit variant, e.g. "頂培" or "永恆上4".
#: Its level and price come from data/volatile.json. Set to None to fall back
#: to LEVEL below and value the equipment repairs consume at zero.
EQUIPMENT: str | None = "頂培"

#: Item level, used only when EQUIPMENT is None.
#: Only 130, 140, 150, 160, 200 and 250 are published.
LEVEL = 150

#: (start_star, target_star) pairs to simulate.
#: start_star must be 10-20; target_star must exceed it and stay within the
#: level cap (30 stars, or 15 for level 130).
RUNS: tuple[tuple[int, int], ...] = (
    (15, 22),
    (17, 22),
    (19, 22),
)

#: Repair policies to compare for every run above.
#: FULL  = pay equipment + meso, item returns to the star it was destroyed at.
#: TO_12 = pay one equipment, item returns to 12 stars, then a start_star
#:         scroll goes back on.
POLICIES: tuple[RepairPolicy, ...] = (RepairPolicy.FULL, RepairPolicy.TO_12)

#: Trials per configuration.
TRIALS = 100_000

#: Percentiles to report.
PERCENTILES: tuple[int, ...] = (25, 50, 75, 90)

#: Print the per-star attempt breakdown under each run.
SHOW_ATTEMPTS_BY_STAR = True

#: Path to dump raw results as JSON, or None to skip.
EXPORT_JSON: Path | None = None

# ---------------------------------------------------------------------------


def build_configs(
    equipment: str | None,
    level: int,
    runs: Sequence[tuple[int, int]],
    policies: Sequence[RepairPolicy],
) -> list[RunConfig]:
    """One config per runs x policies combination."""
    configs = []
    for start_star, target_star in runs:
        for policy in policies:
            if equipment is None:
                configs.append(
                    RunConfig(
                        level=level,
                        start_star=start_star,
                        target_star=target_star,
                        repair_policy=policy,
                    )
                )
            else:
                configs.append(
                    RunConfig.for_equipment(
                        equipment, start_star, target_star, repair_policy=policy
                    )
                )
    return configs


def print_prices(equipment: str | None, runs: Sequence[tuple[int, int]]) -> None:
    """Show the volatile prices this run depends on."""
    print(f"volatile prices from {volatile_data.SOURCE_PATH}")
    if equipment is None:
        print("  equipment  (none - repair equipment valued at 0)")
    else:
        item = volatile_data.lookup(equipment)
        print(
            f"  equipment  {item.name}  level {item.level}  "
            f"{format_meso(item.price)}"
        )
    for star in sorted({start for start, _ in runs}):
        print(
            f"  {star:>2} star scroll  {to_yi(rules.star_scroll_cost(star)):>10,.2f}e"
        )
    print()


def print_comparison(
    results: Sequence[tuple[RunConfig, SimulationSummary]],
    percentiles: Sequence[int],
) -> None:
    """One row per configuration. Percentiles are of total cost, meso in 億."""
    header = (
        f"{'run':<10}{'policy':<8}"
        + "".join(f"{f'p{p}':>12}" for p in percentiles)
        + f"{'mean':>12}{'meso':>12}{'equip$':>12}{'qty':>7}{'destroy':>9}{'try':>8}"
    )
    print("=" * len(header))
    print("total cost percentiles")
    print(header)
    print("-" * len(header))
    for config, summary in results:
        row = f"{f'{config.start_star}->{config.target_star}':<10}"
        row += f"{config.repair_policy.value:<8}"
        row += "".join(
            f"{to_yi(summary.total_cost.percentiles[p]):>11,.1f}e" for p in percentiles
        )
        row += f"{to_yi(summary.total_cost.mean):>11,.1f}e"
        row += f"{to_yi(summary.meso.mean):>11,.1f}e"
        row += f"{to_yi(summary.equipment_cost.mean):>11,.1f}e"
        row += f"{summary.equipment.mean:>7.2f}{summary.destroys.mean:>9.2f}"
        row += f"{summary.attempts.mean:>8.1f}"
        print(row)
    print("=" * len(header))


def main(
    equipment: str | None = EQUIPMENT,
    level: int = LEVEL,
    runs: Sequence[tuple[int, int]] = RUNS,
    policies: Sequence[RepairPolicy] = POLICIES,
    trials: int = TRIALS,
    percentiles: Sequence[int] = PERCENTILES,
    show_attempts_by_star: bool = SHOW_ATTEMPTS_BY_STAR,
    export_json: Path | None = EXPORT_JSON,
) -> list[tuple[RunConfig, SimulationSummary]]:
    """Simulate every ``runs`` x ``policies`` combination and print the results."""
    configs = build_configs(equipment, level, runs, policies)

    print(f"level {configs[0].level}   trials={trials:,}\n")
    print_prices(equipment, runs)

    results: list[tuple[RunConfig, SimulationSummary]] = []
    for config in configs:
        summary = simulate(config, trials=trials, percentiles=percentiles)
        results.append((config, summary))

        print(summary.report(percentiles))
        if show_attempts_by_star:
            breakdown = "  ".join(
                f"{star}:{value:.1f}"
                for star, value in sorted(summary.mean_attempts_by_star.items())
            )
            print(f"  by star     {breakdown}")
        print()

    print_comparison(results, percentiles)

    if export_json is not None:
        payload = [summary.to_dict() for _, summary in results]
        export_json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nwrote {len(payload)} results to {export_json}")

    return results


if __name__ == "__main__":
    main(
        equipment=EQUIPMENT,
        level=LEVEL,
        runs=RUNS,
        policies=POLICIES,
        trials=TRIALS,
        percentiles=PERCENTILES,
        show_attempts_by_star=SHOW_ATTEMPTS_BY_STAR,
        export_json=EXPORT_JSON,
    )
