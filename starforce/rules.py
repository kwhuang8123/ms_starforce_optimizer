"""Star force rules derived from the V272 announcement.

Every lookup validates its arguments and raises rather than falling back to a
default, so an unsupported level or an out-of-range star fails loudly.

Fixed tables come from :mod:`starforce.static_data`; prices that move with the
market come from :mod:`starforce.volatile_data`.
"""

from __future__ import annotations

from . import static_data as data
from . import volatile_data

# Star force caps by item level. 130 gear stops at 20 stars, 140+ at 30.
MAX_STAR: dict[int, int] = {
    130: 20,
    140: 30,
    150: 30,
    160: 30,
    200: 30,
    250: 30,
}

# Destruction first appears on the 15 -> 16 attempt.
DESTROY_START_STAR = 15

# A run always begins from a star scroll, so the starting star is limited to
# the stars scrolls exist for.
MIN_START_STAR = data.STAR_SCROLL_STARS[0]
MAX_START_STAR = data.STAR_SCROLL_STARS[-1]

# A trace never records more than 22 stars: destruction at 23 through 30 stars
# still produces a 22 star trace.
TRACE_STAR_CAP = 22

# The cheap repair option restores the item to 12 stars.
CHEAP_REPAIR_STAR = 12
CHEAP_REPAIR_EQUIPMENT = 1

# Where a rebuild lands when a run that started from an already-owned item is
# destroyed: repair to 12 stars, then climb back to 22. 22 is the star the
# rebuild cost is priced against, so the two must stay in step.
REBUILD_STAR = 22


def check_level(level: int) -> None:
    """Raise unless ``level`` is one of the six published levels."""
    if level not in data.SUPPORTED_LEVELS:
        raise ValueError(
            f"level {level} is not published by the official tables; "
            f"supported levels are {data.SUPPORTED_LEVELS}"
        )


def max_star(level: int) -> int:
    """Star force cap for ``level``."""
    check_level(level)
    return MAX_STAR[level]


def max_target_star(level: int) -> int:
    """Highest target this engine will simulate for ``level``.

    Level 130 is capped at :data:`DESTROY_START_STAR` because the official
    repair table publishes no level 130 column, which makes the cost of a
    destroyed 130 item unknowable. Every other level uses its real cap.
    """
    cap = max_star(level)
    if level not in data.REPAIR_MESO:
        return min(cap, DESTROY_START_STAR)
    return cap


def enhance_cost(level: int, star: int) -> int:
    """Meso cost of one ``star -> star + 1`` attempt."""
    check_level(level)
    costs = data.ENHANCE_COST[level]
    if star not in costs:
        raise ValueError(
            f"level {level} has no published cost for the {star} -> {star + 1} attempt"
        )
    return costs[star]


def enhance_rates(star: int) -> tuple[int, int, int]:
    """``(success, destroy, maintain)`` in basis points for one attempt."""
    if star not in data.ENHANCE_RATES:
        raise ValueError(f"no published rates for the {star} -> {star + 1} attempt")
    return data.ENHANCE_RATES[star]


def trace_star(destroyed_star: int) -> int:
    """Star force recorded on the trace left by destruction at ``destroyed_star``."""
    if destroyed_star < DESTROY_START_STAR:
        raise ValueError(
            f"an item at {destroyed_star} stars cannot be destroyed; "
            f"destruction starts at {DESTROY_START_STAR} stars"
        )
    return min(destroyed_star, TRACE_STAR_CAP)


def full_repair(level: int, trace: int) -> tuple[int, int]:
    """``(meso, equipment_pieces)`` to restore a trace to its original stars."""
    check_level(level)
    if level not in data.REPAIR_MESO:
        raise ValueError(f"the official repair table publishes no level {level} column")
    table = data.REPAIR_MESO[level]
    if trace not in table:
        raise ValueError(f"no published repair cost for a {trace} star trace")
    return table[trace], data.REPAIR_EQUIPMENT[trace]


def cheap_repair() -> tuple[int, int]:
    """``(meso, equipment_pieces)`` to restore a trace to 12 stars."""
    return 0, CHEAP_REPAIR_EQUIPMENT


def check_start_star(star: int) -> None:
    """Raise unless a star scroll exists for ``star``."""
    if not MIN_START_STAR <= star <= MAX_START_STAR:
        raise ValueError(
            f"start_star must be between {MIN_START_STAR} and {MAX_START_STAR} "
            f"because the run begins from a star scroll, got {star}"
        )


def star_scroll_cost(star: int) -> int:
    """Meso cost of the ``star`` star scroll, as currently priced.

    Scroll prices do not vary with item level, so this takes no level. The
    figure is volatile: it is read live so a reload picks up new prices.
    """
    check_start_star(star)
    return volatile_data.STAR_SCROLL_COST[star]
