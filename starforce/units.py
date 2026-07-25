"""Meso display units.

Meso figures in the star force range run to tens of billions, so everything
shown to a reader is expressed in 億 (10^8).
"""

from __future__ import annotations

#: One 億.
YI = 100_000_000


def to_yi(meso: float) -> float:
    """Convert a raw meso amount to 億."""
    return meso / YI


def format_meso(meso: float, decimals: int = 2) -> str:
    """Render a raw meso amount as a 億 string, e.g. ``"191.80億"``."""
    return f"{to_yi(meso):,.{decimals}f}億"
