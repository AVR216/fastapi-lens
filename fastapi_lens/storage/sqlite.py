"""
SQLite storage backend for fastapi-lens.

Design decisions:
- WAL mode for concurrent reads + writes without locking
- Single connection per thread via threading.local
- Batch inserts to minimize I/O
- Minimal schema — only what we actually need
"""
from __future__ import annotations

import sqlite3
import threading
import time
from typing import List, Optional

from fastapi_lens.core.models import EndpointStats, RequestRecord


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS lens_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT    NOT NULL,
    method      TEXT    NOT NULL,
    status_code INTEGER NOT NULL,
    duration_ms REAL    NOT NULL,
    timestamp   REAL    NOT NULL,
    client_ip   TEXT
);
CREATE INDEX IF NOT EXISTS idx_lens_path_method ON lens_requests (path, method);
CREATE INDEX IF NOT EXISTS idx_lens_timestamp   ON lens_requests (timestamp);
"""


class SQLiteStorage:
    """
    Thread-safe SQLite storage.
    - File-based DBs: one connection per thread via threading.local (WAL allows concurrent access)
    - :memory: DBs: single shared connection (in-memory DBs are per-connection in SQLite,
      so sharing is the only way to have one consistent DB across threads)
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._is_memory = db_path == ":memory:"

        if self._is_memory:
            # Single shared connection for in-memory DBs.
            # check_same_thread=False is safe here because SQLite serializes writes.
            self._shared_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._shared_conn.execute("PRAGMA cache_size=-4096")
            self._shared_conn.row_factory = sqlite3.Row
            self._shared_conn.executescript(_CREATE_TABLE)
            self._shared_conn.commit()
            self._local = None
        else:
            self._shared_conn = None
            self._local = threading.local()
            # Eagerly create schema on the calling thread.
            # _conn() will also create schema on any future new-thread connection.
            self._conn()

    def _conn(self) -> sqlite3.Connection:
        """
        Return the appropriate connection for the current context.

        - :memory:  → always the single shared connection
        - file DB   → per-thread connection (created with schema if new)
        """
        if self._is_memory:
            return self._shared_conn  # type: ignore[return-value]

        if not getattr(self._local, "conn", None):
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")   # concurrent reads
            conn.execute("PRAGMA synchronous=NORMAL") # safe + fast
            conn.execute("PRAGMA cache_size=-4096")   # 4MB page cache
            conn.row_factory = sqlite3.Row
            conn.executescript(_CREATE_TABLE)         # init schema on every new connection
            conn.commit()
            assert self._local is not None
            self._local.conn = conn
        assert self._local is not None
        return self._local.conn

    def insert_batch(self, records: List[RequestRecord]) -> None:
        """Batch insert — called by the background flush task."""
        if not records:
            return
        conn = self._conn()
        conn.executemany(
            """
            INSERT INTO lens_requests
                (path, method, status_code, duration_ms, timestamp, client_ip)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (r.path, r.method, r.status_code, r.duration_ms, r.timestamp, r.client_ip)
                for r in records
            ],
        )
        conn.commit()

    def get_stats(
        self,
        since: Optional[float] = None,
        limit: int = 500,
    ) -> List[EndpointStats]:
        """
        Aggregate stats per (path, method).
        Uses a single query with window-friendly aggregations.
        """
        since = since or 0.0
        conn = self._conn()
        rows = conn.execute(
            """
            SELECT
                path,
                method,
                COUNT(*)                                        AS total_calls,
                SUM(CASE WHEN status_code >= 400 AND status_code < 500 THEN 1 ELSE 0 END) AS error_4xx_count,
                SUM(CASE WHEN status_code >= 500 THEN 1 ELSE 0 END) AS error_5xx_count,
                AVG(duration_ms)                               AS avg_duration_ms,
                MAX(duration_ms)                               AS max_duration_ms,
                MAX(timestamp)                                 AS last_called_at,
                MIN(timestamp)                                 AS first_called_at
            FROM lens_requests
            WHERE timestamp >= ?
            GROUP BY path, method
            ORDER BY total_calls DESC
            LIMIT ?
            """,
            (since, limit),
        ).fetchall()

        return [
            EndpointStats(
                path=row["path"],
                method=row["method"],
                total_calls=row["total_calls"],
                error_4xx_count=row["error_4xx_count"] or 0,
                error_5xx_count=row["error_5xx_count"] or 0,
                avg_duration_ms=round(row["avg_duration_ms"] or 0, 2),
                max_duration_ms=round(row["max_duration_ms"] or 0, 2),
                last_called_at=row["last_called_at"],
                first_called_at=row["first_called_at"],
                # Percentiles are filled by the API layer to avoid complex SQL
                p50_duration_ms=0.0,
                p95_duration_ms=0.0,
                p99_duration_ms=0.0,
            )
            for row in rows
        ]

    def get_percentiles(self, path: str, method: str, since: float = 0.0) -> dict[str, float]:
        """Compute actual p50, p95, p99 for a specific endpoint."""
        conn = self._conn()
        rows = conn.execute(
            """
            SELECT duration_ms FROM lens_requests
            WHERE path = ? AND method = ? AND timestamp >= ?
            ORDER BY duration_ms
            """,
            (path, method, since),
        ).fetchall()
        if not rows:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
        durations = [r[0] for r in rows]
        n = len(durations)
        return {
            "p50": round(durations[max(0, int(n * 0.50) - 1)], 2),
            "p95": round(durations[max(0, int(n * 0.95) - 1)], 2),
            "p99": round(durations[max(0, int(n * 0.99) - 1)], 2),
        }

    def total_requests(self, since: float = 0.0) -> int:
        conn = self._conn()
        row = conn.execute(
            "SELECT COUNT(*) FROM lens_requests WHERE timestamp >= ?", (since,)
        ).fetchone()
        return row[0] if row else 0

    def close(self) -> None:
        if self._is_memory:
            if self._shared_conn:
                self._shared_conn.close()
                self._shared_conn = None  # type: ignore[assignment]
        elif self._local and hasattr(self._local, "conn"):
            self._local.conn.close()
            del self._local.conn