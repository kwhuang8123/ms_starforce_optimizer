"""Volatile data: prices that move with the market.

Star scroll prices and equipment prices live in ``data/volatile.json`` rather
than in Python, so they can be edited without touching code - and so the
planned GitHub Pages editor has a single file to read and write. Anything the
official balance patch fixes lives in :mod:`starforce.static_data`.

Call :func:`load` to point the module at a different file, or to pick up edits
made while the process is running.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .static_data import STAR_SCROLL_STARS, SUPPORTED_LEVELS

#: Shipped location of the editable price file.
DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "volatile.json"

# Chinese numerals and full-width digits are folded to plain digits before a
# name is matched, so "永恆上四" and "永恆上4" resolve to the same equipment.
_DIGIT_FOLD = str.maketrans(
    {
        "０": "0", "１": "1", "２": "2", "３": "3", "４": "4",
        "５": "5", "６": "6", "７": "7", "８": "8", "９": "9",
        "〇": "0", "零": "0", "一": "1", "二": "2", "三": "3", "四": "4",
        "五": "5", "六": "6", "七": "7", "八": "8", "九": "9",
    }
)


@dataclass(frozen=True)
class Equipment:
    """One catalogue entry: what it is, what it costs, what else it is called."""

    name: str
    level: int
    price: int
    aliases: tuple[str, ...] = ()


def normalize(name: str) -> str:
    """Fold a name to its lookup key: no whitespace, digits in one form."""
    return "".join(name.split()).translate(_DIGIT_FOLD).casefold()


#: Star -> meso. Populated by :func:`load`.
STAR_SCROLL_COST: dict[int, int] = {}

#: Canonical name -> Equipment. Populated by :func:`load`.
CATALOG: dict[str, Equipment] = {}

#: Normalized name or alias -> Equipment. Populated by :func:`load`.
_INDEX: dict[str, Equipment] = {}

#: Where the current data came from.
SOURCE_PATH: Path = DEFAULT_PATH


def _require_positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer, got {value!r}")
    if value < 0:
        raise ValueError(f"{label} must not be negative, got {value}")
    return value


def _parse_scroll_costs(raw: Any) -> dict[int, int]:
    if not isinstance(raw, dict):
        raise ValueError("'star_scroll_cost' must be an object keyed by star")
    costs: dict[int, int] = {}
    for key, value in raw.items():
        try:
            star = int(key)
        except (TypeError, ValueError):
            raise ValueError(f"'star_scroll_cost' has a non-numeric key {key!r}") from None
        costs[star] = _require_positive_int(value, f"star_scroll_cost[{star}]")

    missing = [star for star in STAR_SCROLL_STARS if star not in costs]
    if missing:
        raise ValueError(f"'star_scroll_cost' is missing stars {missing}")
    extra = sorted(set(costs) - set(STAR_SCROLL_STARS))
    if extra:
        raise ValueError(
            f"'star_scroll_cost' has stars {extra} that no scroll exists for; "
            f"scrolls cover {STAR_SCROLL_STARS[0]} to {STAR_SCROLL_STARS[-1]}"
        )
    return costs


def _parse_equipment(raw: Any) -> tuple[dict[str, Equipment], dict[str, Equipment]]:
    if not isinstance(raw, list):
        raise ValueError("'equipment' must be a list of objects")

    catalog: dict[str, Equipment] = {}
    index: dict[str, Equipment] = {}

    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError(f"every 'equipment' entry must be an object, got {entry!r}")

        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"equipment entry has no usable 'name': {entry!r}")

        level = entry.get("level")
        if level not in SUPPORTED_LEVELS:
            raise ValueError(
                f"equipment {name!r} has level {level!r}; "
                f"supported levels are {SUPPORTED_LEVELS}"
            )

        price = _require_positive_int(entry.get("price"), f"equipment {name!r} price")

        raw_aliases = entry.get("aliases", [])
        if not isinstance(raw_aliases, list) or not all(
            isinstance(alias, str) for alias in raw_aliases
        ):
            raise ValueError(f"equipment {name!r} has a malformed 'aliases' list")

        item = Equipment(
            name=name, level=level, price=price, aliases=tuple(raw_aliases)
        )
        if name in catalog:
            raise ValueError(f"equipment {name!r} is listed twice")
        catalog[name] = item

        for label in (name, *item.aliases):
            key = normalize(label)
            if key in index and index[key] is not item:
                raise ValueError(
                    f"{label!r} resolves to both {index[key].name!r} and {name!r}; "
                    f"names and aliases must stay distinct after normalization"
                )
            index[key] = item

    if not catalog:
        raise ValueError("'equipment' is empty")
    return catalog, index


def load(path: Path | str | None = None) -> None:
    """Read the price file and replace this module's tables with its contents."""
    global STAR_SCROLL_COST, CATALOG, _INDEX, SOURCE_PATH

    source = Path(path) if path is not None else DEFAULT_PATH
    if not source.is_file():
        raise FileNotFoundError(f"volatile price file not found: {source}")

    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{source} is not valid JSON: {error}") from error

    if not isinstance(payload, dict):
        raise ValueError(f"{source} must contain a JSON object at the top level")
    for key in ("star_scroll_cost", "equipment"):
        if key not in payload:
            raise ValueError(f"{source} is missing the {key!r} section")

    scroll_costs = _parse_scroll_costs(payload["star_scroll_cost"])
    catalog, index = _parse_equipment(payload["equipment"])

    STAR_SCROLL_COST = scroll_costs
    CATALOG = catalog
    _INDEX = index
    SOURCE_PATH = source


def known_names() -> list[str]:
    """Canonical equipment names, in catalogue order."""
    return list(CATALOG)


def lookup(name: str) -> Equipment:
    """Resolve ``name`` - canonical, alias, or a digit variant - to an Equipment."""
    item = _INDEX.get(normalize(name))
    if item is None:
        raise ValueError(
            f"unknown equipment {name!r}; known names are {known_names()}"
        )
    return item


load()
