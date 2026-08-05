"""Which action to take at each star, and what that costs in expectation.

Breakthrough scrolls turn every star into a choice: enhance, or spend a scroll
for one shot at ``+1``. Sweeping that choice space by Monte Carlo is hopeless -
a 15 to 22 climb has seven decision points - but it does not need simulating at
all. The expected cost has a closed form, so this module *solves* for the
cheapest policy and hands the sweep a short list of policies worth measuring.

The structure that makes it solvable
------------------------------------
A breakthrough scroll cannot destroy, so its star is a geometric wait:

    V(s) = price + (1 - rate) V(s) + rate V(s + 1)
         = price / rate + V(s + 1)

An enhancement can destroy, and where that lands is the whole difference
between the two repair policies:

``FULL``
    the trace carries the item's own star (below 23), so a repair puts it back
    exactly where it was. The star is again an independent wait::

        V(s) = (fee + p_destroy x repair) / p_success + V(s + 1)

``TO_12``
    the item drops to 12 stars and re-scrolls to ``start_star``, so every star
    depends on the value of restarting - one unknown, shared by all of them.
    Writing ``X`` for that value, every ``V(s)`` is affine in ``X``, and
    ``X = V(start_star)`` closes the system.

So both cases are one backward pass, and TO_12 adds a fixed point over a single
scalar. :func:`optimal_policy` alternates the two - evaluate, then improve -
until the policy stops changing, which is policy iteration on that scalar.

What this module does not do
----------------------------
Percentiles. The mean is linear in the prices and has a closed form; p50 and
p95 do not, and still come from ``sweep.py`` running the policies this module
names. ``OWNED`` runs are not solved either - that is ``sweep_marginal.py``'s
question, and it is not yet answered here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from . import rules
from . import static_data as data
from .engine import RepairPolicy, StartMode

#: Policy iteration should settle in two or three rounds. This is the guard
#: against a bug turning that into an infinite loop, not a tuning knob.
MAX_ROUNDS = 50


@dataclass(frozen=True)
class BreakthroughPolicy:
    """What to do at each star: enhance, unless a scroll is named for it.

    ``entries`` holds ``(star, cap_star, success)`` triples, sorted by star. A
    tuple rather than a mapping because :class:`starforce.engine.RunConfig` is
    frozen and hashable, and this rides along on it.
    """

    name: str
    entries: tuple[tuple[int, int, int], ...] = ()

    def __post_init__(self) -> None:
        seen: set[int] = set()
        for star, cap_star, success in self.entries:
            if star in seen:
                raise ValueError(f"policy {self.name!r} names two scrolls for star {star}")
            seen.add(star)
            rules.check_breakthrough(cap_star, success)
            if star + 1 > cap_star:
                raise ValueError(
                    f"policy {self.name!r} uses a scroll capped at {cap_star} stars "
                    f"on star {star}, which it cannot raise"
                )
        if list(self.entries) != sorted(self.entries):
            raise ValueError(f"policy {self.name!r} must list its stars in order")
        # Built once: scroll_at runs inside the Monte Carlo loop, millions of
        # times per sweep, and a linear scan there is measurable.
        object.__setattr__(self, "_by_star", dict((s, (c, r)) for s, c, r in self.entries))

    def scroll_at(self, star: int) -> tuple[int, int] | None:
        """``(cap_star, success)`` for this star, or None to enhance."""
        return self._by_star.get(star)  # type: ignore[attr-defined]

    @property
    def stars(self) -> tuple[int, ...]:
        return tuple(star for star, _, _ in self.entries)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "entries": [list(entry) for entry in self.entries],
        }

    def describe(self) -> str:
        """One line naming every scroll this policy buys, in star order."""
        if not self.entries:
            return f"{self.name}: enhance throughout"
        parts = [
            f"{star}:{cap}*{success * 100 // data.RATE_BASIS}%"
            for star, cap, success in self.entries
        ]
        return f"{self.name}: " + " ".join(parts)


#: Enhance at every star. The behaviour the engine had before scrolls existed,
#: kept as a named policy so a sweep row can say so explicitly.
NONE = BreakthroughPolicy("none")


def _usable(star: int, deterministic_only: bool) -> Iterable[tuple[int, int]]:
    """Scrolls that could raise an item at ``star``, cheapest expectation first."""
    for cap_star, success in data.BREAKTHROUGH_SCROLLS:
        if star + 1 > cap_star:
            continue
        if deterministic_only and success != data.RATE_BASIS:
            continue
        yield cap_star, success


def _best_scroll(star: int, deterministic_only: bool) -> tuple[float, tuple[int, int]] | None:
    """The cheapest scroll for one star, as ``(expected cost, scroll)``.

    A scroll's expected cost is ``price / rate``: it is bought again on every
    miss, and a miss changes nothing else.
    """
    best: tuple[float, tuple[int, int]] | None = None
    for cap_star, success in _usable(star, deterministic_only):
        cost = rules.breakthrough_cost(cap_star, success) / (success / data.RATE_BASIS)
        if best is None or cost < best[0]:
            best = (cost, (cap_star, success))
    return best


@dataclass(frozen=True)
class _Problem:
    """Everything the recursion needs, resolved once."""

    level: int
    start_star: int
    target_star: int
    equipment_price: int
    repair_policy: RepairPolicy

    def enhance_terms(self, star: int) -> tuple[float, float, float, float]:
        """``(fee, p_success, p_destroy, immediate destruction cost)``."""
        fee = float(rules.enhance_cost(self.level, star))
        success, destroy, _ = rules.enhance_rates(star)
        cost = 0.0
        if destroy:
            if self.repair_policy is RepairPolicy.FULL:
                meso, pieces = rules.full_repair(self.level, rules.trace_star(star))
            else:
                meso, pieces = rules.cheap_repair()
            cost = meso + pieces * self.equipment_price
            if self.repair_policy is RepairPolicy.TO_12:
                # The engine climbs back out of a 12 star repair with another
                # start_star scroll, charged at repair time.
                cost += rules.star_scroll_cost(self.start_star)
        return fee, success / data.RATE_BASIS, destroy / data.RATE_BASIS, cost


def _sweep_back(
    problem: _Problem,
    restart: float,
    policy: BreakthroughPolicy | None,
    deterministic_only: bool = False,
) -> tuple[list[tuple[int, int, int]], dict[int, float], dict[int, float]]:
    """One backward pass from the target, holding the restart value fixed.

    With ``policy`` given, every star follows it. With ``policy`` None, every
    star takes whichever action is cheaper - that is the greedy improvement.

    Returns the chosen entries plus ``V(s)`` split into its constant part and
    its coefficient on the restart value, so the caller can close the fixed
    point. Under FULL repair the coefficient stays zero: a repair puts the item
    back where it was, so restarting never happens.
    """
    constant = {problem.target_star: 0.0}
    coefficient = {problem.target_star: 0.0}
    chosen: list[tuple[int, int, int]] = []

    for star in range(problem.target_star - 1, problem.start_star - 1, -1):
        fee, p_success, p_destroy, destruction = problem.enhance_terms(star)

        if problem.repair_policy is RepairPolicy.FULL:
            enhance_constant = (fee + p_destroy * destruction) / p_success + constant[star + 1]
            enhance_coefficient = coefficient[star + 1]
        else:
            denominator = p_success + p_destroy
            enhance_constant = (
                fee + p_destroy * destruction + p_success * constant[star + 1]
            ) / denominator
            enhance_coefficient = (
                p_destroy + p_success * coefficient[star + 1]
            ) / denominator

        enhance_value = enhance_constant + enhance_coefficient * restart

        scroll = policy.scroll_at(star) if policy is not None else None
        if policy is None:
            best = _best_scroll(star, deterministic_only)
            if best is not None and best[0] + constant[star + 1] + coefficient[
                star + 1
            ] * restart < enhance_value:
                scroll = best[1]

        if scroll is None:
            constant[star] = enhance_constant
            coefficient[star] = enhance_coefficient
            continue

        cap_star, success = scroll
        per_success = rules.breakthrough_cost(cap_star, success) / (
            success / data.RATE_BASIS
        )
        constant[star] = per_success + constant[star + 1]
        coefficient[star] = coefficient[star + 1]
        chosen.append((star, cap_star, success))

    chosen.reverse()
    return chosen, constant, coefficient


def _restart_value(problem: _Problem, policy: BreakthroughPolicy) -> float:
    """``V(start_star)`` for a fixed policy, solved exactly.

    ``V(start) = a + b V(start)`` where ``a`` and ``b`` come from one backward
    pass, so the fixed point is ``a / (1 - b)``. ``b`` is the probability-weighted
    share of runs that end up restarting, and it is strictly below one because
    every star has a positive chance of being passed.
    """
    _, constant, coefficient = _sweep_back(problem, 0.0, policy)
    a = constant[problem.start_star]
    b = coefficient[problem.start_star]
    if b >= 1.0:
        raise RuntimeError(
            f"the restart fixed point does not converge (coefficient {b}); "
            f"this means a star can never be passed, which the rate tables rule out"
        )
    return a / (1.0 - b)


#: Highest target whose FULL repair still returns an item where it was.
#:
#: The recursion treats a destroyed star as an independent wait, which needs the
#: repair to put the item back on that same star. A trace never records more
#: than TRACE_STAR_CAP, so that holds only while the highest attempt - one below
#: the target - is still at or under the cap.
MAX_FULL_REPAIR_TARGET = rules.TRACE_STAR_CAP + 1


def _check_repair_reachable(target_star: int, repair_policy: RepairPolicy) -> None:
    """Refuse a FULL repair target the recursion would answer wrongly.

    Past MAX_FULL_REPAIR_TARGET a destruction leaves a 22 star trace rather than
    the star it happened on, so repairing drops the item below where it was and
    the stars stop being independent. Solving it needs a different recursion,
    not a wider bound - so this raises instead of returning a plausible number.

    TO_12 is unaffected: it always lands on 12 stars and re-scrolls to the
    start, whatever star the destruction happened on.
    """
    if repair_policy is RepairPolicy.FULL and target_star > MAX_FULL_REPAIR_TARGET:
        raise NotImplementedError(
            f"a FULL repair run to {target_star} stars is not solved here: above "
            f"{rules.TRACE_STAR_CAP} stars a destroyed item leaves a "
            f"{rules.TRACE_STAR_CAP} star trace, so repairing it does not return "
            f"it to the star it was lost on and the per-star recursion no longer "
            f"holds. sweep_marginal.py measures that range instead"
        )


def _check(
    level: int,
    start_star: int,
    target_star: int,
    start_mode: StartMode,
    repair_policy: RepairPolicy,
) -> None:
    rules.check_level(level)
    if start_mode is not StartMode.SCROLL:
        raise NotImplementedError(
            "only SCROLL runs are solved here; an OWNED run's rebuild cost is "
            "itself a measured figure, and sweep_marginal.py has not been "
            "brought into this yet"
        )
    _check_repair_reachable(target_star, repair_policy)
    rules.check_start_star(start_star)
    if target_star <= start_star:
        raise ValueError(
            f"target_star must exceed start_star, got {start_star} -> {target_star}"
        )
    if target_star > rules.max_target_star(level):
        raise ValueError(
            f"level {level} cannot be simulated past "
            f"{rules.max_target_star(level)} stars, got {target_star}"
        )


def expected_total(
    policy: BreakthroughPolicy,
    level: int,
    start_star: int,
    target_star: int,
    equipment_price: int,
    repair_policy: RepairPolicy = RepairPolicy.FULL,
    start_mode: StartMode = StartMode.SCROLL,
) -> float:
    """Exact expected total cost of following ``policy``, in meso.

    Exact in the sense that it is derived rather than sampled: no number of
    trials would improve it. It covers the same three cost streams the engine
    tracks - enhancement fees, repair meso and equipment, and both kinds of
    scroll - and the opening star scroll the run is set up with.
    """
    _check(level, start_star, target_star, start_mode, repair_policy)
    outside = [star for star in policy.stars if not start_star <= star < target_star]
    if outside:
        raise ValueError(
            f"policy {policy.name!r} names scrolls for stars {outside}, which this "
            f"{start_star} -> {target_star} run never visits"
        )
    problem = _Problem(
        level=level,
        start_star=start_star,
        target_star=target_star,
        equipment_price=equipment_price,
        repair_policy=repair_policy,
    )
    return rules.star_scroll_cost(start_star) + _restart_value(problem, policy)


def optimal_policy(
    level: int,
    start_star: int,
    target_star: int,
    equipment_price: int,
    repair_policy: RepairPolicy = RepairPolicy.FULL,
    start_mode: StartMode = StartMode.SCROLL,
    deterministic_only: bool = False,
    name: str | None = None,
) -> BreakthroughPolicy:
    """The cheapest policy by expected total cost.

    ``deterministic_only`` restricts the choice to 100% scrolls. Those cost
    more per star but cannot miss, which is the trade the cheat sheet's stable
    answer is about: at 21 stars the cheapest scroll by expectation is a 50%
    one, and paying more for certainty is a defensible thing to want.

    Policy iteration: evaluate the current policy to get the value of
    restarting, take the cheaper action at every star given that value, repeat.
    Under FULL repair nothing restarts, so the first pass is already optimal.
    """
    _check(level, start_star, target_star, start_mode, repair_policy)
    problem = _Problem(
        level=level,
        start_star=start_star,
        target_star=target_star,
        equipment_price=equipment_price,
        repair_policy=repair_policy,
    )
    label = name or ("safe" if deterministic_only else "optimal")

    policy = BreakthroughPolicy(label)
    for _ in range(MAX_ROUNDS):
        restart = _restart_value(problem, policy)
        entries, _, _ = _sweep_back(problem, restart, None, deterministic_only)
        improved = BreakthroughPolicy(label, tuple(entries))
        if improved.entries == policy.entries:
            return improved
        policy = improved

    raise RuntimeError(
        f"policy iteration did not settle in {MAX_ROUNDS} rounds for level {level} "
        f"{start_star}->{target_star} {repair_policy.value}"
    )


def sweep_policies(
    level: int,
    start_star: int,
    target_star: int,
    equipment_price: int,
    repair_policy: RepairPolicy = RepairPolicy.FULL,
) -> list[BreakthroughPolicy]:
    """The policies worth measuring for one combination.

    ``none`` is the baseline the dataset already had. ``optimal`` is the
    cheapest by expectation. ``safe`` is the cheapest that never misses. Any of
    the three can coincide, and duplicates are dropped: measuring the same
    policy twice would put two identical rows in the dataset.
    """
    candidates = [
        NONE,
        optimal_policy(
            level, start_star, target_star, equipment_price, repair_policy
        ),
        optimal_policy(
            level,
            start_star,
            target_star,
            equipment_price,
            repair_policy,
            deterministic_only=True,
        ),
    ]

    kept: list[BreakthroughPolicy] = []
    seen: set[tuple[tuple[int, int, int], ...]] = set()
    for policy in candidates:
        if policy.entries in seen:
            continue
        seen.add(policy.entries)
        kept.append(policy)
    return kept
