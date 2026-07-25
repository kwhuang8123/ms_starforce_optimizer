"""Read the stored sweep dataset back in.

A marginal run - one that starts from an already-owned item - needs to know
what rebuilding that item costs after a 12 star repair. That figure is not
something to guess at: it is the cheapest mean total cost of taking the same
equipment to 22 stars, which the from-scratch sweep already measured. This
module pulls it out of ``starforce/sim_data/simulations.json``.

Everything raises rather than defaulting. A missing dataset or a missing
equipment means the marginal numbers would be built on a guess, which is worse
than not running at all.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .rules import REBUILD_STAR

#: Where the from-scratch sweep writes its dataset.
DEFAULT_PATH = Path(__file__).resolve().parent / "sim_data" / "simulations.json"


@dataclass(frozen=True)
class RebuildOption:
    """The cheapest measured way to take one equipment to the rebuild star."""

    equipment: str
    cost: int
    start_star: int
    repair_policy: str


@dataclass(frozen=True)
class RebuildBasis:
    """Every equipment's rebuild cost, plus where the figures came from."""

    source: Path
    #: ``generated_at`` of the dataset these came from, recorded so a marginal
    #: dataset can be checked against the prices it was actually built on.
    generated_at: str
    star: int
    options: dict[str, RebuildOption]

    def cost(self, equipment: str) -> int:
        option = self.options.get(equipment)
        if option is None:
            raise ValueError(
                f"{self.source} has no {self.star} star results for {equipment!r}; "
                f"it covers {sorted(self.options)}"
            )
        return option.cost


def load_dataset(path: Path | str | None = None) -> dict[str, Any]:
    """Read and lightly validate a sweep dataset."""
    source = Path(path) if path is not None else DEFAULT_PATH
    if not source.is_file():
        raise FileNotFoundError(
            f"sweep dataset not found: {source}; run sweep.py before a marginal sweep"
        )
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{source} is not valid JSON: {error}") from error

    if not isinstance(payload, dict):
        raise ValueError(f"{source} must contain a JSON object at the top level")
    for key in ("meta", "results"):
        if key not in payload:
            raise ValueError(f"{source} is missing the {key!r} section")
    if not isinstance(payload["results"], list):
        raise ValueError(f"{source} has a malformed 'results' section")
    return payload


def load_rebuild_basis(
    path: Path | str | None = None, star: int = REBUILD_STAR
) -> RebuildBasis:
    """Cheapest mean total cost of reaching ``star``, per equipment."""
    source = Path(path) if path is not None else DEFAULT_PATH
    payload = load_dataset(source)

    best: dict[str, RebuildOption] = {}
    for entry in payload["results"]:
        config = entry.get("config", {})
        if config.get("target_star") != star:
            continue
        name = config.get("equipment_name")
        if name is None:
            # A run configured by level alone prices equipment at zero, so its
            # total is not a rebuild cost for any particular item.
            continue
        mean = entry.get("total_cost", {}).get("mean")
        if not isinstance(mean, (int, float)):
            raise ValueError(f"{source} has a result with no total_cost.mean: {config}")

        option = RebuildOption(
            equipment=name,
            cost=round(mean),
            start_star=config.get("start_star"),
            repair_policy=config.get("repair_policy"),
        )
        current = best.get(name)
        if current is None or option.cost < current.cost:
            best[name] = option

    if not best:
        raise ValueError(
            f"{source} has no {star} star results with an equipment name; "
            f"run sweep.py with {star} in TARGET_STARS first"
        )

    generated_at = payload["meta"].get("generated_at")
    if not isinstance(generated_at, str):
        raise ValueError(f"{source} has no meta.generated_at")

    return RebuildBasis(
        source=source, generated_at=generated_at, star=star, options=best
    )
