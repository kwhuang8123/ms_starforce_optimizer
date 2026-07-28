"""The committed docs/data must still match what build_site_data.py produces.

The front end runs a JavaScript port of the rules, so ``docs/data/static.json``
is the only thing standing between a table edit in Python and a browser quietly
simulating the old numbers. These tests rebuild the deterministic files and
compare, so editing :mod:`starforce.static_data` or the engine without re-running
``build_site_data.py`` fails here rather than on the published page.

The sweep snapshots are deliberately not compared: they are copies of whatever
``sweep.py`` last wrote, and that file is rewritten at every checkpoint of a
running sweep.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import build_site_data
from starforce import rules
from starforce import static_data as data

DATA_DIR = Path(build_site_data.OUTPUT_DIR)


def read(name: str):
    path = DATA_DIR / name
    if not path.is_file():
        raise AssertionError(f"{path} is missing; run build_site_data.py")
    return json.loads(path.read_text(encoding="utf-8"))


class StaticDataTest(unittest.TestCase):
    def test_the_committed_file_matches_a_fresh_build(self) -> None:
        self.assertEqual(read("static.json"), build_site_data.build_static())

    def test_it_carries_every_published_table(self) -> None:
        payload = read("static.json")
        self.assertEqual(payload["rate_basis"], data.RATE_BASIS)
        self.assertEqual(len(payload["enhance_rates"]), len(data.ENHANCE_RATES))
        self.assertEqual(len(payload["enhance_cost"]), len(data.ENHANCE_COST))
        self.assertEqual(len(payload["repair_meso"]), len(data.REPAIR_MESO))
        self.assertEqual(payload["repair_equipment"]["22"], data.REPAIR_EQUIPMENT[22])

    def test_the_level_130_cap_is_precomputed_not_left_to_the_port(self) -> None:
        payload = read("static.json")
        self.assertEqual(payload["max_star"]["130"], 20)
        self.assertEqual(payload["max_target_star"]["130"], rules.max_target_star(130))
        self.assertEqual(payload["max_target_star"]["150"], 30)


class PricesTest(unittest.TestCase):
    def test_the_committed_file_matches_a_fresh_build(self) -> None:
        self.assertEqual(read("prices.json"), build_site_data.build_prices())

    def test_every_scroll_star_is_present(self) -> None:
        payload = read("prices.json")
        self.assertEqual(
            sorted(int(star) for star in payload["star_scroll_cost"]),
            list(data.STAR_SCROLL_STARS),
        )


class ParityTest(unittest.TestCase):
    """Replaying a stored case through Python must still produce its expected."""

    def setUp(self) -> None:
        self.payload = read("parity.json")

    def test_every_case_still_reproduces(self) -> None:
        rebuilt = build_site_data.build_parity()
        for stored, fresh in zip(self.payload["cases"], rebuilt["cases"]):
            with self.subTest(case=stored["name"]):
                self.assertEqual(stored, fresh)

    def test_the_case_list_has_not_changed(self) -> None:
        rebuilt = build_site_data.build_parity()
        self.assertEqual(
            [case["name"] for case in self.payload["cases"]],
            [case["name"] for case in rebuilt["cases"]],
        )

    def test_the_scroll_prices_the_cases_were_built_on_ride_along(self) -> None:
        # selftest.html prices its scroll actions from this, not from prices.json.
        self.assertEqual(
            sorted(int(star) for star in self.payload["star_scroll_cost"]),
            list(data.STAR_SCROLL_STARS),
        )

    def test_the_cases_cover_the_paths_worth_guarding(self) -> None:
        kinds = {case["kind"] for case in self.payload["cases"]}
        self.assertEqual(kinds, {"auto", "manual"})

        actions = {
            entry["action"]
            for case in self.payload["cases"]
            for entry in case["expected"]["log"]
        }
        self.assertEqual(
            actions, {"enhance", "scroll", "repair_full", "repair_to_12"}
        )

        outcomes = {
            entry["outcome"]
            for case in self.payload["cases"]
            for entry in case["expected"]["log"]
            if entry["outcome"] is not None
        }
        self.assertEqual(outcomes, {"success", "maintain", "destroy"})

        stops = {
            case["expected"]["stop_reason"]
            for case in self.payload["cases"]
            if case["kind"] == "auto"
        }
        self.assertEqual(stops, {"reached_target", "budget_exhausted"})

    def test_a_case_consumes_exactly_the_rolls_it_stores(self) -> None:
        # The stored rolls are trimmed to what the run used, so a port that
        # draws a different number of rolls cannot silently pass.
        for case in self.payload["cases"]:
            with self.subTest(case=case["name"]):
                self.assertEqual(
                    len(case["rolls"]),
                    sum(
                        1
                        for entry in case["expected"]["log"]
                        if entry["action"] == "enhance"
                    ),
                )


class SiteFilesTest(unittest.TestCase):
    def test_the_pages_and_scripts_are_committed(self) -> None:
        root = DATA_DIR.parent
        for name in (
            "index.html",
            "selftest.html",
            "styles.css",
            ".nojekyll",
            "js/app.js",
            "js/rules.js",
            "js/session.js",
            "js/autorun.js",
            "js/format.js",
            "js/prices-store.js",
            "js/ui-play.js",
            "js/ui-data.js",
            "js/ui-prices.js",
        ):
            with self.subTest(name=name):
                self.assertTrue((root / name).is_file(), f"{name} is missing")

    def test_the_sweep_snapshots_parse(self) -> None:
        for name in ("simulations.json", "marginal.json"):
            path = DATA_DIR / name
            if not path.is_file():
                continue
            with self.subTest(name=name):
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertIn("meta", payload)
                self.assertTrue(payload["results"])
                row = payload["results"][0]
                self.assertIn("total_cost_percentiles", row)
                self.assertIn("95", row["total_cost_percentiles"])


if __name__ == "__main__":
    unittest.main()
