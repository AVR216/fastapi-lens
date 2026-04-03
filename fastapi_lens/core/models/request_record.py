import time
from dataclasses import dataclass, field
from typing import Optional
 
 
@dataclass(slots=True)
class RequestRecord:
    """Single captured request. Uses __slots__ for memory efficiency."""
    path: str
    method: str
    status_code: int
    duration_ms: float
    timestamp: float = field(default_factory=time.time)
    client_ip: Optional[str] = None