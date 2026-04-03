"""
Tests for fastapi-lens.

Uses in-memory SQLite (:memory:) so tests are fast and isolated.
"""
from __future__ import annotations
import asyncio

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastapi_lens import LensConfig, LensMiddleware


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app_no_auth() -> FastAPI:
    app = FastAPI()
    LensMiddleware.setup(app, LensConfig(
        db_path=":memory:",
        security_enabled=False,
        flush_interval=0.1,
    ))

    @app.get("/items")
    def list_items():
        return [{"id": 1}, {"id": 2}]

    @app.get("/items/{item_id}")
    def get_item(item_id: int):
        return {"id": item_id}

    @app.get("/slow")
    def slow_endpoint():
        return {"slow": True}

    @app.delete("/items/{item_id}")
    def delete_item(item_id: int):
        return {"deleted": item_id}

    return app


@pytest.fixture
def app_with_auth() -> FastAPI:
    app = FastAPI()
    LensMiddleware.setup(app, LensConfig(
        db_path=":memory:",
        security_enabled=True,
        report_key="test-secret",
        flush_interval=0.1,
    ))

    @app.get("/ping")
    def ping():
        return {"ping": "pong"}

    return app


@pytest.fixture
def client(app_no_auth) -> TestClient:
    return TestClient(app_no_auth)


@pytest.fixture
def auth_client(app_with_auth) -> TestClient:
    return TestClient(app_with_auth)


# ---------------------------------------------------------------------------
# Middleware — basic capture
# ---------------------------------------------------------------------------

class TestMiddlewareCapture:
    def test_request_does_not_change_response(self, client):
        resp = client.get("/items")
        assert resp.status_code == 200
        assert resp.json() == [{"id": 1}, {"id": 2}]

    def test_parameterized_route_grouped(self, client):
        """Both /items/1 and /items/2 should map to /items/{item_id}."""
        client.get("/items/1")
        client.get("/items/2")
        # verify template resolution doesn't crash
        resp = client.get("/items/99")
        assert resp.status_code == 200

    def test_report_path_excluded_from_recording(self, client):
        """Calls to /lens/report must not be recorded in the DB."""
        client.get("/lens/report")
        # If it were recorded, the stats would include /lens/report as an endpoint
        resp = client.get("/lens/report")
        data = resp.json()
        endpoints = [e["path"] for e in data["endpoints"]]
        assert "/lens/report" not in endpoints


# ---------------------------------------------------------------------------
# Report endpoint
# ---------------------------------------------------------------------------

class TestReportEndpoint:
    def test_report_returns_200(self, client):
        client.get("/items")
        resp = client.get("/lens/report")
        assert resp.status_code == 200

    def test_report_structure(self, client):
        client.get("/items")
        data = client.get("/lens/report").json()
        assert "summary" in data
        assert "endpoints" in data
        assert "generated_at" in data

    @pytest.mark.asyncio
    async def test_summary_counts(self, client, app_no_auth):
        for _ in range(3):
            client.get("/items")
        
        middleware = app_no_auth.state.lens_middleware
        
        await middleware.force_flush()
        
        data = client.get("/lens/report").json()
        
        print(f"DEBUG: Encontradas {data['summary']['total_requests']} peticiones")
        
        assert data["summary"]["total_requests"] >= 3

    def test_top_endpoint(self, client):
        for _ in range(5):
            client.get("/items")
        for _ in range(2):
            client.get("/slow")
        time.sleep(0.2)
        data = client.get("/lens/report/top?limit=1").json()
        assert len(data["endpoints"]) == 1
        assert data["endpoints"][0]["path"] == "/items"

    def test_dead_endpoint_route(self, client):
        resp = client.get("/lens/report/dead")
        assert resp.status_code == 200
        assert "dead_endpoint_count" in resp.json()

    def test_days_filter(self, client):
        client.get("/items")
        time.sleep(0.2)
        data = client.get("/lens/report?days=1").json()
        assert data["filters"]["days"] == 1

    def test_status_filter(self, client):
        client.get("/items")
        time.sleep(0.2)
        resp = client.get("/lens/report?status=active")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class TestAuth:
    def test_missing_key_returns_403(self, auth_client):
        resp = auth_client.get("/lens/report")
        assert resp.status_code == 403

    def test_wrong_key_returns_403(self, auth_client):
        resp = auth_client.get("/lens/report", headers={"X-Lens-Key": "wrong"})
        assert resp.status_code == 403

    def test_correct_key_returns_200(self, auth_client):
        resp = auth_client.get("/lens/report", headers={"X-Lens-Key": "test-secret"})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# EndpointStats model
# ---------------------------------------------------------------------------

class TestEndpointStats:
    def test_error_rate_zero_calls(self):
        from fastapi_lens.core.models import EndpointStats
        stat = EndpointStats(
            path="/x", method="GET", total_calls=0, 
            error_4xx_count=0, error_5xx_count=0,
            avg_duration_ms=0, p50_duration_ms=0, p95_duration_ms=0, p99_duration_ms=0, max_duration_ms=0,
            last_called_at=None, first_called_at=None,
        )
        assert stat.error_rate == 0.0
        assert stat.status == "never_called"

    def test_status_active(self):
        from fastapi_lens.core.models import EndpointStats
        stat = EndpointStats(
            path="/x", method="GET", total_calls=10, 
            error_4xx_count=0, error_5xx_count=0,
            avg_duration_ms=50, p50_duration_ms=60, p95_duration_ms=80, p99_duration_ms=90, max_duration_ms=100,
            last_called_at=time.time() - 3600,  # 1 hour ago
            first_called_at=time.time() - 86400,
        )
        assert stat.status == "active"

    def test_status_dead(self):
        from fastapi_lens.core.models import EndpointStats
        stat = EndpointStats(
            path="/x", method="GET", total_calls=1, 
            error_4xx_count=0, error_5xx_count=0,
            avg_duration_ms=50, p50_duration_ms=50, p95_duration_ms=80, p99_duration_ms=80, max_duration_ms=80,
            last_called_at=time.time() - (40 * 86400),  # 40 days ago
            first_called_at=time.time() - (50 * 86400),
        )
        assert stat.status == "dead"