"""Reading rebuild costs back out of a stored sweep dataset."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from starforce import sim_data_loader
from starforce.rules import REBUILD_STAR


def result(name: str, start_star: int, policy: str, target_star: int, mean: float) -> dict:
    return {
        "config": {
            "equipment_name": name,
            "start_star": start_star,
            "target_star": target_star,
            "repair_policy": policy,
        },
        "total_cost": {"mean": mean},
    }


class LoaderTestCase(unittest.TestCase):
    def write(self, payload: dict) -> Path:
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        with handle:
            json.dump(payload, handle, ensure_ascii=False)
        path = Path(handle.name)
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def payload(self, results: list[dict]) -> dict:
        return {"meta": {"generated_at": "2026-07-26T00:00:00+00:00"}, "results": results}


class ShippedDatasetTest(unittest.TestCase):
    def test_the_committed_dataset_covers_every_catalogue_equipment(self) -> None:
        from starforce import volatile_data

        basis = sim_data_loader.load_rebuild_basis()
        self.assertEqual(basis.star, REBUILD_STAR)
        self.assertEqual(sorted(basis.options), sorted(volatile_data.known_names()))
        for name, option in basis.options.items():
            with self.subTest(name=name):
                self.assertGreater(option.cost, 0)
                self.assertEqual(option.equipment, name)


class SelectionTest(LoaderTestCase):
    def test_the_cheapest_mean_wins(self) -> None:
        path = self.write(
            self.payload(
                [
                    result("頂培", 15, "full", REBUILD_STAR, 300.0),
                    result("頂培", 19, "to_12", REBUILD_STAR, 100.0),
                    result("頂培", 20, "full", REBUILD_STAR, 200.0),
                ]
            )
        )
        basis = sim_data_loader.load_rebuild_basis(path)
        option = basis.options["頂培"]
        self.assertEqual(option.cost, 100)
        self.assertEqual(option.start_star, 19)
        self.assertEqual(option.repair_policy, "to_12")

    def test_other_targets_are_ignored(self) -> None:
        path = self.write(
            self.payload(
                [
                    result("頂培", 15, "full", REBUILD_STAR, 300.0),
                    result("頂培", 15, "full", 25, 1.0),
                ]
            )
        )
        self.assertEqual(sim_data_loader.load_rebuild_basis(path).cost("頂培"), 300)

    def test_results_without_an_equipment_name_are_skipped(self) -> None:
        payload = self.payload([result("頂培", 15, "full", REBUILD_STAR, 300.0)])
        payload["results"].append(
            {
                "config": {
                    "equipment_name": None,
                    "start_star": 15,
                    "target_star": REBUILD_STAR,
                    "repair_policy": "full",
                },
                "total_cost": {"mean": 1.0},
            }
        )
        basis = sim_data_loader.load_rebuild_basis(self.write(payload))
        self.assertEqual(sorted(basis.options), ["頂培"])

    def test_generated_at_is_carried_through(self) -> None:
        path = self.write(
            self.payload([result("頂培", 15, "full", REBUILD_STAR, 300.0)])
        )
        basis = sim_data_loader.load_rebuild_basis(path)
        self.assertEqual(basis.generated_at, "2026-07-26T00:00:00+00:00")

    def test_cost_of_an_unknown_equipment_lists_what_is_covered(self) -> None:
        path = self.write(
            self.payload([result("頂培", 15, "full", REBUILD_STAR, 300.0)])
        )
        basis = sim_data_loader.load_rebuild_basis(path)
        with self.assertRaises(ValueError) as caught:
            basis.cost("控制核心")
        self.assertIn("頂培", str(caught.exception))


class ValidationTest(LoaderTestCase):
    def test_missing_file_raises(self) -> None:
        with self.assertRaises(FileNotFoundError) as caught:
            sim_data_loader.load_rebuild_basis(Path("no-such-dataset.json"))
        self.assertIn("run sweep.py", str(caught.exception))

    def test_invalid_json_raises(self) -> None:
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        with handle:
            handle.write("{not json")
        path = Path(handle.name)
        self.addCleanup(path.unlink, missing_ok=True)
        with self.assertRaises(ValueError) as caught:
            sim_data_loader.load_rebuild_basis(path)
        self.assertIn("not valid JSON", str(caught.exception))

    def test_missing_section_raises(self) -> None:
        path = self.write({"meta": {"generated_at": "x"}})
        with self.assertRaises(ValueError) as caught:
            sim_data_loader.load_rebuild_basis(path)
        self.assertIn("missing the 'results' section", str(caught.exception))

    def test_no_matching_target_raises(self) -> None:
        path = self.write(self.payload([result("頂培", 15, "full", 25, 1.0)]))
        with self.assertRaises(ValueError) as caught:
            sim_data_loader.load_rebuild_basis(path)
        self.assertIn("run sweep.py", str(caught.exception))

    def test_missing_mean_raises(self) -> None:
        entry = result("頂培", 15, "full", REBUILD_STAR, 300.0)
        entry["total_cost"] = {}
        path = self.write(self.payload([entry]))
        with self.assertRaises(ValueError) as caught:
            sim_data_loader.load_rebuild_basis(path)
        self.assertIn("no total_cost.mean", str(caught.exception))

    def test_missing_generated_at_raises(self) -> None:
        payload = self.payload([result("頂培", 15, "full", REBUILD_STAR, 300.0)])
        payload["meta"] = {}
        path = self.write(payload)
        with self.assertRaises(ValueError) as caught:
            sim_data_loader.load_rebuild_basis(path)
        self.assertIn("meta.generated_at", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
