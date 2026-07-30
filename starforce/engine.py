"""Single-run star force simulation.

The V272 rules make one attempt memoryless: failure always maintains (star
decay was removed) and there is no guaranteed-success-after-two-failures
mechanic, so a run is fully described by the current star plus the running
totals below.

A run begins one of two ways, per :class:`StartMode`. In ``SCROLL`` mode it
buys a star scroll for ``start_star``, which is why that mode bounds
``start_star`` to the 10-20 stars scrolls exist for. In ``OWNED`` mode the item
is already at ``start_star`` and nothing is spent to get there, which is how a
"I already have a 22 star item, what does 25 cost me?" question is asked.

Cost is tracked in three streams. ``total_meso`` is what leaves the wallet -
enhancement fees, repair meso, star scrolls. ``equipment_cost`` values the
identical equipment that repairs consume. ``rebuild_cost`` covers rebuilding an
``OWNED`` run back to 22 stars after a 12 star repair. The base item the run
starts from is not counted: it is a constant across every strategy being
compared.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from . import rules, static_data, volatile_data

if TYPE_CHECKING:
    from .policy import BreakthroughPolicy


class RepairPolicy(Enum):
    """What to do with the trace left behind by a destroyed item."""

    #: Pay meso plus identical equipment to restore the trace's own star force.
    FULL = "full"
    #: Pay a single identical equipment to restore the item to 12 stars, then
    #: get back up: in SCROLL mode via another ``start_star`` scroll, in OWNED
    #: mode by paying ``rebuild_cost`` to return to 22 stars.
    TO_12 = "to_12"


class StartMode(Enum):
    """How the run reaches ``start_star``."""

    #: Buy a star scroll for ``start_star``. Bounds it to 10-20.
    SCROLL = "scroll"
    #: The item is already there. Nothing is spent reaching it.
    OWNED = "owned"


@dataclass(frozen=True)
class RunConfig:
    """Inputs for one simulated climb from ``start_star`` to ``target_star``.

    In ``SCROLL`` mode ``start_star`` doubles as the star scroll used to set the
    item up, both at the beginning of the run and after every 12 star repair.

    ``equipment_price`` values each piece a repair consumes. Build the config
    with :meth:`for_equipment` to fill it, and the level, from the catalogue.
    """

    level: int
    start_star: int
    target_star: int
    repair_policy: RepairPolicy = RepairPolicy.FULL
    start_mode: StartMode = StartMode.SCROLL
    rebuild_cost: int = 0
    equipment_name: str | None = None
    equipment_price: int = 0
    #: Which stars buy a breakthrough scroll instead of enhancing. None enhances
    #: throughout, which is what every run did before scrolls existed. Built by
    #: starforce.policy, which is imported only for typing: it depends on this
    #: module, so importing it here would close a cycle.
    breakthrough_policy: "BreakthroughPolicy | None" = None

    def __post_init__(self) -> None:
        rules.check_level(self.level)

        if self.start_mode is StartMode.SCROLL:
            rules.check_start_star(self.start_star)
        elif self.start_star < 0:
            raise ValueError(f"start_star must not be negative, got {self.start_star}")

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
        if self.equipment_price < 0:
            raise ValueError(
                f"equipment_price must not be negative, got {self.equipment_price}"
            )

        self._check_rebuild_cost()
        self._check_breakthrough_policy()

    def _check_breakthrough_policy(self) -> None:
        """A policy must only name stars this run actually climbs through."""
        if self.breakthrough_policy is None:
            return
        outside = [
            star
            for star in self.breakthrough_policy.stars
            if not self.start_star <= star < self.target_star
        ]
        if outside:
            raise ValueError(
                f"breakthrough policy {self.breakthrough_policy.name!r} names "
                f"scrolls for stars {outside}, which a {self.start_star} -> "
                f"{self.target_star} run never enhances from"
            )

    def _check_rebuild_cost(self) -> None:
        """``rebuild_cost`` applies to exactly one combination, and is required there."""
        needed = (
            self.start_mode is StartMode.OWNED
            and self.repair_policy is RepairPolicy.TO_12
        )
        if not needed:
            if self.rebuild_cost:
                raise ValueError(
                    "rebuild_cost only applies to an OWNED run repairing to 12 stars, "
                    f"got start_mode={self.start_mode.value} "
                    f"and repair_policy={self.repair_policy.value}"
                )
            return

        if self.rebuild_cost <= 0:
            raise ValueError(
                "an OWNED run repairing to 12 stars needs a positive rebuild_cost: "
                f"the cost of climbing back to {rules.REBUILD_STAR} stars"
            )
        if self.start_star < rules.REBUILD_STAR:
            raise ValueError(
                f"rebuild_cost is priced against {rules.REBUILD_STAR} stars, so an "
                f"OWNED run repairing to 12 stars must start at or above it, "
                f"got start_star={self.start_star}"
            )

    @classmethod
    def for_equipment(
        cls,
        name: str,
        start_star: int,
        target_star: int,
        repair_policy: RepairPolicy = RepairPolicy.FULL,
        start_mode: StartMode = StartMode.SCROLL,
        rebuild_cost: int = 0,
        breakthrough_policy: "BreakthroughPolicy | None" = None,
    ) -> RunConfig:
        """Build a config from a catalogue name, alias, or digit variant."""
        item = volatile_data.lookup(name)
        return cls(
            level=item.level,
            start_star=start_star,
            target_star=target_star,
            repair_policy=repair_policy,
            start_mode=start_mode,
            rebuild_cost=rebuild_cost,
            equipment_name=item.name,
            equipment_price=item.price,
            breakthrough_policy=breakthrough_policy,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "start_star": self.start_star,
            "target_star": self.target_star,
            "repair_policy": self.repair_policy.value,
            "start_mode": self.start_mode.value,
            "rebuild_cost": self.rebuild_cost,
            "equipment_name": self.equipment_name,
            "equipment_price": self.equipment_price,
            "breakthrough_policy": (
                None
                if self.breakthrough_policy is None
                else self.breakthrough_policy.to_dict()
            ),
        }


@dataclass
class RunResult:
    """Totals for one completed climb."""

    #: Enhancement fees, repair meso and star scrolls.
    total_meso: int = 0
    #: Identical equipment pieces consumed by repairs.
    equipment_used: int = 0
    #: ``equipment_used`` valued at the config's equipment price.
    equipment_cost: int = 0
    #: Climbing an OWNED run back to 22 stars after a 12 star repair.
    rebuild_cost: int = 0
    #: Star scrolls consumed, including the one that starts a SCROLL run.
    scrolls_used: int = 0
    #: Breakthrough scrolls consumed, win or lose.
    breakthroughs_used: int = 0
    attempts: int = 0
    destroys: int = 0
    #: Attempts made from each star, keyed by the star attempted from.
    attempts_by_star: dict[int, int] = field(default_factory=dict)
    #: Breakthrough scrolls consumed, keyed by scroll id. Each has its own
    #: price, so re-pricing a run needs them counted apart rather than totalled.
    breakthroughs_by_scroll: dict[str, int] = field(default_factory=dict)

    @property
    def total_cost(self) -> int:
        """Meso spent, plus the equipment burned, plus any rebuilds."""
        return self.total_meso + self.equipment_cost + self.rebuild_cost


def simulate_once(config: RunConfig, rng: random.Random) -> RunResult:
    """Run one climb to ``config.target_star`` and return its totals."""
    result = RunResult()
    star = config.start_star

    scroll_cost = 0
    if config.start_mode is StartMode.SCROLL:
        scroll_cost = rules.star_scroll_cost(config.start_star)
        result.total_meso += scroll_cost
        result.scrolls_used += 1

    policy = config.breakthrough_policy

    while star < config.target_star:
        scroll = None if policy is None else policy.scroll_at(star)
        if scroll is not None:
            star = _breakthrough(scroll, star, result, rng)
            continue

        result.total_meso += rules.enhance_cost(config.level, star)
        result.attempts += 1
        result.attempts_by_star[star] = result.attempts_by_star.get(star, 0) + 1

        success, destroy, _ = rules.enhance_rates(star)
        roll = rng.randrange(static_data.RATE_BASIS)

        if roll < success:
            star += 1
        elif roll < success + destroy:
            result.destroys += 1
            star = _repair(config, star, result, scroll_cost)
        # Otherwise the attempt maintained: star is unchanged.

    return result


def _breakthrough(
    scroll: tuple[int, int], star: int, result: RunResult, rng: random.Random
) -> int:
    """Buy one breakthrough scroll and take its shot, returning the new star.

    Paid for whether it lands or not, and a miss changes nothing else - there is
    no destruction on this path, so no repair can follow it. Deliberately not
    counted as an attempt: ``attempts`` and ``attempts_by_star`` describe
    enhancement, which is what the published rate tables are about.
    """
    cap_star, success = scroll
    result.total_meso += rules.breakthrough_cost(cap_star, success)
    result.breakthroughs_used += 1
    key = static_data.breakthrough_id(cap_star, success)
    result.breakthroughs_by_scroll[key] = result.breakthroughs_by_scroll.get(key, 0) + 1

    if rng.randrange(static_data.RATE_BASIS) < success:
        return star + 1
    return star


def _repair(
    config: RunConfig, destroyed_star: int, result: RunResult, scroll_cost: int
) -> int:
    """Charge the repair for a destruction at ``destroyed_star``, return the new star."""
    trace = rules.trace_star(destroyed_star)

    if config.repair_policy is RepairPolicy.FULL:
        meso, equipment = rules.full_repair(config.level, trace)
        result.total_meso += meso
        result.equipment_used += equipment
        result.equipment_cost += equipment * config.equipment_price
        return trace

    meso, equipment = rules.cheap_repair()
    result.total_meso += meso
    result.equipment_used += equipment
    result.equipment_cost += equipment * config.equipment_price

    if config.start_mode is StartMode.OWNED:
        # No scroll reaches 22 stars, so the way back is to rebuild: the flat
        # cost of taking a fresh item to 22 the cheapest known way.
        result.rebuild_cost += config.rebuild_cost
        return rules.REBUILD_STAR

    star = rules.CHEAP_REPAIR_STAR
    # A 12 star repair lands below where the run started, so another start_star
    # scroll goes back on - the same scroll the run opened with. The lowest
    # scroll is 15 stars, so this is always true in SCROLL mode; the check is
    # what would keep it correct if scrolls below 12 ever existed again.
    if config.start_star > star:
        result.total_meso += scroll_cost
        result.scrolls_used += 1
        star = config.start_star
    return star
