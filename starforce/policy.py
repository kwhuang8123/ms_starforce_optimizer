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
    """Everything the recursion needs, resolved once.

    ``base_star`` is the lowest star the recursion covers, and the one every
    destruction that loses ground falls back to. An OWNED run is solved from 22
    stars up even when it starts at 23 or 24, because that is where a
    destruction puts it and it has to climb again from there.
    """

    level: int
    start_star: int
    target_star: int
    equipment_price: int
    repair_policy: RepairPolicy
    start_mode: StartMode
    base_star: int
    rebuild_cost: int = 0

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
                if self.start_mode is StartMode.OWNED:
                    # No scroll reaches 22 stars, so an OWNED run climbs back by
                    # rebuilding - a flat measured cost charged at repair time.
                    cost += self.rebuild_cost
                else:
                    # A SCROLL run climbs back out of a 12 star repair with
                    # another start_star scroll, also charged at repair time.
                    cost += rules.star_scroll_cost(self.start_star)
        return fee, success / data.RATE_BASIS, destroy / data.RATE_BASIS, cost

    def lands_on_itself(self, star: int) -> bool:
        """Does a destruction here put the item back on the star it was lost on?

        Only a FULL repair can, and only while the trace still records the star
        - above TRACE_STAR_CAP every trace reads 22, so the item drops to
        ``base_star`` instead and the star stops being an independent wait.

        TO_12 never does: it lands on 12 stars and climbs back to where the run
        began, which is ``base_star`` by construction.
        """
        return (
            self.repair_policy is RepairPolicy.FULL and star <= rules.TRACE_STAR_CAP
        )


def _sweep_back(
    problem: _Problem,
    restart: float,
    policy: BreakthroughPolicy | None,
    deterministic_only: bool = False,
) -> tuple[list[tuple[int, int, int]], dict[int, float], dict[int, float]]:
    """One backward pass from the target, holding the base value fixed.

    With ``policy`` given, every star follows it. With ``policy`` None, every
    star takes whichever action is cheaper - that is the greedy improvement.

    Returns the chosen entries plus ``V(s)`` split into its constant part and
    its coefficient on ``V(base_star)``, so the caller can close the fixed
    point. A star whose destruction lands back on itself contributes nothing to
    that coefficient: it is an independent wait, and nothing ever falls through
    it. Where every star is like that - a SCROLL run repairing in full below 23
    stars - the coefficient stays zero throughout and the fixed point is moot.
    """
    constant = {problem.target_star: 0.0}
    coefficient = {problem.target_star: 0.0}
    chosen: list[tuple[int, int, int]] = []

    for star in range(problem.target_star - 1, problem.base_star - 1, -1):
        fee, p_success, p_destroy, destruction = problem.enhance_terms(star)

        if problem.lands_on_itself(star):
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


def _base_value(problem: _Problem, policy: BreakthroughPolicy) -> float:
    """``V(base_star)`` for a fixed policy, solved exactly.

    Every star is affine in this value, and the base star is itself one of them,
    so ``V(base) = a + b V(base)`` closes to ``a / (1 - b)``. ``b`` is the
    probability-weighted share of runs that fall back to the base, and it stays
    below one because every star has a positive chance of being passed.
    """
    _, constant, coefficient = _sweep_back(problem, 0.0, policy)
    a = constant[problem.base_star]
    b = coefficient[problem.base_star]
    if b >= 1.0:
        raise RuntimeError(
            f"the fixed point at {problem.base_star} stars does not converge "
            f"(coefficient {b}); this means a star can never be passed, which "
            f"the rate tables rule out"
        )
    return a / (1.0 - b)


def _solve(problem: _Problem, policy: BreakthroughPolicy) -> float:
    """``V(start_star)`` for a fixed policy, read off the closed fixed point.

    For a run that begins at the base - every SCROLL run, and an OWNED run held
    at 22 stars - that is the fixed point itself. An OWNED run starting higher
    is already partway up, and this is where that head start is priced in.
    """
    base = _base_value(problem, policy)
    if problem.start_star == problem.base_star:
        return base
    _, constant, coefficient = _sweep_back(problem, base, policy)
    return constant[problem.start_star] + coefficient[problem.start_star] * base


#: Highest target a SCROLL run repairing in full is solved for.
#:
#: Above TRACE_STAR_CAP a destruction leaves a 22 star trace, so the item drops
#: to 22 rather than back to where it was lost. The recursion handles that - it
#: is how every OWNED run works - but it needs the fallback star to be the
#: lowest one it covers, and a SCROLL run starts below 22. Solving one would
#: mean carrying a second unknown, and nothing asks for it: sweep.py stops at 22
#: stars and sweep_marginal.py answers the range above.
MAX_FULL_REPAIR_TARGET = rules.TRACE_STAR_CAP + 1


def _check_repair_reachable(
    target_star: int, repair_policy: RepairPolicy, start_mode: StartMode
) -> None:
    """Refuse the one combination whose fallback star sits inside the range.

    An OWNED run is unaffected: it never starts below 22, so 22 is both where a
    destruction lands and the lowest star solved, which is exactly what the
    recursion needs.
    """
    if (
        start_mode is StartMode.SCROLL
        and repair_policy is RepairPolicy.FULL
        and target_star > MAX_FULL_REPAIR_TARGET
    ):
        raise NotImplementedError(
            f"a SCROLL run repairing in full to {target_star} stars is not solved "
            f"here: above {rules.TRACE_STAR_CAP} stars a destroyed item drops to "
            f"{rules.TRACE_STAR_CAP}, which is neither the star it was lost on nor "
            f"the star the run began at, so the recursion would need a second "
            f"unknown. sweep_marginal.py measures that range instead"
        )


def base_star_for(start_star: int, start_mode: StartMode) -> int:
    """The lowest star the recursion covers, and where a lost run falls back to.

    A SCROLL run bottoms out where it began: below 23 stars a full repair puts
    the item back on the star it was lost on, and a 12 star repair re-scrolls to
    the start. An OWNED run always drops to the rebuild star, so it is solved
    from there up even when it starts higher.
    """
    if start_mode is StartMode.SCROLL:
        return start_star
    return min(start_star, rules.REBUILD_STAR)


def _check(
    level: int,
    start_star: int,
    target_star: int,
    start_mode: StartMode,
    repair_policy: RepairPolicy,
    rebuild_cost: int,
) -> None:
    rules.check_level(level)
    _check_repair_reachable(target_star, repair_policy, start_mode)

    if start_mode is StartMode.SCROLL:
        rules.check_start_star(start_star)
        if rebuild_cost:
            raise ValueError(
                "rebuild_cost applies to an OWNED run repairing to 12 stars only, "
                f"got start_mode={start_mode.value}"
            )
    else:
        if start_star < rules.REBUILD_STAR:
            raise ValueError(
                f"an OWNED run is priced against a {rules.REBUILD_STAR} star "
                f"rebuild, so it must start at or above it, got {start_star}"
            )
        if repair_policy is RepairPolicy.TO_12 and rebuild_cost <= 0:
            raise ValueError(
                "an OWNED run repairing to 12 stars needs a positive rebuild_cost: "
                f"the cost of climbing back to {rules.REBUILD_STAR} stars"
            )

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
    rebuild_cost: int = 0,
) -> float:
    """Exact expected total cost of following ``policy``, in meso.

    Exact in the sense that it is derived rather than sampled: no number of
    trials would improve it. It covers the same cost streams the engine tracks -
    enhancement fees, repair meso and equipment, both kinds of scroll, and an
    OWNED run's rebuilds - plus the opening star scroll a SCROLL run is set up
    with. An OWNED run buys nothing to begin: it already holds the item.
    """
    _check(
        level, start_star, target_star, start_mode, repair_policy, rebuild_cost
    )
    base = base_star_for(start_star, start_mode)
    outside = [star for star in policy.stars if not base <= star < target_star]
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
        start_mode=start_mode,
        base_star=base,
        rebuild_cost=rebuild_cost,
    )
    opening = (
        rules.star_scroll_cost(start_star)
        if start_mode is StartMode.SCROLL
        else 0
    )
    return opening + _solve(problem, policy)


def optimal_policy(
    level: int,
    start_star: int,
    target_star: int,
    equipment_price: int,
    repair_policy: RepairPolicy = RepairPolicy.FULL,
    start_mode: StartMode = StartMode.SCROLL,
    deterministic_only: bool = False,
    name: str | None = None,
    rebuild_cost: int = 0,
) -> BreakthroughPolicy:
    """The cheapest policy by expected total cost.

    ``deterministic_only`` restricts the choice to 100% scrolls. Those cost
    more per star but cannot miss, which is the trade the cheat sheet's stable
    answer is about: at 21 stars the cheapest scroll by expectation is a 50%
    one, and paying more for certainty is a defensible thing to want.

    Policy iteration: evaluate the current policy to get the value of falling
    back to the base star, take the cheaper action at every star given that
    value, repeat. Where nothing ever falls back - a SCROLL run repairing in
    full - the first pass is already optimal.
    """
    _check(
        level, start_star, target_star, start_mode, repair_policy, rebuild_cost
    )
    problem = _Problem(
        level=level,
        start_star=start_star,
        target_star=target_star,
        equipment_price=equipment_price,
        repair_policy=repair_policy,
        start_mode=start_mode,
        base_star=base_star_for(start_star, start_mode),
        rebuild_cost=rebuild_cost,
    )
    label = name or ("safe" if deterministic_only else "optimal")

    policy = BreakthroughPolicy(label)
    for _ in range(MAX_ROUNDS):
        base = _base_value(problem, policy)
        entries, _, _ = _sweep_back(problem, base, None, deterministic_only)
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
    start_mode: StartMode = StartMode.SCROLL,
    rebuild_cost: int = 0,
) -> list[BreakthroughPolicy]:
    """The policies worth measuring for one combination.

    ``none`` is the baseline the dataset already had. ``optimal`` is the
    cheapest by expectation. ``safe`` is the cheapest that never misses. Any of
    the three can coincide, and duplicates are dropped: measuring the same
    policy twice would put two identical rows in the dataset.
    """
    shared = (level, start_star, target_star, equipment_price, repair_policy)
    candidates = [
        NONE,
        optimal_policy(
            *shared, start_mode=start_mode, rebuild_cost=rebuild_cost
        ),
        optimal_policy(
            *shared,
            start_mode=start_mode,
            deterministic_only=True,
            rebuild_cost=rebuild_cost,
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
