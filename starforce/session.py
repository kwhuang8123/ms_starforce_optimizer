"""Hand-driven star force enhancement, one action at a time.

:mod:`starforce.engine` answers "what does this strategy cost on average" by
running a whole climb with every decision fixed up front. This module answers a
different question: "what happened to *my* item". Each call does exactly one
thing - one enhancement attempt, one scroll of either kind, one repair - and
appends a :class:`LogEntry` describing it, so the caller decides what to do
next with the outcome in hand.

A session holds no I/O of its own. ``play.py`` is a thin shell around it, and
the planned GitHub Pages front end reads :meth:`Session.to_dict`, which is plain
JSON-serialisable data in the same shape :mod:`starforce.stats` already emits.

Totals accumulate in a :class:`starforce.engine.RunResult` so a hand-driven run
and a simulated one report the same fields. ``rebuild_cost`` stays zero here:
climbing back after a cheap repair is something the operator does step by step,
so it lands in ``total_meso`` and ``equipment_cost`` like any other action.

The item the session starts from is not charged, matching the engine: it is a
constant across every strategy being compared.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from . import rules, static_data, volatile_data
from .engine import RepairPolicy, RunResult
from .units import format_meso, to_yi


class Action(Enum):
    """What a log entry did."""

    ENHANCE = "enhance"
    SCROLL = "scroll"
    BREAKTHROUGH = "breakthrough"
    REPAIR_FULL = "repair_full"
    REPAIR_TO_12 = "repair_to_12"


class Outcome(Enum):
    """How an attempt landed. Only enhancing and breakthrough scrolls have one.

    A breakthrough scroll never destroys, so it only ever reports SUCCESS or
    MAINTAIN.
    """

    SUCCESS = "success"
    MAINTAIN = "maintain"
    DESTROY = "destroy"


@dataclass(frozen=True)
class LogEntry:
    """One recorded action: what it did, what it cost, where it left the item."""

    index: int
    action: str
    star_before: int
    star_after: int
    #: ``success`` / ``maintain`` / ``destroy``, or None for a scroll or repair.
    outcome: str | None
    #: Meso that left the wallet for this action.
    meso: int
    #: Identical equipment pieces this action consumed.
    equipment_used: int
    #: ``equipment_used`` valued at the session's equipment price.
    equipment_cost: int
    #: Session total cost once this action was charged.
    total_cost_after: int

    @property
    def cost(self) -> int:
        """What this single action cost, meso plus the equipment it burned."""
        return self.meso + self.equipment_cost

    def describe(self) -> str:
        """One line for a console log, with every meso figure in 億."""
        return (
            f"{self.index:>3}  {self.action:<13}"
            f"{self.star_before:>3} -> {self.star_after:<4}"
            f"{self.outcome or '':<10}"
            f"{format_meso(self.cost):>14}"
            f"   total {format_meso(self.total_cost_after):>14}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "action": self.action,
            "star_before": self.star_before,
            "star_after": self.star_after,
            "outcome": self.outcome,
            "meso": self.meso,
            "meso_yi": to_yi(self.meso),
            "equipment_used": self.equipment_used,
            "equipment_cost": self.equipment_cost,
            "equipment_cost_yi": to_yi(self.equipment_cost),
            "cost": self.cost,
            "cost_yi": to_yi(self.cost),
            "total_cost_after": self.total_cost_after,
            "total_cost_after_yi": to_yi(self.total_cost_after),
        }


@dataclass
class Session:
    """One item being enhanced by hand, plus everything spent on it so far.

    ``star`` is where the item stands. While ``destroyed`` is true the item is a
    trace and ``star`` is the trace's star force: nothing but :meth:`repair` is
    allowed until it is restored.

    Build it with :meth:`for_equipment` to price repairs from the catalogue.
    Leaving ``equipment_price`` at zero values repair equipment at nothing,
    which is the same fallback the engine offers.
    """

    level: int
    #: Where the item already is. Nothing is charged to reach it.
    start_star: int = 0
    equipment_name: str | None = None
    equipment_price: int = 0
    seed: int | None = None

    star: int = field(init=False)
    destroyed: bool = field(default=False, init=False)
    log: list[LogEntry] = field(default_factory=list, init=False)
    totals: RunResult = field(default_factory=RunResult, init=False)
    rng: random.Random = field(init=False)

    def __post_init__(self) -> None:
        rules.check_level(self.level)

        cap = rules.max_target_star(self.level)
        if not 0 <= self.start_star <= cap:
            raise ValueError(
                f"start_star must be between 0 and {cap} for level {self.level}, "
                f"got {self.start_star}"
            )
        if self.equipment_price < 0:
            raise ValueError(
                f"equipment_price must not be negative, got {self.equipment_price}"
            )

        self.star = self.start_star
        self.rng = random.Random(self.seed)

    @classmethod
    def for_equipment(
        cls, name: str, start_star: int = 0, seed: int | None = None
    ) -> Session:
        """Build a session from a catalogue name, alias, or digit variant."""
        item = volatile_data.lookup(name)
        return cls(
            level=item.level,
            start_star=start_star,
            equipment_name=item.name,
            equipment_price=item.price,
            seed=seed,
        )

    @property
    def max_star(self) -> int:
        """Highest star this session will enhance to, per the level's cap."""
        return rules.max_target_star(self.level)

    @property
    def total_cost(self) -> int:
        """Meso spent plus the equipment burned, across every action so far."""
        return self.totals.total_cost

    def enhance(self) -> LogEntry:
        """Make one attempt from the current star and charge its fee."""
        if self.destroyed:
            raise ValueError(
                f"the item is destroyed: repair the {self.star} star trace "
                f"before enhancing again"
            )
        if self.star >= self.max_star:
            raise ValueError(
                f"level {self.level} cannot be enhanced past {self.max_star} stars, "
                f"and the item is already at {self.star}"
            )

        star_before = self.star
        meso = rules.enhance_cost(self.level, star_before)
        self.totals.total_meso += meso
        self.totals.attempts += 1
        self.totals.attempts_by_star[star_before] = (
            self.totals.attempts_by_star.get(star_before, 0) + 1
        )

        success, destroy, _ = rules.enhance_rates(star_before)
        roll = self.rng.randrange(static_data.RATE_BASIS)

        if roll < success:
            outcome = Outcome.SUCCESS
            self.star = star_before + 1
        elif roll < success + destroy:
            outcome = Outcome.DESTROY
            self.totals.destroys += 1
            self.destroyed = True
            # Destruction above 22 stars still leaves a 22 star trace.
            self.star = rules.trace_star(star_before)
        else:
            outcome = Outcome.MAINTAIN

        return self._record(Action.ENHANCE, star_before, meso, 0, outcome=outcome)

    def use_scroll(self, star: int) -> LogEntry:
        """Buy the ``star`` star scroll and set the item to that star force.

        A scroll may only raise the item: applying one at or below the current
        star would throw the scroll away, so it raises instead.
        """
        if self.destroyed:
            raise ValueError(
                f"the item is destroyed: repair the {self.star} star trace "
                f"before using a star scroll"
            )
        rules.check_start_star(star)
        if star <= self.star:
            raise ValueError(
                f"a star scroll may only raise the item, but it is already at "
                f"{self.star} stars and the scroll sets {star}"
            )
        if star > self.max_star:
            raise ValueError(
                f"level {self.level} cannot be taken past {self.max_star} stars, "
                f"so the {star} star scroll does not apply"
            )

        star_before = self.star
        meso = rules.star_scroll_cost(star)
        self.totals.total_meso += meso
        self.totals.scrolls_used += 1
        self.star = star

        return self._record(Action.SCROLL, star_before, meso, 0)

    def use_breakthrough(self, cap_star: int, success: int) -> LogEntry:
        """Buy one breakthrough scroll and take its single shot at +1 star.

        The scroll is paid for whether it lands or not, and a miss leaves the
        item exactly where it was - there is no destruction on this path, so a
        failed attempt needs no repair.

        ``cap_star`` is the star the scroll refuses to go past, so the scroll is
        usable from anywhere below it, not only from ``cap_star - 1``.
        """
        if self.destroyed:
            raise ValueError(
                f"the item is destroyed: repair the {self.star} star trace "
                f"before using a breakthrough scroll"
            )
        rules.check_breakthrough(cap_star, success)
        if self.star + 1 > cap_star:
            raise ValueError(
                f"this scroll will not take an item past {cap_star} stars, "
                f"and it is already at {self.star}"
            )
        if self.star + 1 > self.max_star:
            raise ValueError(
                f"level {self.level} cannot be enhanced past {self.max_star} stars, "
                f"and the item is already at {self.star}"
            )

        star_before = self.star
        meso = rules.breakthrough_cost(cap_star, success)
        self.totals.total_meso += meso
        self.totals.breakthroughs_used += 1

        roll = self.rng.randrange(static_data.RATE_BASIS)
        if roll < success:
            outcome = Outcome.SUCCESS
            self.star = star_before + 1
        else:
            outcome = Outcome.MAINTAIN

        return self._record(Action.BREAKTHROUGH, star_before, meso, 0, outcome=outcome)

    def repair(self, policy: RepairPolicy) -> LogEntry:
        """Restore a destroyed item, either to its trace star or to 12 stars."""
        if not self.destroyed:
            raise ValueError(
                f"the item is not destroyed - it is at {self.star} stars - "
                f"so there is nothing to repair"
            )

        star_before = self.star
        if policy is RepairPolicy.FULL:
            action = Action.REPAIR_FULL
            meso, equipment = rules.full_repair(self.level, star_before)
            star_after = star_before
        else:
            action = Action.REPAIR_TO_12
            meso, equipment = rules.cheap_repair()
            star_after = rules.CHEAP_REPAIR_STAR

        equipment_cost = equipment * self.equipment_price
        self.totals.total_meso += meso
        self.totals.equipment_used += equipment
        self.totals.equipment_cost += equipment_cost
        self.star = star_after
        self.destroyed = False

        return self._record(
            action, star_before, meso, equipment_cost, equipment=equipment
        )

    def _record(
        self,
        action: Action,
        star_before: int,
        meso: int,
        equipment_cost: int,
        outcome: Outcome | None = None,
        equipment: int = 0,
    ) -> LogEntry:
        """Append the entry for an action that has already been charged."""
        entry = LogEntry(
            index=len(self.log) + 1,
            action=action.value,
            star_before=star_before,
            star_after=self.star,
            outcome=None if outcome is None else outcome.value,
            meso=meso,
            equipment_used=equipment,
            equipment_cost=equipment_cost,
            total_cost_after=self.totals.total_cost,
        )
        self.log.append(entry)
        return entry

    def headline(self) -> str:
        """Where the item stands right now, in one line."""
        text = f"level {self.level}  {self.star} stars"
        if self.destroyed:
            text += "  DESTROYED (repair before continuing)"
        if self.equipment_name is not None:
            text += (
                f"  equipment={self.equipment_name} @ "
                f"{format_meso(self.equipment_price)}"
            )
        return text

    def report(self) -> str:
        """The full log plus the running totals, every meso figure in 億."""
        lines = [self.headline()]
        if self.log:
            rule = "-" * 78
            lines.append(rule)
            lines.extend(entry.describe() for entry in self.log)
            lines.append(rule)

        totals = self.totals
        lines.append(f"  meso        {format_meso(totals.total_meso):>16}")
        lines.append(
            f"  equip cost  {format_meso(totals.equipment_cost):>16}"
            f"   ({totals.equipment_used} pieces)"
        )
        lines.append(f"  total       {format_meso(totals.total_cost):>16}")
        lines.append(
            f"  scrolls {totals.scrolls_used}   "
            f"breakthroughs {totals.breakthroughs_used}   "
            f"attempts {totals.attempts}   destroys {totals.destroys}"
        )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable state, log and totals, for the static front end."""
        totals = self.totals
        return {
            "level": self.level,
            "equipment_name": self.equipment_name,
            "equipment_price": self.equipment_price,
            "equipment_price_yi": to_yi(self.equipment_price),
            "seed": self.seed,
            "start_star": self.start_star,
            "star": self.star,
            "destroyed": self.destroyed,
            "log": [entry.to_dict() for entry in self.log],
            "totals": {
                "total_meso": totals.total_meso,
                "total_meso_yi": to_yi(totals.total_meso),
                "equipment_used": totals.equipment_used,
                "equipment_cost": totals.equipment_cost,
                "equipment_cost_yi": to_yi(totals.equipment_cost),
                "total_cost": totals.total_cost,
                "total_cost_yi": to_yi(totals.total_cost),
                "scrolls_used": totals.scrolls_used,
                "breakthroughs_used": totals.breakthroughs_used,
                "attempts": totals.attempts,
                "destroys": totals.destroys,
                "attempts_by_star": {
                    str(star): count
                    for star, count in sorted(totals.attempts_by_star.items())
                },
            },
        }
