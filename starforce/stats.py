"""Monte Carlo aggregation over repeated runs.

``to_dict`` output is plain JSON-serialisable data, ready to be dumped for the
static HTML front end. Meso appears twice: ``meso`` holds raw amounts and
``meso_yi`` holds the same figures in 億, which is the unit meant for display.
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
    meso: Distribution
    equipment: Distribution
    scrolls: Distribution
    attempts: Distribution
    destroys: Distribution
    #: Mean number of attempts made from each star, keyed by star.
    mean_attempts_by_star: dict[int, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "trials": self.trials,
            "seed": self.seed,
            "meso": self.meso.to_dict(),
            "meso_yi": self.meso.to_yi_dict(),
            "equipment": self.equipment.to_dict(),
            "scrolls": self.scrolls.to_dict(),
            "attempts": self.attempts.to_dict(),
            "destroys": self.destroys.to_dict(),
            "mean_attempts_by_star": {
                str(star): value
                for star, value in sorted(self.mean_attempts_by_star.items())
            },
        }

    def report(self, percentiles: Sequence[int] = DEFAULT_PERCENTILES) -> str:
        """Human-readable summary with every meso figure in 億."""
        config = self.config
        lines = [
            f"level {config.level}  {config.start_star} -> {config.target_star} stars  "
            f"repair={config.repair_policy.value}  trials={self.trials:,}",
            f"  meso       mean {format_meso(self.meso.mean):>14}"
            + "".join(
                f"  p{p} {format_meso(self.meso.percentiles[p]):>14}"
                for p in percentiles
            ),
        ]
        for label, dist in (
            ("equipment", self.equipment),
            ("scrolls", self.scrolls),
            ("attempts", self.attempts),
            ("destroys", self.destroys),
        ):
            lines.append(
                f"  {label:<9}  mean {dist.mean:>14,.2f}"
                + "".join(
                    f"  p{p} {dist.percentiles[p]:>14,.0f}" for p in percentiles
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
    meso: list[int] = []
    equipment: list[int] = []
    scrolls: list[int] = []
    attempts: list[int] = []
    destroys: list[int] = []
    attempts_by_star: dict[int, int] = {}

    for _ in range(trials):
        result = simulate_once(config, rng)
        meso.append(result.total_meso)
        equipment.append(result.equipment_used)
        scrolls.append(result.scrolls_used)
        attempts.append(result.attempts)
        destroys.append(result.destroys)
        for star, count in result.attempts_by_star.items():
            attempts_by_star[star] = attempts_by_star.get(star, 0) + count

    return SimulationSummary(
        config=config,
        trials=trials,
        seed=seed,
        meso=_summarise(meso, percentiles),
        equipment=_summarise(equipment, percentiles),
        scrolls=_summarise(scrolls, percentiles),
        attempts=_summarise(attempts, percentiles),
        destroys=_summarise(destroys, percentiles),
        mean_attempts_by_star={
            star: count / trials for star, count in attempts_by_star.items()
        },
    )
