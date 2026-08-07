"""Rule lookups: caps, trace stars, repairs, star scrolls."""

from __future__ import annotations

import unittest

from starforce import rules, static_data as data


class LevelTest(unittest.TestCase):
    def test_unsupported_level_raises(self) -> None:
        for level in (130, 152):
            with self.subTest(level=level):
                with self.assertRaises(ValueError):
                    rules.check_level(level)

    def test_caps(self) -> None:
        for level in data.SUPPORTED_LEVELS:
            with self.subTest(level=level):
                self.assertEqual(rules.max_star(level), 30)

    def test_every_supported_level_keeps_its_real_cap(self) -> None:
        # The target cap only drops below the star cap for a level with no
        # repair column, and no supported level is in that position.
        for level in data.SUPPORTED_LEVELS:
            with self.subTest(level=level):
                self.assertIn(level, data.REPAIR_MESO)
                self.assertEqual(rules.max_target_star(level), rules.max_star(level))


class EnhanceCostTest(unittest.TestCase):
    def test_plain_cost(self) -> None:
        self.assertEqual(rules.enhance_cost(140, 15), 39_138_900)

    def test_a_star_beyond_the_published_table_raises(self) -> None:
        # 29 -> 30 is the last published attempt.
        with self.assertRaises(ValueError):
            rules.enhance_cost(140, 30)


class EnhanceRatesTest(unittest.TestCase):
    def test_rates_are_returned_verbatim(self) -> None:
        self.assertEqual(rules.enhance_rates(17), (1500, 680, 7820))
        self.assertEqual(sum(rules.enhance_rates(17)), data.RATE_BASIS)

    def test_unknown_star_raises(self) -> None:
        with self.assertRaises(ValueError):
            rules.enhance_rates(30)


class TraceTest(unittest.TestCase):
    def test_below_15_stars_cannot_be_destroyed(self) -> None:
        with self.assertRaises(ValueError):
            rules.trace_star(14)

    def test_15_to_22_keeps_its_own_star(self) -> None:
        for star in range(15, 23):
            with self.subTest(star=star):
                self.assertEqual(rules.trace_star(star), star)

    def test_23_to_30_collapses_to_22(self) -> None:
        for star in range(23, 31):
            with self.subTest(star=star):
                self.assertEqual(rules.trace_star(star), 22)


class RepairTest(unittest.TestCase):
    def test_full_repair(self) -> None:
        self.assertEqual(rules.full_repair(250, 22), (80_100_000_000, 4))
        self.assertEqual(rules.full_repair(140, 15), (149_000_000, 1))

    def test_a_trace_outside_the_published_range_raises(self) -> None:
        # The repair table covers 15 to 22 star traces only.
        for trace in (14, 23):
            with self.subTest(trace=trace):
                with self.assertRaises(ValueError):
                    rules.full_repair(140, trace)

    def test_cheap_repair_costs_one_equipment_and_no_meso(self) -> None:
        self.assertEqual(rules.cheap_repair(), (0, 1))
        self.assertEqual(rules.CHEAP_REPAIR_STAR, 12)


class StartStarTest(unittest.TestCase):
    def test_range_matches_the_available_scrolls(self) -> None:
        self.assertEqual(rules.MIN_START_STAR, 15)
        self.assertEqual(rules.MAX_START_STAR, 20)

    def test_inside_the_range_is_accepted(self) -> None:
        for star in range(15, 21):
            with self.subTest(star=star):
                rules.check_start_star(star)

    def test_outside_the_range_raises(self) -> None:
        for star in (0, 9, 14, 21, 25):
            with self.subTest(star=star):
                with self.assertRaises(ValueError):
                    rules.check_start_star(star)


class StarScrollTest(unittest.TestCase):
    def test_cost_is_returned(self) -> None:
        self.assertEqual(rules.star_scroll_cost(15), 15_000_000)
        self.assertEqual(rules.star_scroll_cost(17), 700_000_000)
        self.assertEqual(rules.star_scroll_cost(20), 17_700_000_000)

    def test_star_outside_the_scroll_range_raises(self) -> None:
        for star in (9, 14, 21):
            with self.subTest(star=star):
                with self.assertRaises(ValueError):
                    rules.star_scroll_cost(star)


class BreakthroughTest(unittest.TestCase):
    def test_every_published_scroll_is_accepted(self) -> None:
        for cap_star, success in data.BREAKTHROUGH_SCROLLS:
            with self.subTest(cap_star=cap_star, success=success):
                rules.check_breakthrough(cap_star, success)

    def test_a_cap_and_rate_that_are_not_sold_together_raises(self) -> None:
        # 21 and 22 only exist at 100%, and 26 has no 100% version, so these
        # pairs are each made of two figures that do exist separately.
        for pair in ((21, 3_000), (22, 5_000), (26, 10_000), (27, 10_000)):
            with self.subTest(pair=pair):
                with self.assertRaises(ValueError):
                    rules.check_breakthrough(*pair)

    def test_cost_is_returned(self) -> None:
        self.assertEqual(rules.breakthrough_cost(21, 10_000), 15_200_000_000)
        self.assertEqual(rules.breakthrough_cost(23, 3_000), 8_700_000_000)
        self.assertEqual(rules.breakthrough_cost(26, 5_000), 380_000_000_000)

    def test_a_scroll_that_does_not_exist_has_no_cost(self) -> None:
        with self.assertRaises(ValueError):
            rules.breakthrough_cost(26, 10_000)

    def test_a_scroll_applies_from_anywhere_below_its_cap(self) -> None:
        # The cap limits where the scroll leaves the item, not where it is used
        # from, so a fresh item can buy any of them.
        self.assertEqual(
            rules.available_breakthroughs(0, 150), list(data.BREAKTHROUGH_SCROLLS)
        )

    def test_scrolls_drop_off_as_the_item_climbs(self) -> None:
        # At 22 stars the 21 and 22 caps are spent: +1 would overshoot both.
        self.assertEqual(
            rules.available_breakthroughs(22, 150),
            [
                scroll
                for scroll in data.BREAKTHROUGH_SCROLLS
                if scroll[0] >= 23
            ],
        )

    def test_the_last_scroll_goes_at_26_stars(self) -> None:
        self.assertEqual(rules.available_breakthroughs(25, 150), [(26, 3_000), (26, 5_000)])
        self.assertEqual(rules.available_breakthroughs(26, 150), [])

    def test_the_level_cap_applies_on_top(self) -> None:
        # Nothing may take an item past the level's own cap, scroll or not.
        cap = rules.max_target_star(150)
        self.assertEqual(rules.available_breakthroughs(cap, 150), [])


if __name__ == "__main__":
    unittest.main()

