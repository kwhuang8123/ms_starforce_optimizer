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


class RepriceTest(unittest.TestCase):
    """The split the page re-prices from must add back up to what it came from.

    Everything here rides on one property: no price can change a trajectory, so
    the mean is exactly linear in the prices. If the engine ever gains a
    price-dependent decision - a run that buys the cheaper of two scrolls, say -
    these break, which is the point.
    """

    #: Meso means are shipped rounded to whole meso, so a reconstruction can
    #: land one meso either side. The figures being checked run to 1e10, which
    #: makes this a rounding allowance rather than a fudge factor.
    TOLERANCE = 1.0

    def rows(self):
        for name in ("simulations.json", "marginal.json"):
            path = DATA_DIR / name
            if not path.is_file():
                continue
            for row in json.loads(path.read_text(encoding="utf-8"))["results"]:
                yield name, row

    def test_the_static_part_plus_the_scrolls_rebuilds_the_meso_mean(self) -> None:
        prices = build_site_data.build_prices()["star_scroll_cost"]
        for name, row in self.rows():
            with self.subTest(dataset=name, row=row["equipment"], target=row["target_star"]):
                scroll_price = (
                    0 if row["scroll_star"] is None else prices[str(row["scroll_star"])]
                )
                rebuilt = row["static_meso_mean"] + row["scrolls_mean"] * scroll_price
                self.assertAlmostEqual(rebuilt, row["meso_mean"], delta=self.TOLERANCE)

    def test_the_four_parts_rebuild_the_total(self) -> None:
        prices = build_site_data.build_prices()["star_scroll_cost"]
        for name, row in self.rows():
            with self.subTest(dataset=name, row=row["equipment"], target=row["target_star"]):
                scroll_price = (
                    0 if row["scroll_star"] is None else prices[str(row["scroll_star"])]
                )
                rebuilt = (
                    row["static_meso_mean"]
                    + row["scrolls_mean"] * scroll_price
                    + row["equipment_mean"] * row["equipment_price"]
                    + row["rebuild_count_mean"] * row["rebuild_cost"]
                )
                self.assertAlmostEqual(
                    rebuilt, row["total_cost_mean"], delta=self.TOLERANCE
                )

    def test_only_a_scrolled_run_carries_a_scroll_star(self) -> None:
        for name, row in self.rows():
            with self.subTest(dataset=name, mode=row["start_mode"]):
                if row["start_mode"] == "scroll":
                    self.assertEqual(row["scroll_star"], row["start_star"])
                    self.assertGreaterEqual(row["scrolls_mean"], 1.0)
                else:
                    self.assertIsNone(row["scroll_star"])
                    self.assertEqual(row["scrolls_mean"], 0.0)

    def test_a_rebuild_count_appears_only_where_a_rebuild_is_priced(self) -> None:
        for name, row in self.rows():
            with self.subTest(dataset=name, policy=row["repair_policy"]):
                if row["rebuild_cost"] == 0:
                    self.assertEqual(row["rebuild_count_mean"], 0.0)
                else:
                    self.assertGreater(row["rebuild_count_mean"], 0.0)

    def test_the_golden_cases_were_measured_not_derived(self) -> None:
        # The expectation must come from a second simulation at the new prices,
        # not from applying the same formula twice. Both halves must therefore
        # be present and the prices must actually differ.
        cases = read("parity.json")["reprice"]
        self.assertTrue(cases)
        shipped = build_site_data.build_prices()
        for case in cases:
            with self.subTest(case=case["name"]):
                self.assertNotEqual(case["prices"], shipped)
                self.assertIn("expected_total_cost_mean", case)
                self.assertIn("static_meso_mean", case["row"])

    def test_repricing_a_golden_case_lands_on_the_measured_mean(self) -> None:
        # The same arithmetic docs/js/reprice.js performs, checked here too so a
        # failure points at the data rather than only at the browser.
        for case in read("parity.json")["reprice"]:
            row = case["row"]
            prices = case["prices"]
            with self.subTest(case=case["name"]):
                scroll_price = (
                    0
                    if row["scroll_star"] is None
                    else prices["star_scroll_cost"][str(row["scroll_star"])]
                )
                equipment_price = next(
                    item["price"]
                    for item in prices["equipment"]
                    if item["name"] == row["equipment"]
                )
                repriced = round(
                    row["static_meso_mean"]
                    + row["scrolls_mean"] * scroll_price
                    + row["equipment_mean"] * equipment_price
                    + row["rebuild_count_mean"] * case["rebuild_cost"]
                )
                self.assertAlmostEqual(
                    repriced,
                    case["expected_total_cost_mean"],
                    delta=self.TOLERANCE,
                )

    def test_the_rebuild_term_is_exercised_by_a_case(self) -> None:
        # Without this the rebuild multiplier could be dropped entirely and
        # every remaining case would still pass.
        cases = read("parity.json")["reprice"]
        rebuilding = [case for case in cases if case["rebuild_cost"] > 0]
        self.assertTrue(rebuilding, "no re-pricing case rebuilds")
        for case in rebuilding:
            with self.subTest(case=case["name"]):
                self.assertGreater(case["row"]["rebuild_count_mean"], 0)
                self.assertNotEqual(case["rebuild_cost"], case["row"]["rebuild_cost"])


class AssetManifestTest(unittest.TestCase):
    """Artwork is optional, but a path that points nowhere is a typo, not a choice.

    The page degrades to text when a file is missing, which is exactly what makes
    a mistyped path easy to miss on screen - so it gets caught here instead.
    """

    def setUp(self) -> None:
        self.root = DATA_DIR.parent
        path = self.root / "assets" / "manifest.json"
        if not path.is_file():
            self.skipTest("no asset manifest committed")
        self.manifest = json.loads(path.read_text(encoding="utf-8"))

    def paths(self):
        for name, path in (self.manifest.get("equipment") or {}).items():
            yield name, path
        if self.manifest.get("scroll"):
            yield "scroll", self.manifest["scroll"]

    def test_every_referenced_file_exists(self) -> None:
        for name, path in self.paths():
            with self.subTest(name=name, path=path):
                self.assertTrue(
                    (self.root / path).is_file(), f"{path} 不存在（{name}）"
                )

    def test_paths_are_relative_to_the_site_root(self) -> None:
        # An absolute path would work locally and break under the project's
        # /ms_starforce_optimizer/ prefix on GitHub Pages.
        for name, path in self.paths():
            with self.subTest(name=name):
                self.assertFalse(path.startswith("/"), f"{path} 不可以用絕對路徑")

    def test_named_equipment_is_in_the_catalogue(self) -> None:
        known = {item["name"] for item in build_site_data.build_prices()["equipment"]}
        for name in (self.manifest.get("equipment") or {}):
            with self.subTest(name=name):
                self.assertIn(name, known, f"{name} 不在 data/volatile.json 的目錄裡")


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
            "js/assets.js",
            "js/ui-play.js",
            "js/ui-best.js",
            "js/ui-data.js",
            "js/ui-prices.js",
            "js/reprice.js",
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
