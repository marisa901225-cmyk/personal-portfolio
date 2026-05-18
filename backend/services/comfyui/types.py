from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSpec:
    prompt: str
    negative_prompt: str
    width: int
    height: int
    steps: int
    cfg: float
    seed: int


@dataclass(frozen=True)
class GpuMemory:
    used_mb: float
    utilization_percent: float

    @property
    def estimated_total_mb(self) -> float | None:
        if self.utilization_percent <= 0:
            return None
        return self.used_mb * 100.0 / self.utilization_percent

    @property
    def estimated_free_mb(self) -> float | None:
        total = self.estimated_total_mb
        if total is None:
            return None
        return max(total - self.used_mb, 0.0)
