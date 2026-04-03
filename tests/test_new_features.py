import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi_lens import LensMiddleware, LensConfig


@pytest.fixture
def app():
    app = FastAPI()
    LensConfig.ignore_unmapped = True # Ensure it's enabled
    LensMiddleware.setup(app, LensConfig(db_path=":memory:", security_enabled=False))
    
    @app.get("/valid")
    def valid():
        return {"ok": True}
    
    return app

@pytest.fixture
def client(app):
    return TestClient(app)

@pytest.mark.asyncio
async def test_ignore_unmapped_routes(client, app):
    # 1. Call a valid route
    client.get("/valid")
    
    # 2. Call an unmapped route (404)
    client.get("/invalid-path-123")
    
    # 3. Call an excluded route
    client.get("/favicon.ico")
    
    # Force flush
    middleware = app.state.lens_middleware
    await middleware.force_flush()
    
    # Check report
    resp = client.get("/lens/report")
    data = resp.json()
    
    paths = [e["path"] for e in data["endpoints"]]
    assert "/valid" in paths
    assert "/invalid-path-123" not in paths
    assert "/favicon.ico" not in paths

@pytest.mark.asyncio
async def test_advanced_metrics(client, app):
    # 1. Generate some specific traffic
    client.get("/valid") # 200
    
    # Add a route that fails
    @app.get("/error-4xx")
    def error_4xx():
        from fastapi import HTTPException
        raise HTTPException(status_code=400)
    
    @app.get("/error-5xx")
    def error_5xx():
        from fastapi import Response
        return Response(status_code=500)

    client.get("/error-4xx")
    client.get("/error-5xx")
    
    # Force flush
    middleware = app.state.lens_middleware
    await middleware.force_flush()
    
    # Check report
    data = client.get("/lens/report").json()
    
    valid_stat = next(e for e in data["endpoints"] if e["path"] == "/valid")
    err_4xx_stat = next(e for e in data["endpoints"] if e["path"] == "/error-4xx")
    err_5xx_stat = next(e for e in data["endpoints"] if e["path"] == "/error-5xx")
    
    assert valid_stat["error_4xx_count"] == 0
    assert valid_stat["error_5xx_count"] == 0
    assert err_4xx_stat["error_4xx_count"] == 1
    assert err_5xx_stat["error_5xx_count"] == 1
    assert "p50_duration_ms" in valid_stat
    assert "p99_duration_ms" in valid_stat
