"""
/lens/report endpoint.

Returns a JSON report with endpoint stats, health classification,
and summary metrics. Optionally protected by an API key header or query param.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.security.api_key import APIKeyHeader
from starlette.status import HTTP_403_FORBIDDEN

from ..core import LensConfig
from ..core.models import EndpointStats
from ..storage.sqlite import SQLiteStorage


def make_report_router(storage: SQLiteStorage, config: LensConfig) -> APIRouter:
    """
    Factory that returns a configured APIRouter.
    Keeps the router stateless and easy to test.
    """
    router = APIRouter(tags=["lens"])

    # --- Auth dependency (optional) ---
    _api_key_header = APIKeyHeader(name="X-Lens-Key", auto_error=False)

    def verify_key(
        header_key: Optional[str] = Depends(_api_key_header),
        query_key: Optional[str] = Query(None, alias="report_key"),
    ) -> None:
        if not config.security_enabled:
            return  # No security configured
            
        if config.report_key is None:
            # If security is enabled but no key is set, we block all access to be safe
            raise HTTPException(
                status_code=HTTP_403_FORBIDDEN,
                detail="Security is enabled but no report_key is configured on the server",
            )
        
        # Check both header and query parameter
        if header_key == config.report_key or query_key == config.report_key:
            return
            
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Forbidden: Invalid or missing report key (X-Lens-Key header or report_key query param)",
        )

    # --- Helpers ---
    def _since_timestamp(days: Optional[int]) -> float:
        if days is None:
            return 0.0
        return time.time() - (days * 86400)

    def _serialize_stat(stat: EndpointStats) -> Dict[str, Any]:
        return {
            "path": stat.path,
            "method": stat.method,
            "status": stat.status,
            "total_calls": stat.total_calls,
            "error_4xx_count": stat.error_4xx_count,
            "error_5xx_count": stat.error_5xx_count,
            "error_rate_pct": stat.error_rate,
            "success_rate_pct": stat.success_rate_pct,
            "avg_duration_ms": stat.avg_duration_ms,
            "p50_duration_ms": stat.p50_duration_ms,
            "p95_duration_ms": stat.p95_duration_ms,
            "p99_duration_ms": stat.p99_duration_ms,
            "max_duration_ms": stat.max_duration_ms,
            "last_called_at": stat.last_called_at,
            "first_called_at": stat.first_called_at,
            "days_since_last_call": stat.days_since_last_call,
        }

    # --- Routes ---

    @router.get(config.report_path)
    def report(
        days: Optional[int] = Query(None, description="Filter to last N days. Omit for all-time."),
        status: Optional[str] = Query(None, description="Filter by status: active, cold, dead, never_called"),
        _: None = Depends(verify_key),
    ) -> Dict[str, Any]:
        """
        Returns aggregated metrics for all recorded endpoints.

        - **active**: called within the last 7 days
        - **cold**: last call was 7–30 days ago
        - **dead**: no calls in 30+ days
        - **never_called**: endpoint exists in spec but no calls recorded
        """
        since = _since_timestamp(days)
        stats: List[EndpointStats] = storage.get_stats(since=since)

        # Enrich percentiles
        for stat in stats:
            p = storage.get_percentiles(stat.path, stat.method, since)
            stat.p50_duration_ms = p["p50"]
            stat.p95_duration_ms = p["p95"]
            stat.p99_duration_ms = p["p99"]

        # Optional filter by status
        if status:
            stats = [s for s in stats if s.status == status]

        total_requests = storage.total_requests(since=since)
        active = sum(1 for s in stats if s.status == "active")
        cold = sum(1 for s in stats if s.status == "cold")
        dead = sum(1 for s in stats if s.status == "dead")
        never_called = sum(1 for s in stats if s.status == "never_called")

        return {
            "generated_at": time.time(),
            "filters": {"days": days, "status": status},
            "summary": {
                "total_endpoints": len(stats),
                "total_requests": total_requests,
                "active": active,
                "cold": cold,
                "dead": dead,
                "never_called": never_called,
            },
            "endpoints": [_serialize_stat(s) for s in stats],
        }

    @router.get(f"{config.report_path}/top")
    def top_endpoints(
        limit: int = Query(10, ge=1, le=100, description="Number of top endpoints to return"),
        days: Optional[int] = Query(7, description="Window in days"),
        _: None = Depends(verify_key),
    ) -> Dict[str, Any]:
        """Returns the most called endpoints in the given time window."""
        since = _since_timestamp(days)
        stats = storage.get_stats(since=since, limit=limit)
        return {
            "generated_at": time.time(),
            "window_days": days,
            "endpoints": [_serialize_stat(s) for s in stats],
        }

    @router.get(f"{config.report_path}/dead")
    def dead_endpoints(
        days: Optional[int] = Query(None, description="Filter to last N days"),
        _: None = Depends(verify_key),
    ) -> Dict[str, Any]:
        """Returns only endpoints with no calls in 30+ days."""
        since = _since_timestamp(days)
        stats = storage.get_stats(since=since)
        dead = [s for s in stats if s.status in ("dead", "never_called")]
        return {
            "generated_at": time.time(),
            "dead_endpoint_count": len(dead),
            "endpoints": [_serialize_stat(s) for s in dead],
        }

    @router.get("/lens/dashboard")
    def dashboard(_: None = Depends(verify_key)) -> Response:
        """Returns a premium HTML dashboard. Insecure by default for easy viewing."""
        from starlette.responses import HTMLResponse
        
        # We use a single-file SPA for portability.
        # Design: Cyberpunk/Glassmorphism using Vanilla CSS + Inter Font.
        html = _DASHBOARD_HTML.replace("{{report_path}}", config.report_path)
        return HTMLResponse(content=html)

    return router


_DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>fastapi-lens 🔍 | Dashboard</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600&family=JetBrains+Mono&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #0f172a;
            --surface: #1e293b;
            --primary: #38bdf8;
            --primary-glow: rgba(56, 189, 248, 0.2);
            --danger: #f43f5e;
            --warning: #fbbf24;
            --success: #10b981;
            --text-main: #f8fafc;
            --text-dim: #94a3b8;
            --glass: rgba(255, 255, 255, 0.05);
            --border: rgba(255, 255, 255, 0.1);
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { 
            font-family: 'Outfit', sans-serif; 
            background: var(--bg); 
            color: var(--text-main); 
            line-height: 1.5;
            overflow-x: hidden;
        }
        .app { max-width: 1200px; margin: 0 auto; padding: 2rem; min-height: 100vh; }
        header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 2.5rem; }
        h1 { font-size: 2rem; font-weight: 600; display: flex; align-items: center; gap: 0.75rem; }
        h1 i { color: var(--primary); }
        .badge { padding: 0.25rem 0.75rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; }
        .badge-active { background: rgba(16, 185, 129, 0.1); color: var(--success); border: 1px solid var(--success); }
        .badge-cold { background: rgba(251, 191, 36, 0.1); color: var(--warning); border: 1px solid var(--warning); }
        .badge-dead { background: rgba(244, 63, 94, 0.1); color: var(--danger); border: 1px solid var(--danger); }
        
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 1.5rem; margin-bottom: 3rem; }
        .card { 
            background: var(--surface); 
            border: 1px solid var(--border); 
            border-radius: 1.25rem; 
            padding: 1.5rem; 
            transition: transform 0.2s, box-shadow 0.2s;
            position: relative;
            overflow: hidden;
        }
        .card:hover { transform: translateY(-4px); box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.3); }
        .card::after {
            content: ''; position: absolute; top: -50%; left: -50%; width: 200%; height: 200%;
            background: radial-gradient(circle at center, var(--primary-glow) 0%, transparent 70%);
            opacity: 0; transition: opacity 0.3s; pointer-events: none;
        }
        .card:hover::after { opacity: 1; }
        .card-label { font-size: 0.875rem; color: var(--text-dim); margin-bottom: 0.5rem; }
        .card-value { font-size: 2.25rem; font-weight: 600; letter-spacing: -0.025em; }
        
        .table-container { 
            background: var(--glass); 
            backdrop-filter: blur(12px); 
            border: 1px solid var(--border); 
            border-radius: 1.25rem; 
            overflow: hidden; 
        }
        table { width: 100%; border-collapse: collapse; text-align: left; }
        th { 
            background: rgba(255, 255, 255, 0.02); 
            padding: 1rem 1.5rem; 
            font-size: 0.75rem; 
            text-transform: uppercase; 
            letter-spacing: 0.1em; 
            color: var(--text-dim);
            border-bottom: 1px solid var(--border);
        }
        td { padding: 1rem 1.5rem; border-bottom: 1px solid var(--border); font-size: 0.95rem; }
        tr:last-child td { border-bottom: none; }
        tr:hover td { background: rgba(255, 255, 255, 0.02); }
        .path { font-family: 'JetBrains Mono', monospace; font-size: 0.875rem; color: var(--primary); }
        .method { font-weight: 600; margin-right: 0.5rem; width: 45px; display: inline-block; }
        .latency { font-family: 'JetBrains Mono', monospace; }
        
        .filters { display: flex; gap: 1rem; margin-bottom: 1.5rem; }
        .select { 
            background: var(--surface); color: var(--text-main); border: 1px solid var(--border); 
            padding: 0.5rem 1rem; border-radius: 0.75rem; font-family: inherit; cursor: pointer; outline: none;
        }
        .select:focus { border-color: var(--primary); box-shadow: 0 0 0 2px var(--primary-glow); }
        
        .loading { display: flex; justify-content: center; align-items: center; padding: 4rem; opacity: 0.5; }
        .error-rate-bar { width: 100%; height: 4px; background: rgba(255,255,255,0.05); border-radius: 2px; margin-top: 4px; overflow: hidden; }
        .error-rate-fill { height: 100%; background: var(--danger); transition: width 1s; }
    </style>
</head>
<body>
    <div class="app">
        <header>
            <h1><i>🔍</i> fastapi-lens</h1>
            <div id="last-updated" style="font-size: 0.875rem; color: var(--text-dim);">Actualizando...</div>
        </header>

        <div class="stats-grid" id="summary-cards">
            <div class="card">
                <div class="card-label">Total Traffic</div>
                <div class="card-value" id="val-total">-</div>
            </div>
            <div class="card">
                <div class="card-label">Success Rate</div>
                <div class="card-value" id="val-success">-</div>
            </div>
            <div class="card">
                <div class="card-label">Avg P95 Latency</div>
                <div class="card-value" id="val-latency">-</div>
            </div>
            <div class="card">
                <div class="card-label">Active Routes</div>
                <div class="card-value" id="val-active">-</div>
            </div>
        </div>

        <div class="filters">
            <select class="select" id="filter-days" onchange="loadData()">
                <option value="none">All Time</option>
                <option value="1">Last 24h</option>
                <option value="7" selected>Last 7 days</option>
                <option value="30">Last 30 days</option>
            </select>
            <select class="select" id="filter-status" onchange="renderTable()">
                <option value="all">All States</option>
                <option value="active">Active</option>
                <option value="cold">Cold</option>
                <option value="dead">Dead</option>
            </select>
        </div>

        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Endpoint</th>
                        <th>Health</th>
                        <th>Calls</th>
                        <th>Latency (P50/P95/P99)</th>
                        <th>Last Call</th>
                    </tr>
                </thead>
                <tbody id="endpoint-table">
                    <tr><td colspan="5" class="loading">Cargando métricas...</td></tr>
                </tbody>
            </table>
        </div>
    </div>

    <script>
        let currentData = null;

        async function loadData() {
            const days = document.getElementById('filter-days').value;
            const urlParams = new URLSearchParams(window.location.search);
            const reportKey = urlParams.get('report_key');
            
            let url = `{{report_path}}?days=${days === 'none' ? '' : days}`;
            if (reportKey) {
                url += `&report_key=${reportKey}`;
            }
            
            try {
                const resp = await fetch(url);
                if (!resp.ok) {
                    if (resp.status === 403) {
                        document.getElementById('endpoint-table').innerHTML = '<tr><td colspan="5" align="center" style="color: var(--danger)">403 Forbidden: Invalid or missing report_key</td></tr>';
                    }
                    return;
                }
                currentData = await resp.json();
                updateSummary();
                renderTable();
                document.getElementById('last-updated').innerText = `Updated at ${new Date().toLocaleTimeString()}`;
            } catch (err) {
                console.error("Lens error:", err);
                document.getElementById('endpoint-table').innerHTML = '<tr><td colspan="5" align="center" style="color: var(--danger)">Error loading data</td></tr>';
            }
        }

        function updateSummary() {
            if (!currentData || !currentData.summary) return;
            const s = currentData.summary;
            document.getElementById('val-total').innerText = s.total_requests.toLocaleString();
            
            const endpoints = currentData.endpoints || [];
            const avgP95 = endpoints.length > 0 ? (endpoints.reduce((acc, e) => acc + e.p95_duration_ms, 0) / endpoints.length).toFixed(1) : 0;
            const avgSuccess = endpoints.length > 0 ? (endpoints.reduce((acc, e) => acc + (e.success_rate_pct || 0), 0) / endpoints.length).toFixed(1) : 100;
            
            document.getElementById('val-latency').innerText = `${avgP95}ms`;
            document.getElementById('val-active').innerText = s.active;
            document.getElementById('val-success').innerText = `${avgSuccess}%`;
        }

        function renderTable() {
            const tbody = document.getElementById('endpoint-table');
            const statusFilter = document.getElementById('filter-status').value;
            
            let html = '';
            const endpoints = currentData.endpoints || [];
            endpoints.forEach(e => {
                if (statusFilter !== 'all' && e.status !== statusFilter) return;

                const errorRate = (100 - (e.success_rate_pct || 100)).toFixed(1);
                
                html += `
                    <tr>
                        <td>
                            <div><span class="method">${e.method}</span><span class="path">${e.path}</span></div>
                            <div class="error-rate-bar"><div class="error-rate-fill" style="width: ${errorRate}%"></div></div>
                        </td>
                        <td><span class="badge badge-${e.status}">${e.status}</span></td>
                        <td>${e.total_calls.toLocaleString()}</td>
                        <td class="latency">
                            <span style="color: var(--text-dim)">${e.p50_duration_ms}</span> / 
                            <span style="font-weight: 600">${e.p95_duration_ms}</span> / 
                            <span style="color: var(--danger)">${e.p99_duration_ms}</span> <small>ms</small>
                        </td>
                        <td style="color: var(--text-dim)">${e.days_since_last_call === 0 ? 'Recently' : e.days_since_last_call + ' days ago'}</td>
                    </tr>
                `;
            });
            tbody.innerHTML = html || '<tr><td colspan="5" align="center">No routes match your filters</td></tr>';
        }

        loadData();
        setInterval(loadData, 30000); // Auto-refresh 30s
    </script>
</body>
</html>
"""