"""Automatic runs: stop reasons, the no-overspend rule, and engine parity."""

from __future__ import annotations

import json
import random
import unittest

from starforce import rules
from starforce.autorun import (
    AutoPolicy,
    StopReason,
    run_to_star,
    run_within_budget,
)
from starforce.engine import RepairPolicy, RunConfig, StartMode, simulate_once
from starforce.session import Session
from starforce.units import YI

from .test_engine import ScriptedRandom

HUGE_BUDGET = 10_000_000 * YI


def scripted(session: Session, rolls) -> Session:
    session.rng = ScriptedRandom(rolls)
    return session


class ValidationTest(unittest.TestCase):
    def test_a_non_positive_budget_raises(self) -> None:
        for budget in (0, -1):
            with self.subTest(budget=budget):
                with self.assertRaises(ValueError):
                    run_within_budget(Session(level=150), 20, budget)

    def test_a_target_past_the_level_cap_raises(self) -> None:
        with self.assertRaises(ValueError):
            run_within_budget(Session(level=150), 31, HUGE_BUDGET)
        with self.assertRaises(ValueError):
            run_within_budget(Session(level=130), 16, HUGE_BUDGET)

    def test_an_already_finished_session_stops_immediately(self) -> None:
        session = Session(level=150, start_star=22)
        result = run_within_budget(session, 22, HUGE_BUDGET)
        self.assertIs(result.stop_reason, StopReason.REACHED_TARGET)
        self.assertEqual(result.entries, ())
        self.assertEqual(result.spent, 0)

    def test_a_scroll_star_no_scroll_exists_for_raises(self) -> None:
        with self.assertRaises(ValueError):
            AutoPolicy(scroll_star=21)


class ReachTargetTest(unittest.TestCase):
    def test_it_stops_the_moment_the_target_is_hit(self) -> None:
        session = scripted(Session(level=140, start_star=10), [0, 0, 0])
        result = run_to_star(session, 13, HUGE_BUDGET)
        self.assertIs(result.stop_reason, StopReason.REACHED_TARGET)
        self.assertEqual(session.star, 13)
        self.assertEqual(len(result.entries), 3)
        self.assertEqual(session.totals.attempts, 3)

    def test_it_keeps_going_through_maintains(self) -> None:
        session = scripted(Session(level=140, start_star=10), [9999, 9999, 0])
        result = run_to_star(session, 11, HUGE_BUDGET)
        self.assertIs(result.stop_reason, StopReason.REACHED_TARGET)
        self.assertEqual(len(result.entries), 3)

    def test_it_repairs_a_destroyed_item_and_carries_on(self) -> None:
        session = scripted(
            Session(level=140, start_star=15, equipment_price=1_000_000_000),
            [3100, 0],
        )
        result = run_to_star(session, 16, HUGE_BUDGET, AutoPolicy(RepairPolicy.FULL))
        self.assertIs(result.stop_reason, StopReason.REACHED_TARGET)
        self.assertEqual(
            [entry.action for entry in result.entries],
            ["enhance", "repair_full", "enhance"],
        )
        self.assertEqual(session.star, 16)
        self.assertFalse(session.destroyed)

    def test_spent_covers_this_run_only(self) -> None:
        session = Session(level=140)
        session.use_scroll(15)
        scrolled = session.total_cost
        scripted(session, [0])
        result = run_to_star(session, 16, HUGE_BUDGET)
        self.assertEqual(result.spent, rules.enhance_cost(140, 15))
        self.assertEqual(session.total_cost, scrolled + result.spent)


class ScrollPolicyTest(unittest.TestCase):
    def test_the_scroll_goes_on_before_the_first_attempt(self) -> None:
        session = scripted(Session(level=140), [0])
        result = run_to_star(session, 16, HUGE_BUDGET, AutoPolicy(scroll_star=15))
        self.assertEqual(
            [entry.action for entry in result.entries], ["scroll", "enhance"]
        )
        self.assertEqual(session.totals.scrolls_used, 1)

    def test_no_scroll_once_the_item_is_already_above_it(self) -> None:
        session = scripted(Session(level=140, start_star=17), [0])
        result = run_to_star(session, 18, HUGE_BUDGET, AutoPolicy(scroll_star=15))
        self.assertEqual([entry.action for entry in result.entries], ["enhance"])

    def test_no_scroll_when_it_would_reach_the_target_on_its_own(self) -> None:
        # Scrolling to 15 to reach a 15 star target would be buying the answer,
        # which is not a climb the engine models either.
        session = scripted(Session(level=140, start_star=14), [0])
        result = run_to_star(session, 15, HUGE_BUDGET, AutoPolicy(scroll_star=15))
        self.assertEqual([entry.action for entry in result.entries], ["enhance"])

    def test_the_scroll_goes_back_on_after_a_cheap_repair(self) -> None:
        session = scripted(Session(level=140, start_star=15), [3100, 0])
        result = run_to_star(
            session,
            16,
            HUGE_BUDGET,
            AutoPolicy(RepairPolicy.TO_12, scroll_star=15),
        )
        self.assertEqual(
            [entry.action for entry in result.entries],
            ["enhance", "repair_to_12", "scroll", "enhance"],
        )
        self.assertEqual(session.star, 16)


class BudgetTest(unittest.TestCase):
    def test_a_budget_below_the_first_attempt_buys_nothing(self) -> None:
        session = Session(level=140, start_star=10)
        result = run_within_budget(session, 11, rules.enhance_cost(140, 10) - 1)
        self.assertIs(result.stop_reason, StopReason.BUDGET_EXHAUSTED)
        self.assertEqual(result.entries, ())
        self.assertEqual(session.total_cost, 0)

    def test_a_budget_of_exactly_one_attempt_buys_one(self) -> None:
        session = scripted(Session(level=140, start_star=10), [9999])
        result = run_within_budget(session, 11, rules.enhance_cost(140, 10))
        self.assertIs(result.stop_reason, StopReason.BUDGET_EXHAUSTED)
        self.assertEqual(len(result.entries), 1)

    def test_it_never_overspends(self) -> None:
        budget = 50 * YI
        session = scripted(Session(level=250, start_star=15), [9999] * 40)
        result = run_within_budget(session, 16, budget)
        self.assertIs(result.stop_reason, StopReason.BUDGET_EXHAUSTED)
        self.assertLessEqual(session.total_cost, budget)

    def test_the_budget_caps_the_lifetime_total_not_the_run(self) -> None:
        session = Session(level=140)
        session.use_scroll(15)
        scripted(session, [9999] * 10)
        result = run_within_budget(session, 16, session.total_cost)
        self.assertIs(result.stop_reason, StopReason.BUDGET_EXHAUSTED)
        self.assertEqual(result.entries, ())

    def test_a_repair_it_cannot_afford_stops_the_run_destroyed(self) -> None:
        # One attempt fits the budget; the repair that follows does not.
        session = scripted(
            Session(level=140, start_star=15, equipment_price=1_000_000_000), [3100]
        )
        budget = rules.enhance_cost(140, 15) + 1
        result = run_within_budget(session, 16, budget, AutoPolicy(RepairPolicy.FULL))
        self.assertIs(result.stop_reason, StopReason.BUDGET_EXHAUSTED)
        self.assertTrue(result.destroyed)
        self.assertTrue(session.destroyed)
        self.assertEqual(result.star, 15)
        self.assertEqual([entry.action for entry in result.entries], ["enhance"])

    def test_the_equipment_price_counts_against_the_budget(self) -> None:
        # The same run is affordable when repair equipment is valued at zero.
        rolls = [3100, 0]
        budget = (
            rules.enhance_cost(140, 15) * 2 + rules.full_repair(140, 15)[0] + 1
        )
        free = scripted(Session(level=140, start_star=15), list(rolls))
        self.assertIs(
            run_within_budget(free, 16, budget).stop_reason,
            StopReason.REACHED_TARGET,
        )

        priced = scripted(
            Session(level=140, start_star=15, equipment_price=1_000_000_000),
            list(rolls),
        )
        self.assertIs(
            run_within_budget(priced, 16, budget).stop_reason,
            StopReason.BUDGET_EXHAUSTED,
        )

    def test_to_dict_is_json_serialisable(self) -> None:
        session = scripted(Session(level=140, start_star=10), [0])
        result = run_to_star(session, 11, HUGE_BUDGET)
        payload = json.loads(json.dumps(result.to_dict()))
        self.assertEqual(payload["stop_reason"], "reached_target")
        self.assertEqual(payload["star"], 11)
        self.assertEqual(len(payload["entries"]), 1)


class EngineParityTest(unittest.TestCase):
    """The logged driver and the unlogged Monte Carlo path must agree.

    Both consume one ``randrange`` per attempt in the same order, so seeding
    them alike makes the two runs identical roll for roll. If this ever fails,
    ``autorun`` and ``engine.simulate_once`` have drifted apart.
    """

    LEVEL = 150
    PRICE = 20_000_000_000
    SEED = 20260728

    def compare(self, config: RunConfig, policy: AutoPolicy, start_star: int) -> None:
        expected = simulate_once(config, random.Random(self.SEED))

        session = Session(
            level=config.level,
            start_star=start_star,
            equipment_price=config.equipment_price,
            seed=self.SEED,
        )
        run_to_star(session, config.target_star, HUGE_BUDGET, policy)
        actual = session.totals

        self.assertEqual(actual.total_meso, expected.total_meso)
        self.assertEqual(actual.equipment_used, expected.equipment_used)
        self.assertEqual(actual.equipment_cost, expected.equipment_cost)
        self.assertEqual(actual.scrolls_used, expected.scrolls_used)
        self.assertEqual(actual.attempts, expected.attempts)
        self.assertEqual(actual.destroys, expected.destroys)
        self.assertEqual(actual.attempts_by_star, expected.attempts_by_star)
        self.assertEqual(actual.total_cost, expected.total_cost)

    def test_a_scrolled_full_repair_run_matches(self) -> None:
        self.compare(
            RunConfig(
                level=self.LEVEL,
                start_star=15,
                target_star=19,
                repair_policy=RepairPolicy.FULL,
                equipment_price=self.PRICE,
            ),
            AutoPolicy(RepairPolicy.FULL, scroll_star=15),
            start_star=0,
        )

    def test_a_scrolled_cheap_repair_run_matches(self) -> None:
        self.compare(
            RunConfig(
                level=self.LEVEL,
                start_star=15,
                target_star=19,
                repair_policy=RepairPolicy.TO_12,
                equipment_price=self.PRICE,
            ),
            AutoPolicy(RepairPolicy.TO_12, scroll_star=15),
            start_star=0,
        )

    def test_an_owned_run_with_no_scroll_matches(self) -> None:
        self.compare(
            RunConfig(
                level=self.LEVEL,
                start_star=22,
                target_star=24,
                repair_policy=RepairPolicy.FULL,
                start_mode=StartMode.OWNED,
                equipment_price=self.PRICE,
            ),
            AutoPolicy(RepairPolicy.FULL),
            start_star=22,
        )


if __name__ == "__main__":
    unittest.main()
