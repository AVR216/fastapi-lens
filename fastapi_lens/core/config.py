"""
Configuration for LensMiddleware.
All options in one place to make contributions easy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Set


@dataclass
class LensConfig:
    """
    Configuration for LensMiddleware.

    Args:
        db_path: SQLite file path. Use ":memory:" for tests.
        report_key: Secret key to protect /lens/report. None = no auth (dev only).
        report_path: Path where the report endpoint is mounted.
        exclude_paths: Paths to never record (e.g. health checks, static files).
        exclude_methods: HTTP methods to skip (default: HEAD, OPTIONS).
        flush_interval: Seconds between batch writes to SQLite. Lower = more writes.
        max_batch_size: Max records held in memory before forcing a flush.
        dead_threshold_days: Days without calls to mark endpoint as "dead".
        cold_threshold_days: Days without calls to mark endpoint as "cold".
    """
    db_path: str = "lens.db"
    report_path: str = "/lens/report"
    # Security options
    security_enabled: bool = False
    report_key: Optional[str] = None
    # New options for noise reduction
    ignore_unmapped: bool = True
    exclude_paths: Set[str] = field(default_factory=lambda: {
        "/lens/report", "/lens/dashboard", "/docs", "/redoc", "/openapi.json",
        "/favicon.ico", "/robots.txt", "/sitemap.xml", "/apple-touch-icon.png"
    })
    exclude_methods: Set[str] = field(default_factory=lambda: {"HEAD", "OPTIONS"})
    flush_interval: float = 5.0
    max_batch_size: int = 100
    dead_threshold_days: int = 30
    cold_threshold_days: int = 7
    ttl_days: Optional[int] = None