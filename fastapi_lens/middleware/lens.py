"""
LensMiddleware — captures request metrics with minimal overhead.

Design decisions:
- asyncio.Queue for non-blocking capture (request path is never slowed)
- Background asyncio.Task drains the queue and batches writes to SQLite
- No external dependencies beyond FastAPI/Starlette
- Router registration uses setup() classmethod to avoid Starlette wrapper issues
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, List, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match
from starlette.types import ASGIApp

from ..core import LensConfig
from ..core.models import RequestRecord
from ..storage.sqlite import SQLiteStorage

logger = logging.getLogger("fastapi_lens")

# Shares a SQLiteStorage instance between setup() and __init__()
# so the router and middleware write to the same DB connection.
_storage_cache: Dict[int, SQLiteStorage] = {}


class LensMiddleware(BaseHTTPMiddleware):
    """
    Lightweight middleware that records request metrics into SQLite.

    Recommended usage via setup()::

        from fastapi import FastAPI
        from fastapi_lens import LensMiddleware, LensConfig

        app = FastAPI()
        LensMiddleware.setup(app, LensConfig(report_key="secret"))

    Manual usage (advanced)::

        app.add_middleware(LensMiddleware, config=LensConfig())
        # Then register the router yourself:
        from fastapi_lens.api.report import make_report_router
        app.include_router(make_report_router(storage, config))
    """

    def __init__(self, app: ASGIApp, config: Optional[LensConfig] = None) -> None:
        super().__init__(app)
        self.config = config or LensConfig()

        cfg_id = id(self.config)
        if cfg_id in _storage_cache:
            self.storage = _storage_cache.pop(cfg_id)
        else:
            self.storage = SQLiteStorage(self.config.db_path)

        self._queue: asyncio.Queue[RequestRecord] = asyncio.Queue(maxsize=10_000)
        self._flush_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None # <--- Nuevo
        self._lock = asyncio.Lock() # New: To avoid 2 requests creating 2 loops
        self._started = False

    @classmethod
    def setup(cls, app: "FastAPI", config: Optional[LensConfig] = None) -> None:  # type: ignore[name-defined]
        """
        Registers the /lens/report router AND adds the middleware in one call.

        This is the recommended usage because it guarantees the router is
        registered on the real FastAPI instance before Starlette wraps it
        in middleware layers (which breaks isinstance checks in __init__).
        """
        from fastapi_lens.api.report import make_report_router

        cfg = config or LensConfig()

        # Create storage once and cache it so __init__ reuses the same instance
        storage = SQLiteStorage(cfg.db_path)
        _storage_cache[id(cfg)] = storage

        # Register the report router directly on the FastAPI app
        router = make_report_router(storage, cfg)
        app.include_router(router)

        # Add the middleware — __init__ will pick up storage from cache
        app.add_middleware(cls, config=cfg)


    async def _ensure_flush_task(self) -> None:
        """Start background tasks lazily on first request."""
        if self._started:
            return

        async with self._lock: 
            if not self._started:
                loop = asyncio.get_running_loop()
                self._flush_task = loop.create_task(self._flush_loop(), name="lens_flush")
                
                if self.config.ttl_days:
                    self._cleanup_task = loop.create_task(self._cleanup_loop(), name="lens_cleanup")
                
                self._started = True

    async def _cleanup_loop(self) -> None:
        """
        Background task: Runs once every 24 hours to delete records older than TTL.
        Uses run_in_executor to avoid blocking the event loop during VACUUM.
        """
        # We wait 60 seconds before the first cleanup to not stress the app startup.
        await asyncio.sleep(60)

        if not self.config.ttl_days:
            return

        while True:
            try:
                loop = asyncio.get_event_loop()
                # We execute the cleanup (which includes DELETE + VACUUM)
                deleted = await loop.run_in_executor(
                    None, 
                    self.storage.cleanup_old_data, 
                    self.config.ttl_days
                )
                
                if deleted > 0:
                    logger.info("lens ttl cleanup: removed %d expired records", deleted)
                
                # Wait 24 hours for the next round
                await asyncio.sleep(86400) 

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("lens cleanup error: %s. Retrying in 1 hour.", exc)
                # If it fails (e.g. DB blocked), we retry in 1 hour instead of 24
                await asyncio.sleep(3600)

    async def force_flush(self) -> None:
        """Flushes the queue of requests to the DB immediately."""
        batch: List[RequestRecord] = []
        while not self._queue.empty():
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        
        if batch:
            # We use run_in_executor to avoid blocking if the DB is busy
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.storage.insert_batch, batch)

    async def _flush_loop(self) -> None:
        """
        Background task: drain the queue every flush_interval seconds
        OR when batch is full — whichever comes first.
        """
        batch: List[RequestRecord] = []
        interval = self.config.flush_interval
        max_batch = self.config.max_batch_size

        while True:
            try:
                deadline = time.monotonic() + interval
                while time.monotonic() < deadline:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    try:
                        record = await asyncio.wait_for(
                            self._queue.get(), timeout=remaining
                        )
                        batch.append(record)
                        if len(batch) >= max_batch:
                            break
                    except asyncio.TimeoutError:
                        break

                if batch:
                    # Run sync SQLite write in thread pool — don't block event loop
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, self.storage.insert_batch, batch)
                    batch = []

            except asyncio.CancelledError:
                # Graceful shutdown: flush remaining records
                if batch:
                    self.storage.insert_batch(batch)
                break
            except Exception as exc:  # pragma: no cover
                logger.warning("lens flush error: %s", exc)
                batch = []

    def _should_record(self, path: str, method: str) -> bool:
        if method in self.config.exclude_methods:
            return False
        for excluded in self.config.exclude_paths:
            if path.startswith(excluded):
                return False
        return True

    def _resolve_path_template(self, request: Request) -> Optional[str]:
        """
        Return the route template (e.g. /users/{user_id}) instead of
        the actual path (/users/42) to group parameterized routes correctly.
        Returns None if no matching route is found (404 or unmapped).
        """
        if not hasattr(request.app, "routes"):
            return request.url.path

        for route in request.app.routes:
            match, _ = route.matches(request.scope)
            if match == Match.FULL:
                return getattr(route, "path", request.url.path)
        return None

    async def dispatch(self, request: Request, call_next) -> Response:
        await self._ensure_flush_task()

        if not hasattr(request.app.state, "lens_middleware"):
            try:
                request.app.state.lens_middleware = self
            except Exception: pass

        path = self._resolve_path_template(request)
        method = request.method

        if path is None:
            if self.config.ignore_unmapped:
                return await call_next(request)
            path = request.url.path

        if not self._should_record(path, method):
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        record = RequestRecord(
            path=path,
            method=method,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 3),
            timestamp=time.time(),
            client_ip=request.client.host if request.client else None,
        )

        try:
            self._queue.put_nowait(record)
        except asyncio.QueueFull:
            logger.debug("lens queue full — dropping record")

        return response

    async def close(self) -> None:
        """Call on app shutdown to flush pending records and stop cleanup."""
        # Cancel flush
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        
        # Cancel cleanup
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
                
        self.storage.close()