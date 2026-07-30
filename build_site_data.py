"""Generate the JSON the GitHub Pages front end reads into ``docs/data``.

The front end runs in a browser, so it cannot import :mod:`starforce`. It gets a
JavaScript port of the rules instead - and a port is only safe if the *numbers*
are never copied by hand. Everything under ``docs/data`` is produced here from
the Python single source of truth:

``static.json``
    The official tables and caps, straight out of :mod:`starforce.static_data`
    and the constants in :mod:`starforce.rules`.
``prices.json``
    The validated contents of ``data/volatile.json``, as the page's defaults.
``simulations.json`` / ``marginal.json``
    The sweep datasets, flattened to one row per combination and rounded, which
    is what the browsing page needs and a fraction of the size.
``parity.json``
    Golden cases: a fixed roll sequence, the actions taken, and what the Python
    engine produced. ``docs/selftest.html`` replays each one through the
    JavaScript port and compares. Scripted rolls make the two runs comparable
    even though the two languages have different random number generators.

Run this after ``sweep.py`` or after editing ``data/volatile.json``.
``tests/test_site_data.py`` rebuilds ``static.json``, ``prices.json`` and
``parity.json`` and compares them against what is committed, so forgetting to
re-run this file fails the test suite.
"""

from __future__ import annotations

import json
import random
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from starforce import load_rebuild_basis, rules, simulate, volatile_data
from starforce import static_data as data
from starforce.autorun import AutoPolicy, run_within_budget
from starforce.engine import RepairPolicy, RunConfig, StartMode
from starforce.session import Session
from starforce.units import YI

ROOT = Path(__file__).resolve().parent
SIM_DATA_DIR = ROOT / "starforce" / "sim_data"
OUTPUT_DIR = ROOT / "docs" / "data"

#: Budget that no parity case can reach, so those runs stop on their target.
UNCAPPED = 1_000_000 * YI

#: Fixed so the re-pricing cases are reproducible.
REPRICE_SEED = 20260729


class _ScriptedRandom(random.Random):
    """Feeds ``randrange`` a fixed sequence and remembers how much was used."""

    def __init__(self, rolls: Sequence[int]) -> None:
        super().__init__()
        self._rolls = list(rolls)
        self.used = 0

    def randrange(self, *args: Any, **kwargs: Any) -> int:  # noqa: D102
        if self.used >= len(self._rolls):
            raise RuntimeError(
                "a parity case ran out of rolls; raise the roll count in "
                "build_parity so the run finishes"
            )
        value = self._rolls[self.used]
        self.used += 1
        return value


def build_static() -> dict[str, Any]:
    """The fixed tables and caps, keyed by string so JSON round-trips cleanly."""
    return {
        "rate_basis": data.RATE_BASIS,
        "supported_levels": list(data.SUPPORTED_LEVELS),
        "star_scroll_stars": list(data.STAR_SCROLL_STARS),
        "min_start_star": rules.MIN_START_STAR,
        "max_start_star": rules.MAX_START_STAR,
        "destroy_start_star": rules.DESTROY_START_STAR,
        "trace_star_cap": rules.TRACE_STAR_CAP,
        "cheap_repair_star": rules.CHEAP_REPAIR_STAR,
        "cheap_repair_equipment": rules.CHEAP_REPAIR_EQUIPMENT,
        "rebuild_star": rules.REBUILD_STAR,
        "enhance_rates": {
            str(star): list(rates) for star, rates in sorted(data.ENHANCE_RATES.items())
        },
        "enhance_cost": {
            str(level): {str(star): cost for star, cost in sorted(costs.items())}
            for level, costs in sorted(data.ENHANCE_COST.items())
        },
        "repair_meso": {
            str(level): {str(star): meso for star, meso in sorted(table.items())}
            for level, table in sorted(data.REPAIR_MESO.items())
        },
        "repair_equipment": {
            str(star): pieces for star, pieces in sorted(data.REPAIR_EQUIPMENT.items())
        },
        # Precomputed rather than ported: one fewer rule for the port to get
        # wrong, and the level 130 exception stays in one place.
        "max_star": {
            str(level): rules.max_star(level) for level in data.SUPPORTED_LEVELS
        },
        "max_target_star": {
            str(level): rules.max_target_star(level) for level in data.SUPPORTED_LEVELS
        },
    }


def build_prices() -> dict[str, Any]:
    """The catalogue as ``volatile_data`` validated it, not as raw file text."""
    return {
        "star_scroll_cost": {
            str(star): volatile_data.STAR_SCROLL_COST[star]
            for star in data.STAR_SCROLL_STARS
        },
        "equipment": [
            {
                "name": item.name,
                "level": item.level,
                "price": item.price,
                "aliases": list(item.aliases),
            }
            for item in volatile_data.CATALOG.values()
        ],
    }


def slim_result(entry: dict[str, Any], scroll_costs: dict[str, int]) -> dict[str, Any]:
    """One combination, flattened and split into its price-dependent parts.

    A run's trajectory does not depend on any price - the engine only ever adds
    them up - so the mean total cost is exactly linear in them:

        total = static_meso_mean
              + scrolls_mean       x star scroll price
              + equipment_mean     x equipment price
              + rebuild_count_mean x rebuild cost

    Splitting the figures out here is what lets the page re-price a dataset for
    edited prices without simulating anything. ``scroll_costs`` must be the
    snapshot the dataset was generated against, not today's prices.
    """
    config = entry["config"]
    scrolled = config["start_mode"] == "scroll"
    scroll_star = config["start_star"] if scrolled else None
    scroll_price = scroll_costs[str(scroll_star)] if scrolled else 0

    # Meso figures round to whole meso; the counts they get multiplied by do
    # not round at all. The page multiplies these by prices that can reach 1e11,
    # so trimming even eight decimals here would show up as hundreds of meso of
    # disagreement against a directly measured mean.
    meso_mean = round(entry["meso"]["mean"])
    scrolls_mean = entry["scrolls"]["mean"]
    equipment_mean = entry["equipment"]["mean"]
    rebuild_cost = config["rebuild_cost"]
    rebuild_count_mean = (
        entry["rebuild_cost"]["mean"] / rebuild_cost if rebuild_cost else 0.0
    )

    return {
        "equipment": config["equipment_name"],
        "level": config["level"],
        "equipment_price": config["equipment_price"],
        "start_star": config["start_star"],
        "target_star": config["target_star"],
        "start_mode": config["start_mode"],
        "repair_policy": config["repair_policy"],
        # Which star scroll this run buys, or null when it buys none. The page
        # needs the star to look the price up, and start_star is not it for a
        # run that starts from an item it already owns.
        "scroll_star": scroll_star,
        "rebuild_cost": rebuild_cost,
        "trials": entry["trials"],
        "total_cost_mean": round(entry["total_cost"]["mean"]),
        "total_cost_percentiles": {
            label: round(value)
            for label, value in entry["total_cost"]["percentiles"].items()
        },
        "meso_mean": meso_mean,
        # Enhancement fees and repair meso: fixed by the level, not the market.
        "static_meso_mean": round(meso_mean - scrolls_mean * scroll_price, 6),
        "equipment_cost_mean": round(entry["equipment_cost"]["mean"]),
        "rebuild_cost_mean": round(entry["rebuild_cost"]["mean"]),
        "rebuild_count_mean": rebuild_count_mean,
        "equipment_mean": equipment_mean,
        "scrolls_mean": scrolls_mean,
        "attempts_mean": round(entry["attempts"]["mean"], 2),
        "destroys_mean": round(entry["destroys"]["mean"], 3),
        "attempts_by_star": {
            star: round(value, 3)
            for star, value in entry["mean_attempts_by_star"].items()
        },
    }


def slim_dataset(payload: dict[str, Any]) -> dict[str, Any]:
    """Flatten a sweep dataset to one row per combination, rounded for size."""
    meta = dict(payload["meta"])
    # The published copy advertises the targets it actually carries. A sweep that
    # was configured for more than it finished - or, as with 24 stars from
    # scratch, was configured for something since dropped - would otherwise have
    # the site reporting a gap that nobody intends to fill.
    completed = meta.get("targets_completed")
    if completed:
        meta["target_stars"] = list(completed)

    scroll_costs = meta["prices"]["star_scroll_cost"]
    return {
        "meta": meta,
        "results": [slim_result(entry, scroll_costs) for entry in payload["results"]],
    }


def load_dataset(path: Path) -> dict[str, Any] | None:
    """Read a sweep dataset, or None when it has not been generated yet."""
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _session_state(session: Session) -> dict[str, Any]:
    """The half of a session's state a parity case compares."""
    totals = session.totals
    return {
        "star": session.star,
        "destroyed": session.destroyed,
        "totals": {
            "total_meso": totals.total_meso,
            "equipment_used": totals.equipment_used,
            "equipment_cost": totals.equipment_cost,
            "scrolls_used": totals.scrolls_used,
            "attempts": totals.attempts,
            "destroys": totals.destroys,
            "total_cost": totals.total_cost,
            "attempts_by_star": {
                str(star): count
                for star, count in sorted(totals.attempts_by_star.items())
            },
        },
        # The core fields only: the ``_yi`` keys LogEntry.to_dict adds are
        # derived floats, and the port is judged on the figures they come from.
        "log": [
            {
                "index": entry.index,
                "action": entry.action,
                "star_before": entry.star_before,
                "star_after": entry.star_after,
                "outcome": entry.outcome,
                "meso": entry.meso,
                "equipment_used": entry.equipment_used,
                "equipment_cost": entry.equipment_cost,
                "total_cost_after": entry.total_cost_after,
            }
            for entry in session.log
        ],
    }


def _auto_case(
    name: str,
    level: int,
    start_star: int,
    equipment_price: int,
    target_star: int,
    policy: AutoPolicy,
    rolls: Sequence[int],
    budget: int = UNCAPPED,
) -> dict[str, Any]:
    """One automatic run, recorded down to the last log entry."""
    session = Session(
        level=level, start_star=start_star, equipment_price=equipment_price
    )
    rng = _ScriptedRandom(rolls)
    session.rng = rng
    result = run_within_budget(session, target_star, budget, policy)

    expected = _session_state(session)
    expected["stop_reason"] = result.stop_reason.value
    expected["spent"] = result.spent
    return {
        "name": name,
        "kind": "auto",
        "session": {
            "level": level,
            "start_star": start_star,
            "equipment_price": equipment_price,
        },
        "policy": {
            "repair_policy": policy.repair_policy.value,
            "scroll_star": policy.scroll_star,
        },
        "target_star": target_star,
        "budget": budget,
        # Only the rolls the run actually consumed: replaying it must consume
        # exactly as many, and running out is itself a failure.
        "rolls": list(rolls[: rng.used]),
        "expected": expected,
    }


def _manual_case(
    name: str,
    level: int,
    start_star: int,
    equipment_price: int,
    actions: Sequence[Sequence[Any]],
    rolls: Sequence[int],
) -> dict[str, Any]:
    """A hand-written action script, for the parts no automatic run reaches."""
    session = Session(
        level=level, start_star=start_star, equipment_price=equipment_price
    )
    rng = _ScriptedRandom(rolls)
    session.rng = rng

    for action in actions:
        verb = action[0]
        if verb == "enhance":
            session.enhance()
        elif verb == "scroll":
            session.use_scroll(action[1])
        elif verb == "repair":
            session.repair(RepairPolicy(action[1]))
        else:
            raise ValueError(f"unknown parity action {verb!r}")

    return {
        "name": name,
        "kind": "manual",
        "session": {
            "level": level,
            "start_star": start_star,
            "equipment_price": equipment_price,
        },
        "actions": [list(action) for action in actions],
        "rolls": list(rolls[: rng.used]),
        "expected": _session_state(session),
    }


def _seeded_rolls(seed: int, count: int = 4_000) -> list[int]:
    """A deterministic roll supply for a case that runs until it is done."""
    rng = random.Random(seed)
    return [rng.randrange(data.RATE_BASIS) for _ in range(count)]


def build_parity() -> dict[str, Any]:
    """Golden cases the JavaScript port must reproduce exactly.

    Scroll prices ride along so ``selftest.html`` stays self-contained: a case
    involving a scroll is only reproducible against the prices it was built on.
    """
    cases = [
        _auto_case(
            "scrolled climb, full repair",
            level=150,
            start_star=0,
            equipment_price=150_000_000,
            target_star=19,
            policy=AutoPolicy(RepairPolicy.FULL, scroll_star=15),
            rolls=_seeded_rolls(20260728),
        ),
        _auto_case(
            "scrolled climb, cheap repair and re-scroll",
            level=150,
            start_star=0,
            equipment_price=150_000_000,
            target_star=19,
            policy=AutoPolicy(RepairPolicy.TO_12, scroll_star=15),
            rolls=_seeded_rolls(20260728),
        ),
        _auto_case(
            "owned item pushed past 22 stars",
            level=200,
            start_star=22,
            equipment_price=20_000_000_000,
            target_star=24,
            policy=AutoPolicy(RepairPolicy.FULL),
            rolls=_seeded_rolls(19),
        ),
        _auto_case(
            "budget runs out mid climb",
            level=250,
            start_star=15,
            equipment_price=300_000_000,
            target_star=20,
            policy=AutoPolicy(RepairPolicy.FULL),
            rolls=_seeded_rolls(7),
            budget=200 * YI,
        ),
        _manual_case(
            "destroy at 15 stars, then a full repair",
            level=140,
            start_star=0,
            equipment_price=1_000_000_000,
            actions=[["scroll", 15], ["enhance"], ["repair", "full"], ["enhance"]],
            # 3100 falls in the 15 star destroy band, 0 always succeeds.
            rolls=[3100, 0],
        ),
        _manual_case(
            "destroy above 22 stars leaves a 22 star trace",
            level=160,
            start_star=25,
            equipment_price=2_000_000_000,
            actions=[["enhance"], ["repair", "to_12"], ["scroll", 20], ["enhance"]],
            # 1000 falls in the 25 star destroy band, 9999 maintains at 20.
            rolls=[1000, 9999],
        ),
    ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rate_basis": data.RATE_BASIS,
        "star_scroll_cost": {
            str(star): volatile_data.STAR_SCROLL_COST[star]
            for star in data.STAR_SCROLL_STARS
        },
        "cases": cases,
        "reprice": build_reprice_cases(),
    }


# ---------------------------------------------------------------------------
# Re-pricing golden cases
# ---------------------------------------------------------------------------

#: Trials per re-pricing case. These only need the two runs to agree, not a
#: converged distribution, so a small number keeps the build quick.
REPRICE_TRIALS = 3_000

#: Prices the "after" half of each case is measured against. Deliberately far
#: from the shipped ones so a term that was quietly dropped cannot still match.
REPRICE_SCROLL_MULTIPLIER = 3
REPRICE_EQUIPMENT_MULTIPLIER = 5


def _price_payload(scroll_multiplier: int, equipment_multiplier: int) -> dict[str, Any]:
    """The shipped catalogue with every price scaled."""
    return {
        "star_scroll_cost": {
            str(star): volatile_data.STAR_SCROLL_COST[star] * scroll_multiplier
            for star in data.STAR_SCROLL_STARS
        },
        "equipment": [
            {
                "name": item.name,
                "level": item.level,
                "price": item.price * equipment_multiplier,
                "aliases": list(item.aliases),
            }
            for item in volatile_data.CATALOG.values()
        ],
    }


def _measure(config: RunConfig, scroll_costs: dict[str, int]) -> dict[str, Any]:
    """Run one config and flatten it the way the site's datasets are flattened."""
    summary = simulate(config, trials=REPRICE_TRIALS, seed=REPRICE_SEED)
    return slim_result(summary.to_dict(), scroll_costs)


def build_reprice_cases() -> list[dict[str, Any]]:
    """Cases proving the page can re-price a row without re-simulating.

    Each case measures the same configuration twice - once at the shipped
    prices, once at scaled ones - with the same seed. Because no price can
    change a trajectory, the second run's mean is what re-pricing the first
    run's row must produce, to the meso. Generating the expectation by actually
    simulating rather than by applying the same formula twice is what makes this
    a check instead of a tautology.
    """
    shipped_scrolls = {
        str(star): volatile_data.STAR_SCROLL_COST[star]
        for star in data.STAR_SCROLL_STARS
    }
    after_prices = _price_payload(
        REPRICE_SCROLL_MULTIPLIER, REPRICE_EQUIPMENT_MULTIPLIER
    )

    # A marginal run that repairs to 12 stars is priced against a rebuild cost
    # that moves with the market too, so its case carries a different figure on
    # each side - that is the only way the rebuild term gets exercised.
    rebuild_before = load_rebuild_basis().cost("頂培")
    rebuild_after = rebuild_before * 3

    plans = [
        ("scrolled climb, full repair", "頂培", 15, 22, RepairPolicy.FULL, StartMode.SCROLL, 0, 0),
        ("scrolled climb, cheap repair", "頂培", 15, 22, RepairPolicy.TO_12, StartMode.SCROLL, 0, 0),
        ("dearer scroll, dearer equipment", "控制核心", 19, 23, RepairPolicy.TO_12, StartMode.SCROLL, 0, 0),
        ("owned item, no scroll at all", "眼罩", 22, 23, RepairPolicy.FULL, StartMode.OWNED, 0, 0),
        (
            "owned item rebuilding to 22 stars", "頂培", 22, 24,
            RepairPolicy.TO_12, StartMode.OWNED, rebuild_before, rebuild_after,
        ),
    ]

    before_rows = []
    for _, name, start, target, policy, mode, rebuild, _after in plans:
        config = RunConfig.for_equipment(
            name, start, target,
            repair_policy=policy, start_mode=mode, rebuild_cost=rebuild,
        )
        before_rows.append(_measure(config, shipped_scrolls))

    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    )
    try:
        json.dump(after_prices, handle, ensure_ascii=False)
        handle.close()
        volatile_data.load(handle.name)

        cases = []
        for (label, name, start, target, policy, mode, _before, rebuild), row in zip(
            plans, before_rows
        ):
            config = RunConfig.for_equipment(
                name, start, target,
                repair_policy=policy, start_mode=mode, rebuild_cost=rebuild,
            )
            after = simulate(config, trials=REPRICE_TRIALS, seed=REPRICE_SEED)
            cases.append(
                {
                    "name": label,
                    "row": row,
                    "prices": after_prices,
                    "rebuild_cost": rebuild,
                    "expected_total_cost_mean": round(after.total_cost.mean),
                }
            )
    finally:
        volatile_data.load()
        Path(handle.name).unlink(missing_ok=True)

    if volatile_data.SOURCE_PATH != volatile_data.DEFAULT_PATH:
        raise RuntimeError("failed to restore the shipped prices after re-pricing cases")
    return cases


def write_json(payload: dict[str, Any], path: Path) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"  wrote {path.name} ({path.stat().st_size:,} bytes)")


def main(output_dir: Path = OUTPUT_DIR, sim_data_dir: Path = SIM_DATA_DIR) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"writing site data to {output_dir}")

    write_json(build_static(), output_dir / "static.json")
    write_json(build_prices(), output_dir / "prices.json")
    write_json(build_parity(), output_dir / "parity.json")

    for name in ("simulations.json", "marginal.json"):
        payload = load_dataset(sim_data_dir / name)
        if payload is None:
            print(f"  skipped {name}: not found in {sim_data_dir}")
            continue
        meta = payload["meta"]
        print(
            f"  {name}: generated_at={meta.get('generated_at')} "
            f"targets_completed={meta.get('targets_completed')} "
            f"results={len(payload['results'])}"
        )
        write_json(slim_dataset(payload), output_dir / name)


if __name__ == "__main__":
    main()
