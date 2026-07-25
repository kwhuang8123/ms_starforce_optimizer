"""Engine behaviour: config validation, scripted runs, and analytic anchors."""

from __future__ import annotations

import json
import random
import unittest

from starforce import rules, static_data as data
from starforce.engine import RepairPolicy, RunConfig, StartMode, simulate_once
from starforce.stats import simulate
from starforce.units import YI, format_meso, to_yi


class ScriptedRandom(random.Random):
    """Feeds ``randrange`` a fixed sequence so a run is fully deterministic."""

    def __init__(self, rolls):
        super().__init__()
        self._rolls = list(rolls)

    def randrange(self, *args, **kwargs):  # noqa: D102 - matches random.Random
        if not self._rolls:
            raise AssertionError("the run consumed more rolls than were scripted")
        return self._rolls.pop(0)


class RunConfigTest(unittest.TestCase):
    def test_start_star_below_the_scroll_range_raises(self) -> None:
        for star in (0, 9):
            with self.subTest(star=star):
                with self.assertRaises(ValueError):
                    RunConfig(level=140, start_star=star, target_star=25)

    def test_start_star_above_the_scroll_range_raises(self) -> None:
        with self.assertRaises(ValueError):
            RunConfig(level=140, start_star=21, target_star=25)

    def test_start_star_boundaries_are_accepted(self) -> None:
        RunConfig(level=140, start_star=10, target_star=11)
        RunConfig(level=140, start_star=20, target_star=21)

    def test_target_must_exceed_start(self) -> None:
        with self.assertRaises(ValueError):
            RunConfig(level=140, start_star=15, target_star=15)

    def test_target_beyond_the_cap_raises(self) -> None:
        with self.assertRaises(ValueError):
            RunConfig(level=140, start_star=15, target_star=31)

    def test_level_130_cannot_enter_the_destruction_range(self) -> None:
        RunConfig(level=130, start_star=10, target_star=15)
        with self.assertRaises(ValueError):
            RunConfig(level=130, start_star=10, target_star=16)

    def test_unsupported_level_raises(self) -> None:
        with self.assertRaises(ValueError):
            RunConfig(level=152, start_star=15, target_star=20)

    def test_to_dict(self) -> None:
        config = RunConfig(
            level=140, start_star=15, target_star=22, repair_policy=RepairPolicy.TO_12
        )
        self.assertEqual(
            config.to_dict(),
            {
                "level": 140,
                "start_star": 15,
                "target_star": 22,
                "repair_policy": "to_12",
                "start_mode": "scroll",
                "rebuild_cost": 0,
                "equipment_name": None,
                "equipment_price": 0,
            },
        )

    def test_negative_equipment_price_raises(self) -> None:
        with self.assertRaises(ValueError):
            RunConfig(
                level=140, start_star=15, target_star=22, equipment_price=-1
            )


class ForEquipmentTest(unittest.TestCase):
    def test_level_and_price_come_from_the_catalogue(self) -> None:
        config = RunConfig.for_equipment("控制核心", 15, 22)
        self.assertEqual(config.level, 200)
        self.assertEqual(config.equipment_name, "控制核心")
        self.assertEqual(config.equipment_price, 20_000_000_000)

    def test_an_alias_form_resolves_to_the_canonical_name(self) -> None:
        config = RunConfig.for_equipment("永恆上4", 15, 22)
        self.assertEqual(config.equipment_name, "永恆上四")
        self.assertEqual(config.level, 250)

    def test_repair_policy_is_forwarded(self) -> None:
        config = RunConfig.for_equipment(
            "頂培", 15, 22, repair_policy=RepairPolicy.TO_12
        )
        self.assertIs(config.repair_policy, RepairPolicy.TO_12)

    def test_unknown_equipment_raises(self) -> None:
        with self.assertRaises(ValueError):
            RunConfig.for_equipment("不存在的裝備", 15, 22)

    def test_a_level_130_equipment_would_still_hit_the_target_cap(self) -> None:
        # No catalogue entry is level 130 today, but the cap must still apply.
        config = RunConfig(level=130, start_star=10, target_star=15)
        self.assertEqual(config.target_star, 15)


class OwnedStartTest(unittest.TestCase):
    """Runs that begin from an item already at start_star."""

    REBUILD = 90_000_000_000  # 900e

    def owned(self, **kwargs) -> RunConfig:
        defaults = dict(
            level=200,
            start_star=22,
            target_star=23,
            start_mode=StartMode.OWNED,
        )
        return RunConfig(**{**defaults, **kwargs})

    def test_start_star_may_sit_above_the_scroll_range(self) -> None:
        config = self.owned(start_star=24, target_star=25)
        self.assertEqual(config.start_star, 24)

    def test_scroll_mode_still_rejects_the_same_star(self) -> None:
        with self.assertRaises(ValueError):
            RunConfig(level=200, start_star=24, target_star=25)

    def test_negative_start_star_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.owned(start_star=-1)

    def test_no_scroll_is_bought_at_the_start(self) -> None:
        config = self.owned()
        result = simulate_once(config, ScriptedRandom([0]))
        self.assertEqual(result.scrolls_used, 0)
        self.assertEqual(result.total_meso, rules.enhance_cost(200, 22))

    def test_full_repair_returns_to_the_22_star_trace(self) -> None:
        config = self.owned(start_star=23, target_star=24)
        # 23 -> 24 is (850, 1800, 7350): 1000 lands in the destruction band.
        result = simulate_once(config, ScriptedRandom([1000, 0, 0]))
        self.assertEqual(result.destroys, 1)
        self.assertEqual(result.equipment_used, 4)
        self.assertEqual(result.rebuild_cost, 0)
        # Destroyed at 23, repaired to 22, then 22 -> 23 -> 24.
        self.assertEqual(result.attempts_by_star, {23: 2, 22: 1})

    def test_cheap_repair_charges_the_rebuild_and_resumes_at_22(self) -> None:
        config = self.owned(
            start_star=23,
            target_star=24,
            repair_policy=RepairPolicy.TO_12,
            rebuild_cost=self.REBUILD,
            equipment_price=1_000_000_000,
        )
        result = simulate_once(config, ScriptedRandom([1000, 0, 0]))
        self.assertEqual(result.destroys, 1)
        self.assertEqual(result.equipment_used, 1)
        self.assertEqual(result.equipment_cost, 1_000_000_000)
        self.assertEqual(result.rebuild_cost, self.REBUILD)
        self.assertEqual(result.scrolls_used, 0)
        self.assertEqual(result.attempts_by_star, {23: 2, 22: 1})
        self.assertEqual(
            result.total_cost,
            result.total_meso + 1_000_000_000 + self.REBUILD,
        )

    def test_rebuild_cost_is_required_for_a_12_star_repair(self) -> None:
        with self.assertRaises(ValueError) as caught:
            self.owned(repair_policy=RepairPolicy.TO_12)
        self.assertIn("needs a positive rebuild_cost", str(caught.exception))

    def test_starting_below_the_rebuild_star_raises(self) -> None:
        with self.assertRaises(ValueError) as caught:
            self.owned(
                start_star=21,
                repair_policy=RepairPolicy.TO_12,
                rebuild_cost=self.REBUILD,
            )
        self.assertIn("must start at or above it", str(caught.exception))

    def test_rebuild_cost_is_rejected_where_it_does_not_apply(self) -> None:
        with self.assertRaises(ValueError):
            self.owned(rebuild_cost=self.REBUILD)  # OWNED + FULL
        with self.assertRaises(ValueError):
            RunConfig(  # SCROLL + TO_12
                level=200,
                start_star=19,
                target_star=22,
                repair_policy=RepairPolicy.TO_12,
                rebuild_cost=self.REBUILD,
            )

    def test_both_policies_follow_the_same_trajectory(self) -> None:
        # Destruction resumes at 22 either way, so only the charge differs.
        rolls = [1000, 0, 0]
        full = simulate_once(
            self.owned(start_star=23, target_star=24), ScriptedRandom(rolls)
        )
        cheap = simulate_once(
            self.owned(
                start_star=23,
                target_star=24,
                repair_policy=RepairPolicy.TO_12,
                rebuild_cost=self.REBUILD,
            ),
            ScriptedRandom(rolls),
        )
        self.assertEqual(full.attempts, cheap.attempts)
        self.assertEqual(full.destroys, cheap.destroys)
        self.assertEqual(full.attempts_by_star, cheap.attempts_by_star)

    def test_for_equipment_forwards_the_owned_mode(self) -> None:
        config = RunConfig.for_equipment(
            "控制核心",
            22,
            25,
            repair_policy=RepairPolicy.TO_12,
            start_mode=StartMode.OWNED,
            rebuild_cost=self.REBUILD,
        )
        self.assertIs(config.start_mode, StartMode.OWNED)
        self.assertEqual(config.rebuild_cost, self.REBUILD)
        self.assertEqual(config.level, 200)


class EquipmentCostTest(unittest.TestCase):
    PRICE = 1_000_000_000  # 10e

    def test_no_destruction_means_no_equipment_cost(self) -> None:
        config = RunConfig(
            level=140, start_star=10, target_star=13, equipment_price=self.PRICE
        )
        result = simulate_once(config, ScriptedRandom([0, 0, 0]))
        self.assertEqual(result.equipment_used, 0)
        self.assertEqual(result.equipment_cost, 0)
        self.assertEqual(result.total_cost, result.total_meso)

    def test_full_repair_charges_one_piece(self) -> None:
        config = RunConfig(
            level=140, start_star=15, target_star=16, equipment_price=self.PRICE
        )
        result = simulate_once(config, ScriptedRandom([3100, 0]))
        self.assertEqual(result.equipment_used, 1)
        self.assertEqual(result.equipment_cost, self.PRICE)
        self.assertEqual(result.total_cost, result.total_meso + self.PRICE)

    def test_a_22_star_trace_charges_four_pieces(self) -> None:
        config = RunConfig(
            level=140, start_star=20, target_star=26, equipment_price=self.PRICE
        )
        result = simulate_once(
            config, ScriptedRandom([0, 0, 0, 0, 0, 1000, 0, 0, 0, 0])
        )
        self.assertEqual(result.equipment_used, 4)
        self.assertEqual(result.equipment_cost, self.PRICE * 4)

    def test_cheap_repair_charges_one_piece_per_destruction(self) -> None:
        config = RunConfig(
            level=140,
            start_star=15,
            target_star=16,
            repair_policy=RepairPolicy.TO_12,
            equipment_price=self.PRICE,
        )
        result = simulate_once(config, ScriptedRandom([3100, 3100, 0]))
        self.assertEqual(result.destroys, 2)
        self.assertEqual(result.equipment_used, 2)
        self.assertEqual(result.equipment_cost, self.PRICE * 2)

    def test_price_zero_leaves_total_cost_equal_to_meso(self) -> None:
        config = RunConfig(level=140, start_star=15, target_star=16)
        result = simulate_once(config, ScriptedRandom([3100, 0]))
        self.assertEqual(result.equipment_used, 1)
        self.assertEqual(result.equipment_cost, 0)
        self.assertEqual(result.total_cost, result.total_meso)

    def test_base_equipment_is_not_charged(self) -> None:
        # A run that never gets destroyed pays nothing for the item it started
        # from: the base piece is a constant across every strategy.
        config = RunConfig(
            level=140, start_star=10, target_star=11, equipment_price=self.PRICE
        )
        result = simulate_once(config, ScriptedRandom([0]))
        self.assertEqual(result.equipment_cost, 0)


class ScriptedRunTest(unittest.TestCase):
    def test_run_starts_by_consuming_one_scroll(self) -> None:
        config = RunConfig(level=140, start_star=10, target_star=13)
        result = simulate_once(config, ScriptedRandom([0, 0, 0]))
        self.assertEqual(result.scrolls_used, 1)
        self.assertEqual(result.attempts, 3)
        self.assertEqual(result.destroys, 0)
        self.assertEqual(result.equipment_used, 0)
        self.assertEqual(
            result.total_meso,
            20_000_000
            + rules.enhance_cost(140, 10)
            + rules.enhance_cost(140, 11)
            + rules.enhance_cost(140, 12),
        )
        self.assertEqual(result.attempts_by_star, {10: 1, 11: 1, 12: 1})

    def test_maintain_repeats_the_same_star(self) -> None:
        config = RunConfig(level=140, start_star=10, target_star=11)
        # 10 -> 11 succeeds on 0-4999; 9999 maintains.
        result = simulate_once(config, ScriptedRandom([9999, 9999, 0]))
        self.assertEqual(result.attempts, 3)
        self.assertEqual(result.attempts_by_star, {10: 3})
        self.assertEqual(
            result.total_meso, 20_000_000 + rules.enhance_cost(140, 10) * 3
        )

    def test_full_repair_returns_to_the_trace_star(self) -> None:
        config = RunConfig(
            level=140, start_star=15, target_star=16, repair_policy=RepairPolicy.FULL
        )
        # 15 -> 16 is (3000, 210, 6790): 3100 lands in the destruction band.
        result = simulate_once(config, ScriptedRandom([3100, 0]))
        self.assertEqual(result.destroys, 1)
        self.assertEqual(result.equipment_used, 1)
        self.assertEqual(result.scrolls_used, 1)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(
            result.total_meso,
            40_000_000 + 39_138_900 + 149_000_000 + 39_138_900,
        )

    def test_cheap_repair_scrolls_back_to_the_starting_star(self) -> None:
        config = RunConfig(
            level=140, start_star=15, target_star=16, repair_policy=RepairPolicy.TO_12
        )
        result = simulate_once(config, ScriptedRandom([3100, 0]))
        self.assertEqual(result.destroys, 1)
        self.assertEqual(result.equipment_used, 1)
        # One scroll to start, one to climb back out of the 12 star repair.
        self.assertEqual(result.scrolls_used, 2)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(result.attempts_by_star, {15: 2})
        self.assertEqual(result.total_meso, 40_000_000 * 2 + 39_138_900 * 2)

    def test_cheap_repair_below_12_stars_needs_no_second_scroll(self) -> None:
        config = RunConfig(
            level=140, start_star=10, target_star=16, repair_policy=RepairPolicy.TO_12
        )
        # Climb 10 -> 15, get destroyed, land on 12, climb back to 16.
        rolls = [0, 0, 0, 0, 0, 3100, 0, 0, 0, 0]
        result = simulate_once(config, ScriptedRandom(rolls))
        self.assertEqual(result.destroys, 1)
        self.assertEqual(result.equipment_used, 1)
        self.assertEqual(result.scrolls_used, 1)
        self.assertEqual(result.attempts, 10)
        self.assertEqual(
            result.attempts_by_star, {10: 1, 11: 1, 12: 2, 13: 2, 14: 2, 15: 2}
        )

    def test_destruction_above_22_stars_leaves_a_22_star_trace(self) -> None:
        config = RunConfig(level=140, start_star=20, target_star=26)
        # Climb 20 -> 25, then 1000 lands in the (800, 1800, 7400) destroy band.
        rolls = [0, 0, 0, 0, 0, 1000, 0, 0, 0, 0]
        result = simulate_once(config, ScriptedRandom(rolls))
        self.assertEqual(result.destroys, 1)
        self.assertEqual(result.equipment_used, 4)
        self.assertEqual(result.scrolls_used, 1)
        self.assertEqual(result.attempts, 10)
        self.assertEqual(
            result.attempts_by_star, {20: 1, 21: 1, 22: 2, 23: 2, 24: 2, 25: 2}
        )

    def test_a_destroy_band_roll_cannot_destroy_below_15_stars(self) -> None:
        # 3100 destroys at 15 stars. Below 15 the destroy band is empty, so the
        # same roll can only succeed or maintain.
        config = RunConfig(level=140, start_star=10, target_star=15)
        result = simulate_once(config, ScriptedRandom([3100] * 5 + [0]))
        self.assertEqual(result.destroys, 0)
        self.assertEqual(result.equipment_used, 0)
        self.assertEqual(result.scrolls_used, 1)
        self.assertEqual(result.attempts, 6)
        # 3100 succeeds at 10-13 but only maintains at 14 (success band 3000).
        self.assertEqual(result.attempts_by_star, {10: 1, 11: 1, 12: 1, 13: 1, 14: 2})


class AnalyticAnchorTest(unittest.TestCase):
    """10 -> 15 has no destruction, so each attempt is an independent geometric
    trial and the exact expectations are known in closed form."""

    LEVEL = 140
    START = 10
    TARGET = 15
    TRIALS = 20_000

    def _expectations(self) -> tuple[float, float]:
        attempts = 0.0
        meso = float(rules.star_scroll_cost(self.START))
        for star in range(self.START, self.TARGET):
            success = data.ENHANCE_RATES[star][0] / data.RATE_BASIS
            attempts += 1 / success
            meso += rules.enhance_cost(self.LEVEL, star) / success
        return attempts, meso

    def test_monte_carlo_matches_the_closed_form(self) -> None:
        expected_attempts, expected_meso = self._expectations()
        summary = simulate(
            RunConfig(level=self.LEVEL, start_star=self.START, target_star=self.TARGET),
            trials=self.TRIALS,
            seed=20260725,
        )
        self.assertAlmostEqual(
            summary.attempts.mean / expected_attempts, 1.0, delta=0.02
        )
        self.assertAlmostEqual(summary.meso.mean / expected_meso, 1.0, delta=0.02)
        self.assertEqual(summary.destroys.mean, 0.0)
        self.assertEqual(summary.equipment.mean, 0.0)
        self.assertEqual(summary.scrolls.mean, 1.0)

    def test_mean_attempts_per_star_matches_one_over_p(self) -> None:
        summary = simulate(
            RunConfig(level=self.LEVEL, start_star=self.START, target_star=self.TARGET),
            trials=self.TRIALS,
            seed=20260725,
        )
        for star in range(self.START, self.TARGET):
            success = data.ENHANCE_RATES[star][0] / data.RATE_BASIS
            with self.subTest(star=star):
                self.assertAlmostEqual(
                    summary.mean_attempts_by_star[star] * success, 1.0, delta=0.05
                )


class UnitsTest(unittest.TestCase):
    def test_yi_is_ten_to_the_eighth(self) -> None:
        self.assertEqual(YI, 100_000_000)

    def test_to_yi(self) -> None:
        self.assertEqual(to_yi(19_180_000_000), 191.8)

    def test_format_meso(self) -> None:
        self.assertEqual(format_meso(19_180_000_000), "191.80億")
        self.assertEqual(format_meso(149_000_000), "1.49億")
        self.assertEqual(format_meso(1_234_500_000_000), "12,345.00億")

    def test_scroll_prices_round_trip_to_the_quoted_yi_figures(self) -> None:
        quoted = {
            10: 0.2,
            15: 0.4,
            16: 2.8,
            17: 15.8,
            18: 25.0,
            19: 64.0,
            20: 330.0,
        }
        for star, yi in quoted.items():
            with self.subTest(star=star):
                self.assertAlmostEqual(to_yi(rules.star_scroll_cost(star)), yi)


class SimulationSummaryTest(unittest.TestCase):
    def test_seed_makes_the_run_reproducible(self) -> None:
        config = RunConfig(level=140, start_star=15, target_star=18)
        first = simulate(config, trials=500, seed=7)
        second = simulate(config, trials=500, seed=7)
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_percentiles_are_ordered(self) -> None:
        summary = simulate(
            RunConfig(level=250, start_star=17, target_star=20), trials=2_000, seed=1
        )
        values = [summary.meso.percentiles[p] for p in (50, 75, 90, 95, 99)]
        self.assertEqual(values, sorted(values))
        self.assertLessEqual(summary.meso.minimum, summary.meso.percentiles[50])
        self.assertGreaterEqual(summary.meso.maximum, summary.meso.percentiles[99])

    def test_to_dict_carries_both_raw_meso_and_yi(self) -> None:
        summary = simulate(
            RunConfig(level=160, start_star=15, target_star=17), trials=200, seed=3
        )
        payload = summary.to_dict()
        self.assertAlmostEqual(
            payload["meso_yi"]["mean"] * YI, payload["meso"]["mean"], places=2
        )
        self.assertAlmostEqual(
            payload["meso_yi"]["percentiles"]["90"] * YI,
            payload["meso"]["percentiles"]["90"],
            places=2,
        )

    def test_to_dict_is_json_serialisable_and_carries_the_config(self) -> None:
        summary = simulate(
            RunConfig(level=160, start_star=15, target_star=17), trials=200, seed=3
        )
        payload = json.loads(json.dumps(summary.to_dict()))
        self.assertEqual(payload["config"]["level"], 160)
        self.assertEqual(payload["config"]["start_star"], 15)
        self.assertEqual(payload["config"]["target_star"], 17)

    def test_total_cost_is_meso_plus_equipment_cost(self) -> None:
        summary = simulate(
            RunConfig.for_equipment("控制核心", 15, 20), trials=2_000, seed=11
        )
        self.assertAlmostEqual(
            summary.total_cost.mean,
            summary.meso.mean + summary.equipment_cost.mean,
            places=2,
        )
        self.assertGreater(summary.equipment_cost.mean, 0)

    def test_equipment_cost_tracks_the_piece_count(self) -> None:
        config = RunConfig.for_equipment("眼罩", 15, 20)
        summary = simulate(config, trials=2_000, seed=12)
        self.assertAlmostEqual(
            summary.equipment_cost.mean,
            summary.equipment.mean * config.equipment_price,
            places=2,
        )

    def test_report_names_the_equipment(self) -> None:
        summary = simulate(
            RunConfig.for_equipment("苦痛", 15, 18), trials=200, seed=13
        )
        report = summary.report()
        self.assertIn("equipment=苦痛", report)
        self.assertIn("total", report)
        self.assertIn("equip cost", report)

    def test_report_shows_meso_in_yi(self) -> None:
        summary = simulate(
            RunConfig(level=140, start_star=15, target_star=18), trials=200, seed=5
        )
        report = summary.report()
        self.assertIn("億", report)
        self.assertIn("level 140  15 -> 18 stars", report)
        self.assertIn(format_meso(summary.meso.mean), report)

    def test_trials_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            simulate(RunConfig(level=140, start_star=10, target_star=11), trials=0)


if __name__ == "__main__":
    unittest.main()

