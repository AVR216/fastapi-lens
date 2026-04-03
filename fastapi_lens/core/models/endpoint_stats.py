import time
from dataclasses import dataclass
from typing import Optional

@dataclass(slots=True)
class EndpointStats:
    """Aggregated stats for a single endpoint."""
    path: str
    method: str
    total_calls: int
    error_4xx_count: int
    error_5xx_count: int
    avg_duration_ms: float
    p50_duration_ms: float
    p95_duration_ms: float
    p99_duration_ms: float
    max_duration_ms: float
    last_called_at: Optional[float]
    first_called_at: Optional[float]
 
    @property
    def error_count(self) -> int:
        return self.error_4xx_count + self.error_5xx_count

    @property
    def error_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return round(self.error_count / self.total_calls * 100, 2)

    @property
    def success_rate_pct(self) -> float:
        if self.total_calls == 0:
            return 100.0
        return round((self.total_calls - self.error_count) / self.total_calls * 100, 2)
 
    @property
    def days_since_last_call(self) -> Optional[float]:
        if self.last_called_at is None:
            return None
        return round((time.time() - self.last_called_at) / 86400, 1)
 
    @property
    def status(self) -> str:
        """Classify endpoint health."""
        if self.last_called_at is None:
            return "never_called"
        days = self.days_since_last_call
        if days is None:
            return "unknown"
        if days > 30:
            return "dead"
        if days > 7:
            return "cold"
        return "active"