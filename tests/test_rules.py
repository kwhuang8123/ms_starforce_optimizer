"""Rule lookups: caps, trace stars, repairs, star scrolls."""

from __future__ import annotations

import unittest

from starforce import rules, static_data as data


class LevelTest(unittest.TestCase):
    def test_unsupported_level_raises(self) -> None:
        with self.assertRaises(ValueError):
            rules.check_level(152)

    def test_caps(self) -> None:
        self.assertEqual(rules.max_star(130), 20)
        for level in (140, 150, 160, 200, 250):
            with self.subTest(level=level):
                self.assertEqual(rules.max_star(level), 30)

    def test_level_130_target_is_capped_below_the_destruction_range(self) -> None:
        # No level 130 repair column exists, so a destroyed 130 item has no
        # knowable cost; the engine refuses to enter that range at all.
        self.assertEqual(rules.max_target_star(130), rules.DESTROY_START_STAR)

    def test_other_levels_keep_their_real_cap(self) -> None:
        for level in (140, 150, 160, 200, 250):
            with self.subTest(level=level):
                self.assertEqual(rules.max_target_star(level), 30)


class EnhanceCostTest(unittest.TestCase):
    def test_plain_cost(self) -> None:
        self.assertEqual(rules.enhance_cost(140, 15), 39_138_900)

    def test_level_130_beyond_its_cap_raises(self) -> None:
        with self.assertRaises(ValueError):
            rules.enhance_cost(130, 20)


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

    def test_full_repair_at_level_130_raises(self) -> None:
        with self.assertRaises(ValueError):
            rules.full_repair(130, 15)

    def test_cheap_repair_costs_one_equipment_and_no_meso(self) -> None:
        self.assertEqual(rules.cheap_repair(), (0, 1))
        self.assertEqual(rules.CHEAP_REPAIR_STAR, 12)


class StartStarTest(unittest.TestCase):
    def test_range_matches_the_available_scrolls(self) -> None:
        self.assertEqual(rules.MIN_START_STAR, 10)
        self.assertEqual(rules.MAX_START_STAR, 20)

    def test_inside_the_range_is_accepted(self) -> None:
        for star in range(10, 21):
            with self.subTest(star=star):
                rules.check_start_star(star)

    def test_outside_the_range_raises(self) -> None:
        for star in (0, 9, 21, 25):
            with self.subTest(star=star):
                with self.assertRaises(ValueError):
                    rules.check_start_star(star)


class StarScrollTest(unittest.TestCase):
    def test_cost_is_returned(self) -> None:
        self.assertEqual(rules.star_scroll_cost(10), 20_000_000)
        self.assertEqual(rules.star_scroll_cost(17), 1_580_000_000)
        self.assertEqual(rules.star_scroll_cost(20), 33_000_000_000)

    def test_star_outside_the_scroll_range_raises(self) -> None:
        for star in (9, 21):
            with self.subTest(star=star):
                with self.assertRaises(ValueError):
                    rules.star_scroll_cost(star)


if __name__ == "__main__":
    unittest.main()

