"""
/lens/report endpoint.

Returns a JSON report with endpoint stats, health classification,
and summary metrics. Optionally protected by an API key header or query param.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
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

    _api_key_header = APIKeyHeader(name="X-Lens-Key", auto_error=False)

    def verify_key(
        days: Optional[str] = Query(None), 
        header_key: Optional[str] = Depends(_api_key_header),
        query_key: Optional[str] = Query(None, alias="report_key"),
    ) -> None:
        if not config.security_enabled:
            return

        if days is None or days == "":
            return

        if config.report_key is None:
            raise HTTPException(status_code=403, detail="Security set but no key configured")
        
        if header_key == config.report_key or query_key == config.report_key:
            return
            
        raise HTTPException(status_code=403, detail="Acceso Denegado")

    # --- Helpers ---
    def _since_timestamp(days: Optional[int]) -> float:
        if days is None:
            return 0.0
        return time.time() - (days * 86400)

    def _serialize_stat(stat: EndpointStats) -> Dict[str, Any]:
        """Convierte el modelo a un diccionario compatible con el Dashboard."""
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
        request: Request, # Añadimos el request para acceder a las rutas de la app
        days: Optional[int] = Query(None),
        status: Optional[str] = Query(None),
        _: None = Depends(verify_key),
    ) -> Dict[str, Any]:
        since = _since_timestamp(days)
        # 1. Obtener lo que SI está en la DB
        db_stats: List[EndpointStats] = storage.get_stats(since=since)
        recorded_keys = {(s.path, s.method) for s in db_stats}

        # 2. DISCOVERY: Buscar rutas en la App que NO están en la DB
        all_stats = list(db_stats)
        
        # Iteramos sobre las rutas registradas en FastAPI
        for route in request.app.routes:
            # Solo nos interesan rutas de tipo APIRoute (ignora mounts/static)
            if hasattr(route, "path") and hasattr(route, "methods"):
                path = route.path
                # Saltamos las rutas excluidas y las propias de Lens
                if not any(path.startswith(ex) for ex in config.exclude_paths):
                    for method in route.methods:
                        if (path, method) not in recorded_keys:
                            # Creamos un objeto "Never Called" virtual
                            all_stats.append(EndpointStats(
                                path=path,
                                method=method,
                                total_calls=0,
                                error_4xx_count=0,
                                error_5xx_count=0,
                                avg_duration_ms=0,
                                p50_duration_ms=0,
                                p95_duration_ms=0,
                                p99_duration_ms=0,
                                max_duration_ms=0,
                                last_called_at=None,
                                first_called_at=None,
                            ))

        # 3. Enriquecer percentiles solo para los que tienen llamadas
        for stat in all_stats:
            if stat.total_calls > 0:
                p = storage.get_percentiles(stat.path, stat.method, since)
                stat.p50_duration_ms = p["p50"]
                stat.p95_duration_ms = p["p95"]
                stat.p99_duration_ms = p["p99"]

        # 4. Filtro opcional por status (ahora incluye 'never_called')
        if status:
            all_stats = [s for s in all_stats if s.status == status]

        return {
            "generated_at": time.time(),
            "filters": {"days": days, "status": status},
            "summary": {
                "total_endpoints": len(all_stats),
                "total_requests": storage.total_requests(since=since),
                "active": sum(1 for s in all_stats if s.status == "active"),
                "cold": sum(1 for s in all_stats if s.status == "cold"),
                "dead": sum(1 for s in all_stats if s.status == "dead"),
                "never_called": sum(1 for s in all_stats if s.status == "never_called"),
            },
            "endpoints": [_serialize_stat(s) for s in all_stats],
        }

    @router.get(f"{config.report_path}/top")
    def top_endpoints(
        limit: int = Query(10, ge=1, le=100),
        days: Optional[int] = Query(7),
        _: None = Depends(verify_key),
    ) -> Dict[str, Any]:
        since = _since_timestamp(days)
        stats = storage.get_stats(since=since, limit=limit)
        # Also enrich percentiles here for consistency
        for stat in stats:
            p = storage.get_percentiles(stat.path, stat.method, since)
            stat.p50_duration_ms = p["p50"]
            stat.p95_duration_ms = p["p95"]
            stat.p99_duration_ms = p["p99"]
            
        return {
            "generated_at": time.time(),
            "window_days": days,
            "endpoints": [_serialize_stat(s) for s in stats],
        }

    @router.get(f"{config.report_path}/dead")
    def dead_endpoints(
        days: Optional[int] = Query(None),
        _: None = Depends(verify_key),
    ) -> Dict[str, Any]:
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
        from starlette.responses import HTMLResponse
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
            --bg: #0f172a; --surface: #1e293b; --primary: #38bdf8; --primary-glow: rgba(56, 189, 248, 0.2);
            --danger: #f43f5e; --warning: #fbbf24; --success: #10b981; --text-main: #f8fafc;
            --text-dim: #94a3b8; --glass: rgba(255, 255, 255, 0.05); --border: rgba(255, 255, 255, 0.1);
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Outfit', sans-serif; background: var(--bg); color: var(--text-main); line-height: 1.5; overflow-x: hidden; }
        .app { max-width: 1240px; margin: 0 auto; padding: 2rem; min-height: 100vh; }
        
        header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 2.5rem; }
        h1 { font-size: 1.75rem; font-weight: 600; }
        h1 span { color: var(--primary); }
        .refresh-indicator { display: flex; align-items: center; gap: 0.6rem; font-size: 0.85rem; color: var(--text-dim); background: var(--glass); padding: 0.5rem 1rem; border-radius: 2rem; border: 1px solid var(--border); }
        .pulse { width: 10px; height: 10px; background: var(--success); border-radius: 50%; display: inline-block; animation: pulse 2s infinite; }
        @keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.5); } 70% { box-shadow: 0 0 0 10px rgba(16, 185, 129, 0); } 100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); } }

        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1.25rem; margin-bottom: 2.5rem; }
        .card { background: var(--surface); border: 1px solid var(--border); border-radius: 1.25rem; padding: 1.5rem; transition: all 0.3s ease; position: relative; overflow: hidden; }
        .card:hover { transform: translateY(-5px); border-color: var(--primary); box-shadow: 0 10px 30px -10px rgba(0,0,0,0.5); }
        .card-label { font-size: 0.75rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.1em; font-weight: 600; }
        .card-value { font-size: 2rem; font-weight: 600; margin-top: 0.5rem; letter-spacing: -0.02em; }

        .controls { display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1.5rem; align-items: center; }
        .search-box { flex-grow: 1; min-width: 280px; position: relative; }
        .search-box input { 
            width: 100%; background: var(--surface); border: 1px solid var(--border); color: white; 
            padding: 0.75rem 1.25rem; border-radius: 1rem; font-family: inherit; outline: none; transition: border-color 0.2s;
        }
        .search-box input:focus { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-glow); }
        .select { background: var(--surface); color: white; border: 1px solid var(--border); padding: 0.75rem 1rem; border-radius: 1rem; cursor: pointer; font-family: inherit; outline: none; }
        .select:hover { border-color: var(--primary); }

        .table-container { background: var(--glass); backdrop-filter: blur(10px); border: 1px solid var(--border); border-radius: 1.25rem; overflow: hidden; }
        table { width: 100%; border-collapse: collapse; text-align: left; }
        th { background: rgba(255, 255, 255, 0.03); padding: 1.25rem; font-size: 0.7rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.1em; border-bottom: 1px solid var(--border); }
        td { padding: 1.25rem; border-bottom: 1px solid var(--border); vertical-align: middle; }
        tr:last-child td { border-bottom: none; }
        tr:hover td { background: rgba(255, 255, 255, 0.02); }

        .badge { padding: 0.25rem 0.75rem; border-radius: 8px; font-size: 0.7rem; font-weight: 600; text-transform: uppercase; display: inline-block; }
        .badge-active { background: rgba(16, 185, 129, 0.1); color: var(--success); border: 1px solid var(--success); }
        .badge-cold { background: rgba(251, 191, 36, 0.1); color: var(--warning); border: 1px solid var(--warning); }
        .badge-dead { background: rgba(244, 63, 94, 0.1); color: var(--danger); border: 1px solid var(--danger); }
        .badge-never_called { background: rgba(148, 163, 184, 0.1); color: var(--text-dim); border: 1px solid var(--text-dim); }
        
        .method { font-family: 'JetBrains Mono'; font-weight: 600; font-size: 0.75rem; color: var(--primary); background: var(--primary-glow); padding: 3px 8px; border-radius: 6px; margin-right: 10px; }
        .path { font-family: 'JetBrains Mono'; font-size: 0.9rem; color: var(--text-main); }

        .error-breakdown { display: flex; height: 6px; border-radius: 3px; overflow: hidden; background: rgba(255,255,255,0.05); margin-top: 10px; width: 180px; }
        .err-4xx { background: var(--warning); height: 100%; transition: width 0.5s ease; }
        .err-5xx { background: var(--danger); height: 100%; transition: width 0.5s ease; }
        
        .latency-cell { font-family: 'JetBrains Mono'; font-size: 0.85rem; color: var(--text-dim); white-space: nowrap; }
        .latency-cell b { color: var(--text-main); }
        .p99 { color: var(--danger) !important; font-weight: 600; }
    </style>
</head>
<body>
    <div class="app">
        <header>
            <h1>fastapi-lens <span>🔍</span></h1>
            <div class="refresh-indicator">
                <span class="pulse"></span>
                <span id="last-updated">Loading...</span>
            </div>
        </header>

        <div class="stats-grid">
            <div class="card">
                <div class="card-label">Total Routes</div>
                <div id="val-total-routes" class="card-value">-</div>
            </div>
            <div class="card">
                <div class="card-label">Total Traffic</div>
                <div id="val-total" class="card-value">-</div>
            </div>
            <div class="card">
                <div class="card-label">Success Rate</div>
                <div id="val-success" class="card-value">-</div>
            </div>
            <div class="card">
                <div class="card-label">Avg P95 Latency</div>
                <div id="val-latency" class="card-value">-</div>
            </div>
            <div class="card">
                <div class="card-label">Active Routes</div>
                <div id="val-active" class="card-value">-</div>
            </div>
        </div>

        <div class="controls">
            <div class="search-box">
                <input type="text" id="search-input" placeholder="Search by endpoint or method..." oninput="renderTable()">
            </div>
            
            <select class="select" id="filter-status" onchange="renderTable()">
                <option value="all">All Statuses</option>
                <option value="active">Active</option>
                <option value="cold">Cold</option>
                <option value="dead">Dead</option>
                <option value="never_called">Never Called</option>
            </select>

            <select class="select" id="filter-days" onchange="loadData()">
                <option value="none">All Time</option>
                <option value="1">Last 24h</option>
                <option value="7" selected>Last 7 days</option>
                <option value="30">Last 30 days</option>
            </select>
            
            <select class="select" id="filter-sort" onchange="renderTable()">
                <option value="calls">Sort by Traffic</option>
                <option value="p95">Sort by Latency (P95)</option>
                <option value="path">Sort A-Z</option>
            </select>
        </div>

        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Endpoint & Errors</th>
                        <th>Status</th>
                        <th>Calls</th>
                        <th>Latency (P50 / P95 / P99)</th>
                        <th>Last Call</th>
                    </tr>
                </thead>
                <tbody id="endpoint-table"></tbody>
            </table>
        </div>
    </div>

    <script>
        let currentData = null;

        async function loadData() {
            const daysVal = document.getElementById('filter-days').value;
            const urlParams = new URLSearchParams(window.location.search);
            const reportKey = urlParams.get('report_key');
            
            const params = new URLSearchParams();
            if (daysVal !== 'none') params.append('days', daysVal);
            if (reportKey) params.append('report_key', reportKey);

            const queryString = params.toString();
            const url = `{{report_path}}${queryString ? '?' + queryString : ''}`;
            
            try {
                const resp = await fetch(url);
                if (resp.status === 403) throw new Error("AUTH_REQUIRED");
                if (!resp.ok) throw new Error("SERVER_ERROR");

                currentData = await resp.json();
                updateSummary();
                renderTable();
                document.getElementById('last-updated').innerText = `Last updated: ${new Date().toLocaleTimeString()}`;
            } catch (err) {
                let title = "System Error";
                let detail = "Could not fetch metrics.";
                if (err.message === "AUTH_REQUIRED") {
                    title = "Access Denied";
                    detail = "Invalid report_key or missing X-Lens-Key.";
                }
                document.getElementById('endpoint-table').innerHTML = `
                    <tr><td colspan="5" style="text-align:center; padding:4rem;">
                        <div style="color:var(--danger); font-size:1.2rem; font-weight:600;">${title}</div>
                        <div style="color:var(--text-dim); margin-top:0.5rem;">${detail}</div>
                    </td></tr>`;
            }
        }

        function updateSummary() {
            if (!currentData) return;
            const s = currentData.summary;
            document.getElementById('val-total-routes').innerText = s.total_endpoints.toLocaleString();
            document.getElementById('val-total').innerText = s.total_requests.toLocaleString();
            document.getElementById('val-active').innerText = s.active;
            
            const endpoints = (currentData.endpoints || []).filter(e => e.total_calls > 0);
            if (endpoints.length > 0) {
                const avgP95 = (endpoints.reduce((acc, e) => acc + e.p95_duration_ms, 0) / endpoints.length).toFixed(1);
                const avgSuccess = (endpoints.reduce((acc, e) => acc + (e.success_rate_pct || 0), 0) / endpoints.length).toFixed(1);
                document.getElementById('val-latency').innerText = `${avgP95}ms`;
                document.getElementById('val-success').innerText = `${avgSuccess}%`;
            } else {
                document.getElementById('val-latency').innerText = "0ms";
                document.getElementById('val-success').innerText = "100%";
            }
        }

        function renderTable() {
            if (!currentData) return;
            const tbody = document.getElementById('endpoint-table');
            const searchTerm = document.getElementById('search-input').value.toLowerCase();
            const sortBy = document.getElementById('filter-sort').value;
            const statusFilter = document.getElementById('filter-status').value;
            
            let endpoints = [...(currentData.endpoints || [])];

            if (statusFilter !== 'all') {
                endpoints = endpoints.filter(e => e.status === statusFilter);
            }

            endpoints = endpoints.filter(e => 
                e.path.toLowerCase().includes(searchTerm) || 
                e.method.toLowerCase().includes(searchTerm)
            );

            endpoints.sort((a, b) => {
                if (sortBy === 'calls') return b.total_calls - a.total_calls;
                if (sortBy === 'p95') return b.p95_duration_ms - a.p95_duration_ms;
                return a.path.localeCompare(b.path);
            });

            let html = '';
            endpoints.forEach(e => {
                const err4pct = (e.error_4xx_count / e.total_calls * 100) || 0;
                const err5pct = (e.error_5xx_count / e.total_calls * 100) || 0;
                
                // --- ATOMIC SMART DATE LOGIC ---
                let dateDisplay = "Never";
                if (e.last_called_at) {
                    const d = new Date(e.last_called_at * 1000);
                    const now = new Date();
                    
                    // Format time HH:MM
                    const timeStr = d.getHours().toString().padStart(2, '0') + ':' + 
                                  d.getMinutes().toString().padStart(2, '0');
                    
                    // Check if it's actually the same calendar day (ignoring backend diff)
                    const isToday = d.toDateString() === now.toDateString();

                    if (isToday) {
                        dateDisplay = `Today ${timeStr}`;
                    } else {
                        const dateStr = d.toISOString().split('T')[0];
                        dateDisplay = `${dateStr} ${timeStr}`;
                    }
                }

                html += `
                    <tr>
                        <td>
                            <span class="method">${e.method}</span><span class="path">${e.path}</span>
                            <div class="error-breakdown" title="Errors: ${e.error_4xx_count} 4xx / ${e.error_5xx_count} 5xx">
                                <div class="err-4xx" style="width: ${err4pct}%"></div>
                                <div class="err-5xx" style="width: ${err5pct}%"></div>
                            </div>
                        </td>
                        <td><span class="badge badge-${e.status}">${e.status.replace('_', ' ')}</span></td>
                        <td style="font-weight:600; font-size:1.1rem;">${e.total_calls.toLocaleString()}</td>
                        <td class="latency-cell">
                            <b>${e.p50_duration_ms}</b> / <b>${e.p95_duration_ms}</b> / <b class="p99">${e.p99_duration_ms}</b> <small>ms</small>
                        </td>
                        <td style="color:var(--text-dim); font-size:0.85rem">
                            ${dateDisplay}
                        </td>
                    </tr>
                `;
            });
            tbody.innerHTML = html || '<tr><td colspan="5" style="text-align:center; padding:3rem; color:var(--text-dim);">No endpoints found.</td></tr>';
        }

        loadData();
        setInterval(loadData, 30000);
    </script>
</body>
</html>
"""