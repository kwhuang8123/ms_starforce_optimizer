"""The editable price file: parsing, validation, aliases and lookups."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from starforce import static_data, volatile_data


def write_payload(payload: dict) -> Path:
    """Dump ``payload`` to a temporary JSON file and return its path."""
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    )
    with handle:
        json.dump(payload, handle, ensure_ascii=False)
    return Path(handle.name)


class ReloadingTestCase(unittest.TestCase):
    """Restores the shipped data after a test points the module elsewhere."""

    def setUp(self) -> None:
        self.addCleanup(volatile_data.load)

    def load_payload(self, payload: dict) -> None:
        path = write_payload(payload)
        self.addCleanup(path.unlink, missing_ok=True)
        volatile_data.load(path)


class ShippedDataTest(unittest.TestCase):
    def test_source_is_the_default_file(self) -> None:
        self.assertEqual(volatile_data.SOURCE_PATH, volatile_data.DEFAULT_PATH)
        self.assertTrue(volatile_data.DEFAULT_PATH.is_file())

    def test_star_scroll_prices(self) -> None:
        self.assertEqual(
            volatile_data.STAR_SCROLL_COST,
            {
                15: 40_000_000,
                16: 280_000_000,
                17: 1_580_000_000,
                18: 2_500_000_000,
                19: 6_400_000_000,
                20: 33_000_000_000,
            },
        )

    def test_scroll_prices_never_decrease_with_star(self) -> None:
        prices = [
            volatile_data.STAR_SCROLL_COST[star]
            for star in static_data.STAR_SCROLL_STARS
        ]
        self.assertEqual(prices, sorted(prices))

    def test_catalogue(self) -> None:
        expected = {
            "頂培": (150, 150_000_000),
            "神秘": (200, 50_000_000),
            "永恆上四": (250, 300_000_000),
            "永恆下三": (250, 800_000_000),
            "口紅": (160, 500_000_000),
            "眼罩": (160, 1_000_000_000),
            "苦痛": (160, 2_000_000_000),
            "巨大": (200, 2_000_000_000),
            "控制核心": (200, 20_000_000_000),
        }
        self.assertEqual(set(volatile_data.CATALOG), set(expected))
        for name, (level, price) in expected.items():
            with self.subTest(name=name):
                item = volatile_data.CATALOG[name]
                self.assertEqual((item.level, item.price), (level, price))

    def test_every_level_is_supported(self) -> None:
        for item in volatile_data.CATALOG.values():
            with self.subTest(name=item.name):
                self.assertIn(item.level, static_data.SUPPORTED_LEVELS)


class LookupTest(unittest.TestCase):
    def test_canonical_name(self) -> None:
        item = volatile_data.lookup("控制核心")
        self.assertEqual((item.name, item.level, item.price), ("控制核心", 200, 20_000_000_000))

    def test_arabic_digits_match_chinese_numerals(self) -> None:
        self.assertIs(volatile_data.lookup("永恆上4"), volatile_data.lookup("永恆上四"))
        self.assertIs(volatile_data.lookup("永恆下3"), volatile_data.lookup("永恆下三"))

    def test_full_width_digits_match(self) -> None:
        self.assertIs(volatile_data.lookup("永恆上４"), volatile_data.lookup("永恆上四"))

    def test_surrounding_whitespace_is_ignored(self) -> None:
        self.assertIs(volatile_data.lookup("  頂培 "), volatile_data.lookup("頂培"))

    def test_unknown_name_lists_what_is_known(self) -> None:
        with self.assertRaises(ValueError) as caught:
            volatile_data.lookup("不存在的裝備")
        message = str(caught.exception)
        self.assertIn("unknown equipment", message)
        self.assertIn("頂培", message)

    def test_known_names_matches_the_catalogue(self) -> None:
        self.assertEqual(volatile_data.known_names(), list(volatile_data.CATALOG))


class AliasTest(ReloadingTestCase):
    def test_explicit_alias_resolves_to_the_canonical_entry(self) -> None:
        self.load_payload(
            {
                "star_scroll_cost": {str(s): 1 for s in static_data.STAR_SCROLL_STARS},
                "equipment": [
                    {
                        "name": "控制核心",
                        "level": 200,
                        "price": 1,
                        "aliases": ["核心", "control core"],
                    }
                ],
            }
        )
        for alias in ("核心", "control core", "Control Core", "控制核心"):
            with self.subTest(alias=alias):
                self.assertEqual(volatile_data.lookup(alias).name, "控制核心")

    def test_colliding_aliases_are_rejected(self) -> None:
        with self.assertRaises(ValueError) as caught:
            self.load_payload(
                {
                    "star_scroll_cost": {
                        str(s): 1 for s in static_data.STAR_SCROLL_STARS
                    },
                    "equipment": [
                        {"name": "永恆上四", "level": 250, "price": 1, "aliases": []},
                        {"name": "永恆上4", "level": 250, "price": 1, "aliases": []},
                    ],
                }
            )
        self.assertIn("must stay distinct after normalization", str(caught.exception))


class ValidationTest(ReloadingTestCase):
    def valid_payload(self) -> dict:
        return {
            "star_scroll_cost": {
                str(star): 1 for star in static_data.STAR_SCROLL_STARS
            },
            "equipment": [{"name": "測試", "level": 150, "price": 1, "aliases": []}],
        }

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            volatile_data.load(Path("no-such-file.json"))

    def test_invalid_json_raises(self) -> None:
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        with handle:
            handle.write("{not json")
        path = Path(handle.name)
        self.addCleanup(path.unlink, missing_ok=True)
        with self.assertRaises(ValueError) as caught:
            volatile_data.load(path)
        self.assertIn("not valid JSON", str(caught.exception))

    def test_missing_section_raises(self) -> None:
        payload = self.valid_payload()
        del payload["equipment"]
        with self.assertRaises(ValueError) as caught:
            self.load_payload(payload)
        self.assertIn("missing the 'equipment' section", str(caught.exception))

    def test_missing_scroll_star_raises(self) -> None:
        payload = self.valid_payload()
        del payload["star_scroll_cost"]["17"]
        with self.assertRaises(ValueError) as caught:
            self.load_payload(payload)
        self.assertIn("missing stars [17]", str(caught.exception))

    def test_extra_scroll_star_raises(self) -> None:
        payload = self.valid_payload()
        payload["star_scroll_cost"]["21"] = 1
        with self.assertRaises(ValueError) as caught:
            self.load_payload(payload)
        self.assertIn("no scroll exists for", str(caught.exception))

    def test_negative_price_raises(self) -> None:
        payload = self.valid_payload()
        payload["equipment"][0]["price"] = -1
        with self.assertRaises(ValueError) as caught:
            self.load_payload(payload)
        self.assertIn("must not be negative", str(caught.exception))

    def test_unsupported_level_raises(self) -> None:
        payload = self.valid_payload()
        payload["equipment"][0]["level"] = 152
        with self.assertRaises(ValueError) as caught:
            self.load_payload(payload)
        self.assertIn("supported levels are", str(caught.exception))

    def test_empty_catalogue_raises(self) -> None:
        payload = self.valid_payload()
        payload["equipment"] = []
        with self.assertRaises(ValueError) as caught:
            self.load_payload(payload)
        self.assertIn("'equipment' is empty", str(caught.exception))

    def test_duplicate_name_raises(self) -> None:
        payload = self.valid_payload()
        payload["equipment"].append(dict(payload["equipment"][0]))
        with self.assertRaises(ValueError) as caught:
            self.load_payload(payload)
        self.assertIn("is listed twice", str(caught.exception))

    def test_a_failed_load_leaves_the_previous_data_in_place(self) -> None:
        before = dict(volatile_data.CATALOG)
        payload = self.valid_payload()
        payload["equipment"][0]["price"] = -1
        with self.assertRaises(ValueError):
            self.load_payload(payload)
        self.assertEqual(volatile_data.CATALOG, before)


class ReloadPropagationTest(ReloadingTestCase):
    def test_rules_read_the_current_scroll_prices(self) -> None:
        from starforce import rules

        self.assertEqual(rules.star_scroll_cost(15), 40_000_000)
        payload = {
            "star_scroll_cost": {
                str(star): 777 for star in static_data.STAR_SCROLL_STARS
            },
            "equipment": [{"name": "測試", "level": 150, "price": 1, "aliases": []}],
        }
        self.load_payload(payload)
        self.assertEqual(rules.star_scroll_cost(15), 777)


if __name__ == "__main__":
    unittest.main()
