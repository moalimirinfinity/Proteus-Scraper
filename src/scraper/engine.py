from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EngineOutcome:
    success: bool
    error: str | None = None
