"""Guards against transcription errors in the official tables."""

from __future__ import annotations

import unittest

from starforce import static_data as data


class EnhanceRatesTest(unittest.TestCase):
    def test_covers_every_attempt_from_0_to_29(self) -> None:
        self.assertEqual(sorted(data.ENHANCE_RATES), list(range(30)))

    def test_every_row_sums_to_the_basis(self) -> None:
        for star, row in data.ENHANCE_RATES.items():
            with self.subTest(star=star):
                self.assertEqual(sum(row), data.RATE_BASIS)

    def test_no_destruction_below_15_stars(self) -> None:
        for star in range(15):
            with self.subTest(star=star):
                self.assertEqual(data.ENHANCE_RATES[star][1], 0)

    def test_destruction_on_every_attempt_from_15_stars(self) -> None:
        for star in range(15, 30):
            with self.subTest(star=star):
                self.assertGreater(data.ENHANCE_RATES[star][1], 0)

    def test_success_rate_rebounds_at_20_stars(self) -> None:
        # The announcement deliberately makes 20 -> 21 easier than 19 -> 20.
        self.assertEqual(data.ENHANCE_RATES[19][0], 1000)
        self.assertEqual(data.ENHANCE_RATES[20][0], 3000)

    def test_spot_checks_against_the_announcement(self) -> None:
        self.assertEqual(data.ENHANCE_RATES[0], (9500, 0, 500))
        self.assertEqual(data.ENHANCE_RATES[15], (3000, 210, 6790))
        self.assertEqual(data.ENHANCE_RATES[17], (1500, 680, 7820))
        self.assertEqual(data.ENHANCE_RATES[22], (1750, 1225, 7025))
        self.assertEqual(data.ENHANCE_RATES[29], (100, 1980, 7920))


class EnhanceCostTest(unittest.TestCase):
    def test_covers_every_supported_level(self) -> None:
        self.assertEqual(tuple(data.ENHANCE_COST), data.SUPPORTED_LEVELS)

    def test_every_level_reaches_30_stars(self) -> None:
        for level in data.SUPPORTED_LEVELS:
            with self.subTest(level=level):
                self.assertEqual(sorted(data.ENHANCE_COST[level]), list(range(30)))

    def test_spot_checks_against_the_announcement(self) -> None:
        self.assertEqual(data.ENHANCE_COST[140][0], 77_200)
        self.assertEqual(data.ENHANCE_COST[140][9], 763_200)
        self.assertEqual(data.ENHANCE_COST[150][14], 47_243_900)
        self.assertEqual(data.ENHANCE_COST[160][19], 444_652_400)
        self.assertEqual(data.ENHANCE_COST[200][24], 237_957_700)
        self.assertEqual(data.ENHANCE_COST[250][29], 1_013_810_000)

    def test_published_anomaly_is_preserved(self) -> None:
        # This reads like a typo but is exactly what the official table
        # publishes; the engine must not silently "fix" it.
        self.assertGreater(data.ENHANCE_COST[140][21], data.ENHANCE_COST[140][22])

    def test_first_ten_attempts_match_the_derived_formula(self) -> None:
        # cost = round_half_up_to_100(level^3 * (star + 1) / 36 + 1000), which
        # reproduces every published 0 -> 10 figure across all six levels.
        for level in data.SUPPORTED_LEVELS:
            for star in range(10):
                raw = level**3 * (star + 1) / 36 + 1000
                expected = int((raw + 50) // 100) * 100
                with self.subTest(level=level, star=star):
                    self.assertEqual(data.ENHANCE_COST[level][star], expected)


class RepairTest(unittest.TestCase):
    def test_every_supported_level_has_a_column(self) -> None:
        # A level without one could not be simulated into the destruction range,
        # which is exactly why level 130 is not supported.
        self.assertEqual(tuple(data.REPAIR_MESO), data.SUPPORTED_LEVELS)

    def test_every_level_covers_15_to_22_stars(self) -> None:
        for level in data.SUPPORTED_LEVELS:
            with self.subTest(level=level):
                self.assertEqual(sorted(data.REPAIR_MESO[level]), list(range(15, 23)))

    def test_equipment_counts(self) -> None:
        self.assertEqual(
            data.REPAIR_EQUIPMENT,
            {15: 1, 16: 1, 17: 1, 18: 1, 19: 2, 20: 2, 21: 3, 22: 4},
        )

    def test_spot_checks_against_the_event_page(self) -> None:
        self.assertEqual(data.REPAIR_MESO[140][15], 149_000_000)
        self.assertEqual(data.REPAIR_MESO[200][20], 23_500_000_000)
        self.assertEqual(data.REPAIR_MESO[250][22], 80_100_000_000)


class StarScrollTest(unittest.TestCase):
    def test_scrolls_cover_15_to_20_stars(self) -> None:
        # 10 to 14 were dropped: same price as each other, no destruction risk,
        # and no strategy worth measuring starts below 15.
        self.assertEqual(data.STAR_SCROLL_STARS, tuple(range(15, 21)))

    def test_prices_are_not_fixed_data(self) -> None:
        # Which scrolls exist is a rule; what they cost moves with the market
        # and lives in volatile_data.
        self.assertFalse(hasattr(data, "STAR_SCROLL_COST"))


class BreakthroughScrollTest(unittest.TestCase):
    def test_the_published_list(self) -> None:
        self.assertEqual(
            data.BREAKTHROUGH_SCROLLS,
            (
                (21, 10_000),
                (22, 10_000),
                (23, 3_000),
                (23, 5_000),
                (23, 10_000),
                (24, 3_000),
                (24, 5_000),
                (24, 10_000),
                (25, 3_000),
                (25, 5_000),
                (25, 10_000),
                (26, 3_000),
                (26, 5_000),
            ),
        )

    def test_no_scroll_is_listed_twice(self) -> None:
        self.assertEqual(
            len(set(data.BREAKTHROUGH_SCROLLS)), len(data.BREAKTHROUGH_SCROLLS)
        )

    def test_every_rate_is_a_real_probability(self) -> None:
        for cap_star, success in data.BREAKTHROUGH_SCROLLS:
            with self.subTest(cap_star=cap_star, success=success):
                self.assertGreater(success, 0)
                self.assertLessEqual(success, data.RATE_BASIS)

    def test_every_cap_is_reachable_by_enhancing(self) -> None:
        # A cap nothing can be enhanced to would make the scroll unusable.
        for cap_star, _ in data.BREAKTHROUGH_SCROLLS:
            with self.subTest(cap_star=cap_star):
                self.assertIn(cap_star - 1, data.ENHANCE_RATES)

    def test_ids_are_unique_and_readable(self) -> None:
        ids = [
            data.breakthrough_id(cap, success)
            for cap, success in data.BREAKTHROUGH_SCROLLS
        ]
        self.assertEqual(len(set(ids)), len(ids))
        self.assertEqual(data.breakthrough_id(23, 3_000), "23-3000")

    def test_prices_are_not_fixed_data(self) -> None:
        self.assertFalse(hasattr(data, "BREAKTHROUGH_SCROLL_COST"))


if __name__ == "__main__":
    unittest.main()

