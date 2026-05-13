"""Internal Pydantic schemas for the backtesting/outcome computation pipeline.

These are computation-layer types — distinct from the API-layer schemas in db/schemas.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ForwardOutcome:
    """Result of compute_forward_outcome() — pure computation, no DB."""

    # Prices
    start_price: float | None = None
    end_price: float | None = None
    benchmark_start_price: float | None = None
    benchmark_end_price: float | None = None

    # Returns
    forward_return_pct: float | None = None
    benchmark_return_pct: float | None = None
    relative_return_pct: float | None = None

    # Path statistics
    max_drawdown_pct: float | None = None
    max_runup_pct: float | None = None

    # Classification
    outcome_status: str = "PENDING"   # PENDING | MEASURED | INSUFFICIENT_DATA | ERROR
    outcome_label: str | None = None  # WIN | LOSS | NEUTRAL | AVOIDED_LOSS | MISSED_UPSIDE

    # Debug / raw metadata
    raw_json: dict[str, Any] = field(default_factory=dict)
