import asyncio
import time
import pytest
from fastapi import FastAPI
from fastapi_lens import LensMiddleware, LensConfig
from fastapi_lens.core.models import RequestRecord
from httpx import AsyncClient, ASGITransport

@pytest.fixture
def ttl_config():
    return LensConfig(
        db_path=":memory:", 
        ttl_days=1, 
        security_enabled=False
    )

@pytest.mark.asyncio
async def test_storage_cleanup_logic(ttl_config):
    """
    Test unitario: Verifica que el método del Storage realmente borra
    lo viejo y mantiene lo nuevo.
    """
    from fastapi_lens.storage.sqlite import SQLiteStorage
    storage = SQLiteStorage(ttl_config.db_path)
    
    now = time.time()
    day_in_seconds = 86400
    
    # we create manual records with different ages
    records = [
        # Record from 2 days ago (Should be deleted)
        RequestRecord(path="/old", method="GET", status_code=200, duration_ms=10, timestamp=now - (2 * day_in_seconds)),
        # Record from today (Should stay)
        RequestRecord(path="/new", method="GET", status_code=200, duration_ms=10, timestamp=now),
    ]
    
    storage.insert_batch(records)
    assert storage.total_requests() == 2
    
    # we execute cleanup for records older than 1 day
    deleted = storage.cleanup_old_data(days=1)
    
    assert deleted == 1
    assert storage.total_requests() == 1
    
    # Verify that the one that remained is the new one
    stats = storage.get_stats()
    assert stats[0].path == "/new"
    storage.close()

@pytest.mark.asyncio
async def test_middleware_ttl_task_lifecycle(ttl_config):
    """
    Verify that the cleanup task starts and stops correctly in the middleware.
    """
    app = FastAPI()
    LensMiddleware.setup(app, ttl_config)
    
    # We use AsyncClient and ASGITransport
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # We make the request asynchronously
        await ac.get("/")
        
        # We get the middleware from the app state
        middleware = app.state.lens_middleware
        
        assert middleware is not None
        assert middleware._cleanup_task is not None
        
        # We verify that the task is active (not done)
        assert not middleware._cleanup_task.done()
        
        # Now the await will work perfectly because we are in the same loop
        await middleware.close()
        
        assert middleware._cleanup_task.done()

@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_ttl_disabled_if_zero():
    app = FastAPI()
    config = LensConfig(db_path=":memory:", ttl_days=0)
    LensMiddleware.setup(app, config)
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.get("/")
        middleware = app.state.lens_middleware
        assert middleware._cleanup_task is None