"""Single-run star force simulation.

The V272 rules make one attempt memoryless: failure always maintains (star
decay was removed) and there is no guaranteed-success-after-two-failures
mechanic, so a run is fully described by the current star plus the running
totals below.

Every run begins by consuming a star scroll for ``start_star``; scrolls exist
for 10 through 20 stars, which is what bounds ``start_star``.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from . import data, rules


class RepairPolicy(Enum):
    """What to do with the trace left behind by a destroyed item."""

    #: Pay meso plus identical equipment to restore the trace's own star force.
    FULL = "full"
    #: Pay a single identical equipment to restore the item to 12 stars, then
    #: spend another ``start_star`` scroll to climb back to where the run began.
    TO_12 = "to_12"


@dataclass(frozen=True)
class RunConfig:
    """Inputs for one simulated climb from ``start_star`` to ``target_star``.

    ``start_star`` doubles as the star scroll used to set the item up, both at
    the beginning of the run and after every 12 star repair.
    """

    level: int
    start_star: int
    target_star: int
    repair_policy: RepairPolicy = RepairPolicy.FULL

    def __post_init__(self) -> None:
        rules.check_level(self.level)
        rules.check_start_star(self.start_star)

        cap = rules.max_target_star(self.level)
        if self.target_star <= self.start_star:
            raise ValueError(
                f"target_star must exceed start_star, got start_star={self.start_star} "
                f"and target_star={self.target_star}"
            )
        if self.target_star > cap:
            raise ValueError(
                f"level {self.level} cannot be simulated past {cap} stars, "
                f"got target_star={self.target_star}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "start_star": self.start_star,
            "target_star": self.target_star,
            "repair_policy": self.repair_policy.value,
        }


@dataclass
class RunResult:
    """Totals for one completed climb."""

    total_meso: int = 0
    #: Identical equipment pieces consumed by repairs.
    equipment_used: int = 0
    #: Star scrolls consumed, including the one that starts the run.
    scrolls_used: int = 0
    attempts: int = 0
    destroys: int = 0
    #: Attempts made from each star, keyed by the star attempted from.
    attempts_by_star: dict[int, int] = field(default_factory=dict)


def simulate_once(config: RunConfig, rng: random.Random) -> RunResult:
    """Run one climb to ``config.target_star`` and return its totals."""
    result = RunResult()
    scroll_cost = rules.star_scroll_cost(config.start_star)

    result.total_meso += scroll_cost
    result.scrolls_used += 1
    star = config.start_star

    while star < config.target_star:
        result.total_meso += rules.enhance_cost(config.level, star)
        result.attempts += 1
        result.attempts_by_star[star] = result.attempts_by_star.get(star, 0) + 1

        success, destroy, _ = rules.enhance_rates(star)
        roll = rng.randrange(data.RATE_BASIS)

        if roll < success:
            star += 1
        elif roll < success + destroy:
            result.destroys += 1
            star = _repair(config, star, result, scroll_cost)
        # Otherwise the attempt maintained: star is unchanged.

    return result


def _repair(
    config: RunConfig, destroyed_star: int, result: RunResult, scroll_cost: int
) -> int:
    """Charge the repair for a destruction at ``destroyed_star``, return the new star."""
    trace = rules.trace_star(destroyed_star)

    if config.repair_policy is RepairPolicy.FULL:
        meso, equipment = rules.full_repair(config.level, trace)
        result.total_meso += meso
        result.equipment_used += equipment
        return trace

    meso, equipment = rules.cheap_repair()
    result.total_meso += meso
    result.equipment_used += equipment
    star = rules.CHEAP_REPAIR_STAR

    # A 12 star repair lands below where the run started, so another start_star
    # scroll goes back on. A run started at 10 or 11 stars is already past 12.
    if config.start_star > star:
        result.total_meso += scroll_cost
        result.scrolls_used += 1
        star = config.start_star

    return star
