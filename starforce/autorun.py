"""Drive a :class:`~starforce.session.Session` automatically until it stops.

Two modes are exposed, and they are the same loop with a different reason for
setting the budget:

``run_within_budget``
    "I have 100億 and I want 22 stars." The budget is the point of the run.
``run_to_star``
    "Take it to 22 stars." The budget is only a fuse: a climb has no guaranteed
    length, so a front end that runs this in a browser needs some ceiling. Pass
    a figure taken from the measured distribution - the sweep's p95 total cost
    is what this project uses - rather than an arbitrary number.

Neither mode overspends. Every action's price is known before it is taken, so
the loop stops rather than starting something the budget cannot cover. A run
that is destroyed and cannot afford either repair stops in that state and says
so: :class:`AutoRunResult` carries ``destroyed`` for exactly that case.

Decisions come from an :class:`AutoPolicy` fixed at the start - which repair to
buy, which star scroll the strategy uses - so the run is reproducible from the
policy plus the session's seed. This is the logged single-run path; the
unlogged path built for hundred-thousand-trial Monte Carlo is
:func:`starforce.engine.simulate_once`, and the two are held in step by
``tests/test_autorun.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from . import rules
from .engine import RepairPolicy
from .session import LogEntry, Session

# What the policy does next. Internal: the caller sees Action values on the log.
_REPAIR = "repair"
_SCROLL = "scroll"
_ENHANCE = "enhance"


class StopReason(Enum):
    """Why an automatic run gave back control."""

    #: The item reached the target star.
    REACHED_TARGET = "reached_target"
    #: The next action cost more than the budget had left.
    BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass(frozen=True)
class AutoPolicy:
    """The decisions an automatic run is not allowed to make for itself.

    ``scroll_star`` is the star scroll this strategy uses. It goes on at the
    start when the item sits below it, and again after every 12 star repair,
    which is how :func:`starforce.engine.simulate_once` treats a scrolled run.
    Leave it None to climb from wherever the item already is.
    """

    repair_policy: RepairPolicy = RepairPolicy.FULL
    scroll_star: int | None = None

    def __post_init__(self) -> None:
        if self.scroll_star is not None:
            rules.check_start_star(self.scroll_star)


@dataclass(frozen=True)
class AutoRunResult:
    """What one automatic run did, on top of whatever the session already held."""

    stop_reason: StopReason
    #: The entries this run appended, in order.
    entries: tuple[LogEntry, ...]
    #: Where the item ended up.
    star: int
    #: True when the run stopped on a trace it could not afford to repair.
    destroyed: bool
    #: Cost of this run alone, not the session's lifetime total.
    spent: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "stop_reason": self.stop_reason.value,
            "entries": [entry.to_dict() for entry in self.entries],
            "star": self.star,
            "destroyed": self.destroyed,
            "spent": self.spent,
        }


def _next_action(
    session: Session, target_star: int, policy: AutoPolicy
) -> tuple[str, int]:
    """What the policy does next, and what it costs before it is taken."""
    if session.destroyed:
        if policy.repair_policy is RepairPolicy.FULL:
            meso, equipment = rules.full_repair(session.level, session.star)
        else:
            meso, equipment = rules.cheap_repair()
        return _REPAIR, meso + equipment * session.equipment_price

    if (
        policy.scroll_star is not None
        and session.star < policy.scroll_star < target_star
    ):
        return _SCROLL, rules.star_scroll_cost(policy.scroll_star)

    return _ENHANCE, rules.enhance_cost(session.level, session.star)


def _take_action(session: Session, kind: str, policy: AutoPolicy) -> None:
    """Perform the action :func:`_next_action` priced."""
    if kind == _REPAIR:
        session.repair(policy.repair_policy)
    elif kind == _SCROLL:
        # _next_action only picks a scroll when the policy actually has one.
        session.use_scroll(policy.scroll_star)
    else:
        session.enhance()


def run_within_budget(
    session: Session,
    target_star: int,
    budget: int,
    policy: AutoPolicy = AutoPolicy(),
) -> AutoRunResult:
    """Enhance ``session`` towards ``target_star`` until the budget runs out.

    ``budget`` caps the session's lifetime total cost - meso plus the market
    value of the equipment repairs consume - not this run's spending alone, so
    resuming a session cannot spend the same budget twice.
    """
    if budget <= 0:
        raise ValueError(f"budget must be positive, got {budget}")
    if target_star > session.max_star:
        raise ValueError(
            f"level {session.level} cannot be taken past {session.max_star} stars, "
            f"got target_star={target_star}"
        )

    first_entry = len(session.log)
    spent_before = session.total_cost

    while True:
        if not session.destroyed and session.star >= target_star:
            stop_reason = StopReason.REACHED_TARGET
            break

        kind, cost = _next_action(session, target_star, policy)
        if session.total_cost + cost > budget:
            stop_reason = StopReason.BUDGET_EXHAUSTED
            break

        _take_action(session, kind, policy)

    return AutoRunResult(
        stop_reason=stop_reason,
        entries=tuple(session.log[first_entry:]),
        star=session.star,
        destroyed=session.destroyed,
        spent=session.total_cost - spent_before,
    )


def run_to_star(
    session: Session,
    target_star: int,
    budget: int,
    policy: AutoPolicy = AutoPolicy(),
) -> AutoRunResult:
    """Enhance ``session`` to ``target_star``, with ``budget`` as the fuse.

    Identical to :func:`run_within_budget`; the separate name records that here
    the target is the goal and the budget is only there to stop a run that has
    gone far past what the measured distribution says it should cost.
    """
    return run_within_budget(session, target_star, budget, policy)
