"""The decision layer: what it picks, and whether the engine agrees with it."""

from __future__ import annotations

import unittest

from starforce import policy as pol
from starforce import static_data as data
from starforce import rules, simulate, volatile_data
from starforce.engine import RepairPolicy, RunConfig, StartMode

TARGET = 22


class PolicyShapeTest(unittest.TestCase):
    def test_a_policy_may_not_name_a_star_twice(self) -> None:
        with self.assertRaises(ValueError):
            pol.BreakthroughPolicy("x", ((19, 21, 10_000), (19, 23, 3_000)))

    def test_a_policy_must_list_its_stars_in_order(self) -> None:
        with self.assertRaises(ValueError):
            pol.BreakthroughPolicy("x", ((20, 21, 10_000), (19, 21, 10_000)))

    def test_a_scroll_that_cannot_raise_the_star_is_rejected(self) -> None:
        # A scroll capped at 21 cannot be spent at 21: it would reach 22.
        with self.assertRaises(ValueError):
            pol.BreakthroughPolicy("x", ((21, 21, 10_000),))

    def test_a_scroll_that_is_not_sold_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            pol.BreakthroughPolicy("x", ((19, 26, 10_000),))

    def test_scroll_at_answers_only_for_the_stars_it_names(self) -> None:
        policy = pol.BreakthroughPolicy("x", ((19, 21, 10_000),))
        self.assertEqual(policy.scroll_at(19), (21, 10_000))
        self.assertIsNone(policy.scroll_at(18))
        self.assertEqual(policy.stars, (19,))

    def test_the_none_policy_never_scrolls(self) -> None:
        self.assertEqual(pol.NONE.entries, ())
        self.assertIsNone(pol.NONE.scroll_at(19))


class ValidationTest(unittest.TestCase):
    def test_an_owned_run_is_not_solved(self) -> None:
        with self.assertRaises(NotImplementedError):
            pol.optimal_policy(
                200, 22, 24, 1, RepairPolicy.FULL, start_mode=StartMode.OWNED
            )

    def test_a_target_below_the_start_raises(self) -> None:
        with self.assertRaises(ValueError):
            pol.optimal_policy(200, 20, 20, 1)

    def test_a_full_repair_run_past_the_trace_cap_is_refused(self) -> None:
        # Above 22 stars a destroyed item leaves a 22 star trace, so repairing
        # it does not return it to the star it was lost on. The recursion would
        # still produce a number; refusing is the only honest answer.
        for target in (24, 25, 30):
            with self.subTest(target=target):
                with self.assertRaises(NotImplementedError):
                    pol.optimal_policy(200, 20, target, 1, RepairPolicy.FULL)

    def test_the_highest_solvable_full_repair_target_is_23(self) -> None:
        # 23 is reached by attempts from 22 and below, every one of which leaves
        # a trace carrying its own star, so the recursion still holds there.
        self.assertEqual(pol.MAX_FULL_REPAIR_TARGET, 23)
        pol.optimal_policy(200, 20, 23, 1, RepairPolicy.FULL)

    def test_a_cheap_repair_run_is_unaffected_by_the_trace_cap(self) -> None:
        # TO_12 lands on 12 stars and re-scrolls to the start whatever star the
        # destruction happened on, so the target never breaks its recursion.
        for target in (24, 25, 30):
            with self.subTest(target=target):
                pol.optimal_policy(200, 20, target, 1, RepairPolicy.TO_12)

    def test_a_policy_outside_the_run_raises(self) -> None:
        policy = pol.BreakthroughPolicy("x", ((19, 21, 10_000),))
        with self.assertRaises(ValueError):
            pol.expected_total(policy, 200, 20, TARGET, 1)


class OptimalityTest(unittest.TestCase):
    """The solver's answer has to be the cheapest one, not merely a cheap one."""

    def enumerate_best(
        self, level: int, start: int, price: int, repair: RepairPolicy
    ) -> float:
        """Brute force the whole choice space for the cheapest expected total.

        Only tractable because the range is short and each star has few options;
        that is exactly why the solver exists. Any scroll usable at a star is
        allowed here, not just the cheapest per rate, so this would also catch
        the pruning being wrong.
        """
        stars = list(range(start, TARGET))
        choices = []
        for star in stars:
            options: list[tuple[int, int] | None] = [None]
            options.extend(
                (cap, rate)
                for cap, rate in data.BREAKTHROUGH_SCROLLS
                if star + 1 <= cap
            )
            choices.append(options)

        best = None
        stack: list[tuple[int, list[tuple[int, int, int]]]] = [(0, [])]
        while stack:
            index, chosen = stack.pop()
            if index == len(stars):
                policy = pol.BreakthroughPolicy("brute", tuple(chosen))
                total = pol.expected_total(
                    policy, level, start, TARGET, price, repair
                )
                if best is None or total < best:
                    best = total
                continue
            for option in choices[index]:
                nxt = chosen if option is None else chosen + [
                    (stars[index], option[0], option[1])
                ]
                stack.append((index + 1, nxt))
        assert best is not None
        return best

    def test_the_solver_matches_brute_force(self) -> None:
        # 20 star starts only: two decision points, so the brute force stays a
        # few hundred policies rather than tens of thousands.
        for name in ("頂培", "神秘", "控制核心", "永恆下三"):
            item = volatile_data.lookup(name)
            for repair in (RepairPolicy.FULL, RepairPolicy.TO_12):
                with self.subTest(equipment=name, repair=repair.value):
                    chosen = pol.optimal_policy(
                        item.level, 20, TARGET, item.price, repair
                    )
                    solved = pol.expected_total(
                        chosen, item.level, 20, TARGET, item.price, repair
                    )
                    brute = self.enumerate_best(item.level, 20, item.price, repair)
                    self.assertAlmostEqual(solved, brute, delta=1.0)

    def test_the_optimum_is_never_dearer_than_enhancing_throughout(self) -> None:
        for item in volatile_data.CATALOG.values():
            for start in (15, 19, 20):
                for repair in (RepairPolicy.FULL, RepairPolicy.TO_12):
                    with self.subTest(
                        equipment=item.name, start=start, repair=repair.value
                    ):
                        chosen = pol.optimal_policy(
                            item.level, start, TARGET, item.price, repair
                        )
                        best = pol.expected_total(
                            chosen, item.level, start, TARGET, item.price, repair
                        )
                        plain = pol.expected_total(
                            pol.NONE, item.level, start, TARGET, item.price, repair
                        )
                        self.assertLessEqual(best, plain + 1.0)

    def test_the_safe_policy_only_buys_certainty(self) -> None:
        for item in volatile_data.CATALOG.values():
            with self.subTest(equipment=item.name):
                chosen = pol.optimal_policy(
                    item.level,
                    15,
                    TARGET,
                    item.price,
                    RepairPolicy.FULL,
                    deterministic_only=True,
                )
                for _, _, success in chosen.entries:
                    self.assertEqual(success, data.RATE_BASIS)

    def test_a_scroll_is_only_named_where_it_beats_enhancing(self) -> None:
        # Under FULL repair the stars are independent, so the choice at each one
        # can be checked on its own closed form.
        item = volatile_data.lookup("控制核心")
        chosen = pol.optimal_policy(item.level, 15, TARGET, item.price, RepairPolicy.FULL)
        for star in range(15, TARGET):
            fee = rules.enhance_cost(item.level, star)
            success, destroy, _ = rules.enhance_rates(star)
            meso, pieces = rules.full_repair(item.level, rules.trace_star(star))
            enhance = (
                fee + (destroy / data.RATE_BASIS) * (meso + pieces * item.price)
            ) / (success / data.RATE_BASIS)
            scroll = chosen.scroll_at(star)
            with self.subTest(star=star):
                if scroll is None:
                    continue
                cost = rules.breakthrough_cost(*scroll) / (
                    scroll[1] / data.RATE_BASIS
                )
                self.assertLess(cost, enhance)


class SweepPoliciesTest(unittest.TestCase):
    def test_the_baseline_is_always_offered(self) -> None:
        item = volatile_data.lookup("控制核心")
        chosen = pol.sweep_policies(item.level, 15, TARGET, item.price)
        self.assertIs(chosen[0], pol.NONE)

    def test_identical_policies_are_not_measured_twice(self) -> None:
        # Cheap equipment never buys a scroll, so all three collapse to none.
        item = volatile_data.lookup("頂培")
        chosen = pol.sweep_policies(item.level, 15, TARGET, item.price)
        self.assertEqual(len(chosen), 1)
        self.assertEqual(chosen[0].entries, ())

    def test_dear_equipment_gets_all_three(self) -> None:
        item = volatile_data.lookup("控制核心")
        chosen = pol.sweep_policies(item.level, 15, TARGET, item.price)
        self.assertEqual([p.name for p in chosen], ["none", "optimal", "safe"])


class EngineAgreementTest(unittest.TestCase):
    """The closed form must be what the engine actually produces.

    A modest trial count with a fixed seed: this guards against the two drifting
    apart, not against sampling noise, so the tolerance is generous on purpose.
    Convergence itself was checked separately, out to 320,000 trials.
    """

    TRIALS = 20_000
    SEED = 20260731

    def test_the_engine_lands_on_the_solved_mean(self) -> None:
        for name in ("神秘", "控制核心"):
            item = volatile_data.lookup(name)
            for repair in (RepairPolicy.FULL, RepairPolicy.TO_12):
                chosen = pol.optimal_policy(item.level, 19, TARGET, item.price, repair)
                with self.subTest(equipment=name, repair=repair.value):
                    solved = pol.expected_total(
                        chosen, item.level, 19, TARGET, item.price, repair
                    )
                    config = RunConfig.for_equipment(
                        name,
                        19,
                        TARGET,
                        repair_policy=repair,
                        breakthrough_policy=chosen,
                    )
                    sampled = simulate(
                        config, trials=self.TRIALS, seed=self.SEED
                    ).total_cost.mean
                    self.assertAlmostEqual(sampled / solved, 1.0, delta=0.03)

    def test_a_certain_scroll_is_bought_exactly_once_per_star(self) -> None:
        # Three 100% scrolls, three purchases, every trial: nothing to average.
        policy = pol.BreakthroughPolicy(
            "certain", ((18, 21, 10_000), (19, 21, 10_000), (20, 21, 10_000))
        )
        config = RunConfig.for_equipment(
            "控制核心", 18, 21, breakthrough_policy=policy
        )
        summary = simulate(config, trials=200, seed=3)
        self.assertEqual(summary.breakthroughs.mean, 3.0)
        self.assertEqual(summary.mean_breakthroughs_by_scroll, {"21-10000": 3.0})
        self.assertEqual(summary.attempts.mean, 0.0)
        self.assertEqual(summary.destroys.mean, 0.0)

    def test_a_scrolled_star_is_never_enhanced(self) -> None:
        policy = pol.BreakthroughPolicy("x", ((19, 21, 10_000),))
        config = RunConfig.for_equipment(
            "控制核心", 19, TARGET, breakthrough_policy=policy
        )
        summary = simulate(config, trials=500, seed=4)
        self.assertNotIn(19, summary.mean_attempts_by_star)
        self.assertGreater(summary.mean_attempts_by_star[20], 0)


class RunConfigTest(unittest.TestCase):
    def test_a_policy_naming_a_star_outside_the_run_raises(self) -> None:
        policy = pol.BreakthroughPolicy("x", ((19, 21, 10_000),))
        with self.assertRaises(ValueError):
            RunConfig(
                level=200, start_star=20, target_star=22, breakthrough_policy=policy
            )

    def test_the_policy_reaches_the_serialised_config(self) -> None:
        policy = pol.BreakthroughPolicy("x", ((19, 21, 10_000),))
        config = RunConfig(
            level=200, start_star=19, target_star=22, breakthrough_policy=policy
        )
        self.assertEqual(
            config.to_dict()["breakthrough_policy"],
            {"name": "x", "entries": [[19, 21, 10_000]]},
        )


if __name__ == "__main__":
    unittest.main()
