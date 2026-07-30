"""Hand-driven session behaviour: validation, one action at a time, and the log."""

from __future__ import annotations

import json
import unittest

from starforce import rules
from starforce.engine import RepairPolicy
from starforce.session import Session
from starforce.units import YI

from .test_engine import ScriptedRandom


def scripted(session: Session, rolls) -> Session:
    """Replace the session's rng so its attempts are fully deterministic."""
    session.rng = ScriptedRandom(rolls)
    return session


class SessionConfigTest(unittest.TestCase):
    def test_a_fresh_item_starts_at_zero_stars_for_free(self) -> None:
        session = Session(level=150)
        self.assertEqual(session.star, 0)
        self.assertEqual(session.total_cost, 0)
        self.assertEqual(session.log, [])

    def test_start_star_may_sit_anywhere_up_to_the_cap(self) -> None:
        self.assertEqual(Session(level=150, start_star=25).star, 25)
        self.assertEqual(Session(level=150, start_star=30).star, 30)

    def test_start_star_beyond_the_cap_raises(self) -> None:
        with self.assertRaises(ValueError):
            Session(level=150, start_star=31)

    def test_negative_start_star_raises(self) -> None:
        with self.assertRaises(ValueError):
            Session(level=150, start_star=-1)

    def test_unsupported_level_raises(self) -> None:
        for level in (130, 152):
            with self.subTest(level=level):
                with self.assertRaises(ValueError):
                    Session(level=level)

    def test_negative_equipment_price_raises(self) -> None:
        with self.assertRaises(ValueError):
            Session(level=150, equipment_price=-1)

    def test_for_equipment_takes_level_and_price_from_the_catalogue(self) -> None:
        session = Session.for_equipment("控制核心", start_star=22)
        self.assertEqual(session.level, 200)
        self.assertEqual(session.equipment_name, "控制核心")
        self.assertEqual(session.equipment_price, 20_000_000_000)
        self.assertEqual(session.star, 22)

    def test_for_equipment_resolves_an_alias(self) -> None:
        session = Session.for_equipment("永恆上4")
        self.assertEqual(session.equipment_name, "永恆上四")
        self.assertEqual(session.level, 250)

    def test_the_seed_makes_a_session_reproducible(self) -> None:
        def run() -> list[int]:
            session = Session(level=150, start_star=10, seed=99)
            for _ in range(20):
                if session.destroyed:
                    session.repair(RepairPolicy.FULL)
                else:
                    session.enhance()
            return [entry.star_after for entry in session.log]

        self.assertEqual(run(), run())


class EnhanceTest(unittest.TestCase):
    def test_success_raises_the_star_and_charges_the_fee(self) -> None:
        session = scripted(Session(level=140, start_star=10), [0])
        entry = session.enhance()
        self.assertEqual(session.star, 11)
        self.assertEqual(entry.outcome, "success")
        self.assertEqual(entry.meso, rules.enhance_cost(140, 10))
        self.assertEqual(session.totals.attempts, 1)

    def test_maintain_leaves_the_star_but_still_charges(self) -> None:
        # 10 -> 11 succeeds on 0-4999, so 9999 maintains.
        session = scripted(Session(level=140, start_star=10), [9999])
        entry = session.enhance()
        self.assertEqual(session.star, 10)
        self.assertEqual(entry.outcome, "maintain")
        self.assertEqual(entry.meso, rules.enhance_cost(140, 10))

    def test_destroy_leaves_a_trace_and_blocks_further_enhancement(self) -> None:
        # 15 -> 16 is (3000, 210, 6790): 3100 lands in the destruction band.
        session = scripted(Session(level=140, start_star=15), [3100])
        entry = session.enhance()
        self.assertTrue(session.destroyed)
        self.assertEqual(entry.outcome, "destroy")
        self.assertEqual(session.star, 15)
        self.assertEqual(session.totals.destroys, 1)
        with self.assertRaises(ValueError):
            session.enhance()

    def test_destruction_above_22_stars_leaves_a_22_star_trace(self) -> None:
        # 25 -> 26 is (800, 1800, 7400): 1000 destroys.
        session = scripted(Session(level=140, start_star=25), [1000])
        entry = session.enhance()
        self.assertTrue(session.destroyed)
        self.assertEqual(session.star, 22)
        self.assertEqual(entry.star_before, 25)
        self.assertEqual(entry.star_after, 22)

    def test_below_15_stars_a_destroy_band_roll_cannot_destroy(self) -> None:
        session = scripted(Session(level=140, start_star=14), [3100])
        session.enhance()
        self.assertFalse(session.destroyed)
        self.assertEqual(session.star, 14)

    def test_enhancing_at_the_cap_raises(self) -> None:
        session = Session(level=140, start_star=30)
        with self.assertRaises(ValueError):
            session.enhance()

    def test_attempts_by_star_counts_every_attempt(self) -> None:
        session = scripted(Session(level=140, start_star=10), [9999, 9999, 0, 0])
        for _ in range(4):
            session.enhance()
        self.assertEqual(session.totals.attempts_by_star, {10: 3, 11: 1})


class ScrollTest(unittest.TestCase):
    def test_a_scroll_sets_the_star_and_charges_its_price(self) -> None:
        session = Session(level=140)
        entry = session.use_scroll(17)
        self.assertEqual(session.star, 17)
        self.assertEqual(entry.meso, rules.star_scroll_cost(17))
        self.assertEqual(session.totals.scrolls_used, 1)
        self.assertEqual(session.total_cost, rules.star_scroll_cost(17))

    def test_a_scroll_at_or_below_the_current_star_raises(self) -> None:
        session = Session(level=140, start_star=17)
        for star in (16, 17):
            with self.subTest(star=star):
                with self.assertRaises(ValueError):
                    session.use_scroll(star)

    def test_a_star_no_scroll_exists_for_raises(self) -> None:
        session = Session(level=140)
        for star in (9, 14, 21):
            with self.subTest(star=star):
                with self.assertRaises(ValueError):
                    session.use_scroll(star)

    def test_a_destroyed_item_cannot_be_scrolled(self) -> None:
        session = scripted(Session(level=140, start_star=15), [3100])
        session.enhance()
        with self.assertRaises(ValueError):
            session.use_scroll(17)


class BreakthroughTest(unittest.TestCase):
    def test_success_adds_exactly_one_star(self) -> None:
        session = scripted(Session(level=200, start_star=22), [2999])
        entry = session.use_breakthrough(24, 3_000)
        self.assertEqual(session.star, 23)
        self.assertEqual(entry.outcome, "success")
        self.assertEqual(entry.meso, rules.breakthrough_cost(24, 3_000))
        self.assertEqual(session.totals.breakthroughs_used, 1)

    def test_failure_leaves_the_star_alone_but_still_charges(self) -> None:
        session = scripted(Session(level=200, start_star=22), [3_000])
        entry = session.use_breakthrough(24, 3_000)
        self.assertEqual(session.star, 22)
        self.assertEqual(entry.outcome, "maintain")
        self.assertEqual(session.total_cost, rules.breakthrough_cost(24, 3_000))

    def test_a_miss_never_destroys(self) -> None:
        # The roll that would destroy a 22 star enhancement attempt is only a
        # miss here: this path has no destruction band at all.
        session = scripted(Session(level=200, start_star=22), [9_999])
        session.use_breakthrough(24, 3_000)
        self.assertFalse(session.destroyed)
        self.assertEqual(session.totals.destroys, 0)

    def test_a_100_percent_scroll_always_lands(self) -> None:
        session = scripted(Session(level=200, start_star=22), [9_999])
        session.use_breakthrough(23, 10_000)
        self.assertEqual(session.star, 23)

    def test_it_does_not_count_as_an_enhancement_attempt(self) -> None:
        # attempts and attempts_by_star feed the sweep datasets, which know
        # nothing about breakthrough scrolls.
        session = scripted(Session(level=200, start_star=22), [0])
        session.use_breakthrough(24, 3_000)
        self.assertEqual(session.totals.attempts, 0)
        self.assertEqual(session.totals.attempts_by_star, {})
        self.assertEqual(session.totals.scrolls_used, 0)

    def test_a_scroll_that_would_overshoot_its_cap_raises(self) -> None:
        session = Session(level=200, start_star=23)
        with self.assertRaises(ValueError):
            session.use_breakthrough(23, 10_000)

    def test_a_scroll_applies_from_well_below_its_cap(self) -> None:
        session = scripted(Session(level=200), [0])
        session.use_breakthrough(26, 3_000)
        self.assertEqual(session.star, 1)

    def test_a_scroll_that_is_not_sold_raises(self) -> None:
        session = Session(level=200, start_star=22)
        for pair in ((26, 10_000), (24, 4_000), (27, 10_000)):
            with self.subTest(pair=pair):
                with self.assertRaises(ValueError):
                    session.use_breakthrough(*pair)

    def test_the_level_cap_still_applies(self) -> None:
        session = Session(level=200, start_star=rules.max_target_star(200))
        with self.assertRaises(ValueError):
            session.use_breakthrough(26, 3_000)

    def test_a_destroyed_item_cannot_use_one(self) -> None:
        session = scripted(Session(level=140, start_star=15), [3100])
        session.enhance()
        with self.assertRaises(ValueError):
            session.use_breakthrough(23, 3_000)

    def test_a_rejected_scroll_charges_nothing(self) -> None:
        session = Session(level=200, start_star=23)
        with self.assertRaises(ValueError):
            session.use_breakthrough(23, 10_000)
        self.assertEqual(session.total_cost, 0)
        self.assertEqual(session.log, [])


class RepairTest(unittest.TestCase):
    PRICE = 1_000_000_000  # 10億

    def destroyed_at(self, star: int, roll: int) -> Session:
        session = scripted(
            Session(level=140, start_star=star, equipment_price=self.PRICE), [roll]
        )
        session.enhance()
        self.assertTrue(session.destroyed)
        return session

    def test_repairing_an_intact_item_raises(self) -> None:
        session = Session(level=140, start_star=15)
        with self.assertRaises(ValueError):
            session.repair(RepairPolicy.FULL)

    def test_full_repair_restores_the_trace_star(self) -> None:
        session = self.destroyed_at(15, 3100)
        entry = session.repair(RepairPolicy.FULL)
        self.assertFalse(session.destroyed)
        self.assertEqual(session.star, 15)
        self.assertEqual(entry.meso, 149_000_000)
        self.assertEqual(entry.equipment_used, 1)
        self.assertEqual(entry.equipment_cost, self.PRICE)

    def test_a_22_star_trace_costs_four_pieces(self) -> None:
        session = self.destroyed_at(25, 1000)
        entry = session.repair(RepairPolicy.FULL)
        self.assertEqual(session.star, 22)
        self.assertEqual(entry.equipment_used, 4)
        self.assertEqual(entry.equipment_cost, self.PRICE * 4)
        self.assertEqual(entry.meso, 14_100_000_000)

    def test_cheap_repair_lands_on_12_stars_for_one_piece(self) -> None:
        session = self.destroyed_at(25, 1000)
        entry = session.repair(RepairPolicy.TO_12)
        self.assertFalse(session.destroyed)
        self.assertEqual(session.star, rules.CHEAP_REPAIR_STAR)
        self.assertEqual(entry.meso, 0)
        self.assertEqual(entry.equipment_used, 1)
        self.assertEqual(entry.equipment_cost, self.PRICE)

    def test_equipment_is_free_when_no_price_is_given(self) -> None:
        session = scripted(Session(level=140, start_star=15), [3100])
        session.enhance()
        entry = session.repair(RepairPolicy.FULL)
        self.assertEqual(entry.equipment_cost, 0)
        self.assertEqual(session.total_cost, session.totals.total_meso)


class LogTest(unittest.TestCase):
    def build(self) -> Session:
        # Scroll to 15, get destroyed, repair to 12, then succeed once.
        session = scripted(
            Session(level=140, equipment_price=1_000_000_000), [3100, 0]
        )
        session.use_scroll(15)
        session.enhance()
        session.repair(RepairPolicy.TO_12)
        session.enhance()
        return session

    def test_entries_are_numbered_from_one_in_order(self) -> None:
        session = self.build()
        self.assertEqual([entry.index for entry in session.log], [1, 2, 3, 4])
        self.assertEqual(
            [entry.action for entry in session.log],
            ["scroll", "enhance", "repair_to_12", "enhance"],
        )

    def test_each_entry_records_the_running_total(self) -> None:
        session = self.build()
        totals = [entry.total_cost_after for entry in session.log]
        self.assertEqual(totals, sorted(totals))
        self.assertEqual(totals[-1], session.total_cost)

    def test_the_running_total_is_the_sum_of_every_action(self) -> None:
        session = self.build()
        self.assertEqual(
            sum(entry.cost for entry in session.log), session.total_cost
        )

    def test_star_after_chains_into_the_next_star_before(self) -> None:
        session = self.build()
        for previous, entry in zip(session.log, session.log[1:]):
            with self.subTest(index=entry.index):
                self.assertEqual(entry.star_before, previous.star_after)

    def test_rebuild_cost_stays_zero(self) -> None:
        # Climbing back after a cheap repair is charged action by action here.
        session = self.build()
        self.assertEqual(session.totals.rebuild_cost, 0)
        self.assertEqual(
            session.total_cost,
            session.totals.total_meso + session.totals.equipment_cost,
        )

    def test_to_dict_is_json_serialisable_and_carries_the_log(self) -> None:
        session = self.build()
        payload = json.loads(json.dumps(session.to_dict(), ensure_ascii=False))
        self.assertEqual(payload["level"], 140)
        self.assertEqual(len(payload["log"]), 4)
        self.assertEqual(payload["star"], 13)
        self.assertFalse(payload["destroyed"])
        self.assertEqual(payload["totals"]["total_cost"], session.total_cost)

    def test_to_dict_carries_both_raw_meso_and_yi(self) -> None:
        session = self.build()
        totals = session.to_dict()["totals"]
        self.assertAlmostEqual(totals["total_cost_yi"] * YI, totals["total_cost"], 2)

    def test_report_shows_the_log_and_the_totals_in_yi(self) -> None:
        session = self.build()
        report = session.report()
        self.assertIn("level 140", report)
        self.assertIn("repair_to_12", report)
        self.assertIn("億", report)
        self.assertIn("total", report)

    def test_headline_flags_a_destroyed_item(self) -> None:
        session = scripted(Session(level=140, start_star=15), [3100])
        session.enhance()
        self.assertIn("DESTROYED", session.headline())


if __name__ == "__main__":
    unittest.main()
