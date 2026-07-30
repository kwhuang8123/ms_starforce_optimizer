"""Monte Carlo aggregation over repeated runs.

``to_dict`` output is plain JSON-serialisable data, ready to be dumped for the
static HTML front end. Every meso quantity appears twice: the raw amount, and
the same figure in 億 under a ``_yi`` key, which is the unit meant for display.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Sequence

from .engine import RunConfig, simulate_once
from .units import format_meso, to_yi

DEFAULT_PERCENTILES: tuple[int, ...] = (50, 75, 90, 95, 99)


@dataclass(frozen=True)
class Distribution:
    """Summary of one sampled quantity across every trial."""

    mean: float
    minimum: float
    maximum: float
    #: Percentile label -> value, e.g. ``{50: 1.2e9, 90: 7.4e9}``.
    percentiles: dict[int, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mean": self.mean,
            "min": self.minimum,
            "max": self.maximum,
            "percentiles": {str(p): v for p, v in self.percentiles.items()},
        }

    def to_yi_dict(self) -> dict[str, Any]:
        """Same figures converted to 億, for display."""
        return {
            "mean": to_yi(self.mean),
            "min": to_yi(self.minimum),
            "max": to_yi(self.maximum),
            "percentiles": {str(p): to_yi(v) for p, v in self.percentiles.items()},
        }


@dataclass(frozen=True)
class SimulationSummary:
    """Aggregated result of ``trials`` independent runs of one config."""

    config: RunConfig
    trials: int
    seed: int | None
    #: Meso spent, plus the equipment burned, plus any rebuilds.
    total_cost: Distribution
    #: Enhancement fees, repair meso and star scrolls.
    meso: Distribution
    #: Repair equipment valued at the config's equipment price.
    equipment_cost: Distribution
    #: Climbing an OWNED run back to 22 stars after a 12 star repair.
    rebuild_cost: Distribution
    #: Repair equipment as a piece count.
    equipment: Distribution
    scrolls: Distribution
    #: Breakthrough scrolls consumed, all kinds together.
    breakthroughs: Distribution
    attempts: Distribution
    destroys: Distribution
    #: Mean number of attempts made from each star, keyed by star.
    mean_attempts_by_star: dict[int, float]
    #: Mean number of each breakthrough scroll bought, keyed by scroll id. Each
    #: has its own price, so re-pricing needs them apart rather than totalled.
    mean_breakthroughs_by_scroll: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "config": self.config.to_dict(),
            "trials": self.trials,
            "seed": self.seed,
        }
        for label in ("total_cost", "meso", "equipment_cost", "rebuild_cost"):
            distribution: Distribution = getattr(self, label)
            payload[label] = distribution.to_dict()
            payload[f"{label}_yi"] = distribution.to_yi_dict()
        for label in ("equipment", "scrolls", "breakthroughs", "attempts", "destroys"):
            payload[label] = getattr(self, label).to_dict()
        payload["mean_attempts_by_star"] = {
            str(star): value
            for star, value in sorted(self.mean_attempts_by_star.items())
        }
        payload["mean_breakthroughs_by_scroll"] = dict(
            sorted(self.mean_breakthroughs_by_scroll.items())
        )
        return payload

    def report(self, percentiles: Sequence[int] = DEFAULT_PERCENTILES) -> str:
        """Human-readable summary with every meso figure in 億."""
        config = self.config
        headline = (
            f"level {config.level}  {config.start_star} -> {config.target_star} stars  "
            f"start={config.start_mode.value}  repair={config.repair_policy.value}"
        )
        if config.equipment_name is not None:
            headline += (
                f"  equipment={config.equipment_name} @ "
                f"{format_meso(config.equipment_price)}"
            )
        headline += f"  trials={self.trials:,}"

        lines = [headline]
        for label, distribution in (
            ("total", self.total_cost),
            ("meso", self.meso),
            ("equip cost", self.equipment_cost),
            ("rebuild", self.rebuild_cost),
        ):
            lines.append(
                f"  {label:<11} mean {format_meso(distribution.mean):>14}"
                + "".join(
                    f"  p{p} {format_meso(distribution.percentiles[p]):>14}"
                    for p in percentiles
                )
            )
        for label, distribution in (
            ("equip qty", self.equipment),
            ("scrolls", self.scrolls),
            ("breakthrough", self.breakthroughs),
            ("attempts", self.attempts),
            ("destroys", self.destroys),
        ):
            lines.append(
                f"  {label:<11} mean {distribution.mean:>14,.2f}"
                + "".join(
                    f"  p{p} {distribution.percentiles[p]:>14,.0f}"
                    for p in percentiles
                )
            )
        return "\n".join(lines)


def _percentile(sorted_values: Sequence[float], percentile: int) -> float:
    """Linear-interpolation percentile over an already sorted sequence."""
    if not sorted_values:
        raise ValueError("cannot take a percentile of an empty sample")
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * percentile / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _summarise(values: list[int], percentiles: Sequence[int]) -> Distribution:
    ordered = sorted(values)
    return Distribution(
        mean=sum(ordered) / len(ordered),
        minimum=float(ordered[0]),
        maximum=float(ordered[-1]),
        percentiles={p: _percentile(ordered, p) for p in percentiles},
    )


def simulate(
    config: RunConfig,
    trials: int = 10_000,
    seed: int | None = None,
    percentiles: Sequence[int] = DEFAULT_PERCENTILES,
) -> SimulationSummary:
    """Run ``config`` ``trials`` times and summarise the outcome."""
    if trials < 1:
        raise ValueError(f"trials must be at least 1, got {trials}")
    for percentile in percentiles:
        if not 0 <= percentile <= 100:
            raise ValueError(f"percentile must be within 0-100, got {percentile}")

    rng = random.Random(seed)
    samples: dict[str, list[int]] = {
        "total_cost": [],
        "meso": [],
        "equipment_cost": [],
        "rebuild_cost": [],
        "equipment": [],
        "scrolls": [],
        "breakthroughs": [],
        "attempts": [],
        "destroys": [],
    }
    attempts_by_star: dict[int, int] = {}
    breakthroughs_by_scroll: dict[str, int] = {}

    for _ in range(trials):
        result = simulate_once(config, rng)
        samples["total_cost"].append(result.total_cost)
        samples["meso"].append(result.total_meso)
        samples["equipment_cost"].append(result.equipment_cost)
        samples["rebuild_cost"].append(result.rebuild_cost)
        samples["equipment"].append(result.equipment_used)
        samples["scrolls"].append(result.scrolls_used)
        samples["breakthroughs"].append(result.breakthroughs_used)
        samples["attempts"].append(result.attempts)
        samples["destroys"].append(result.destroys)
        for star, count in result.attempts_by_star.items():
            attempts_by_star[star] = attempts_by_star.get(star, 0) + count
        for key, count in result.breakthroughs_by_scroll.items():
            breakthroughs_by_scroll[key] = breakthroughs_by_scroll.get(key, 0) + count

    return SimulationSummary(
        config=config,
        trials=trials,
        seed=seed,
        total_cost=_summarise(samples["total_cost"], percentiles),
        meso=_summarise(samples["meso"], percentiles),
        equipment_cost=_summarise(samples["equipment_cost"], percentiles),
        rebuild_cost=_summarise(samples["rebuild_cost"], percentiles),
        equipment=_summarise(samples["equipment"], percentiles),
        scrolls=_summarise(samples["scrolls"], percentiles),
        breakthroughs=_summarise(samples["breakthroughs"], percentiles),
        attempts=_summarise(samples["attempts"], percentiles),
        destroys=_summarise(samples["destroys"], percentiles),
        mean_attempts_by_star={
            star: count / trials for star, count in attempts_by_star.items()
        },
        mean_breakthroughs_by_scroll={
            key: count / trials for key, count in breakthroughs_by_scroll.items()
        },
    )
