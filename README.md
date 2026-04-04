# fastapi-lens

> **API usage intelligence for FastAPI** — Lightweight middleware that identifies thriving, cold, and dead endpoints. Zero-infrastructure, high-performance monitoring.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com)
[![PyPI version](https://badge.fury.io/py/fastapi-lens.svg)](https://badge.fury.io/py/fastapi-lens)

---

## What's New in v0.3.0 (The Maintenance Update)

The **v0.3.0** release marks a milestone in stability and automation:
- **Dynamic TTL Cleanup**: Automatically purge old logs to keep your SQLite database lean and fast.
- **Advanced Latency (Percentiles)**: Support for **P50, P95, and P99** metrics to find real bottlenecks.
- **Error Segregation**: Distinct tracking for `4xx` (Client) vs `5xx` (Server) errors.
- **Trusted Publishing (OIDC)**: Fully automated and secure deployments to PyPI via GitHub Actions.
- **Concurrency Fixes**: Internal `asyncio.Lock` mechanisms to prevent race conditions during startup.

---

## 📊 HTML Dashboard

Visualizing your API health has never been easier. Access a built-in, glassmorphism-style dashboard at `/lens/dashboard`.

### Key Dashboard Features:
- **Real-time Metrics**: Traffic totals, Success rates, and Active route counts.
- **Latency Distribution**: Watch your P95 and P99 response times per route.
- **Error Visualization**: Red/Green health bars indicating error rates.
- **Status Filtering**: Quickly find "Dead" or "Cold" endpoints to clean up your codebase.

![Dashboard Preview](https://raw.githubusercontent.com/AVR216/fastapi-lens/v0.3.2/static/dashboard.png)

---

## Installation

```bash
pip install fastapi-lens
```

---

## 🛠️ Step-by-Step Setup (The "Senior" Way)

The recommended way to use `fastapi-lens` is via the `setup()` method, which handles both middleware and router registration automatically.

### 1. Basic Integration
```python
from fastapi import FastAPI
from fastapi_lens import LensMiddleware, LensConfig

app = FastAPI()

# One-liner setup
LensMiddleware.setup(
    app, 
    config=LensConfig(
        db_path="lens.db",
        ttl_days=14,           # Auto-delete records older than 14 days
        security_enabled=True,
        report_key="your-secret-passphrase"
    )
)
```

### 2. Access your data
- **UI**: `http://localhost:8000/lens/dashboard?report_key=your-secret-passphrase`
- **JSON API**: Send request with header `X-Lens-Key: your-secret-passphrase` to `/lens/report`.

> **NOTE**: If you set `security_enabled=False`, you can access the dashboard and API without a report key, using the default URL `http://localhost:8000/lens/dashboard` and `http://localhost:8000/lens/report`.


 The report looks like this:

```json
{
  "generated_at": 1775243992.65774,
  "filters": {
    "days": null,
    "status": null
  },
  "summary": {
    "total_endpoints": 3,
    "total_requests": 71,
    "active": 3,
    "cold": 0,
    "dead": 0,
    "never_called": 0
  },
  "endpoints": [
    {
      "path": "/items",
      "method": "GET",
      "status": "active",
      "total_calls": 26,
      "error_4xx_count": 0,
      "error_5xx_count": 0,
      "error_rate_pct": 0,
      "success_rate_pct": 100,
      "avg_duration_ms": 272.79,
      "p50_duration_ms": 245.91,
      "p95_duration_ms": 446.79,
      "p99_duration_ms": 469.53,
      "max_duration_ms": 485.7,
      "last_called_at": 1775241265.46036,
      "first_called_at": 1775165996.83268,
      "days_since_last_call": 0
    }
  ]
}
```

As we said, we can filter by status: `/lens/report?status={active | cold | dead | never_called}` or by days: `/lens/report?days=7`

We also have `/lens/report/top` to get the top endpoints by calls.

```json
{
  "generated_at": 1775244158.6899,
  "window_days": 7,
  "endpoints": [
    {
      "path": "/items",
      "method": "GET",
      "status": "active",
      "total_calls": 26,
      "error_4xx_count": 0,
      "error_5xx_count": 0,
      "error_rate_pct": 0,
      "success_rate_pct": 100,
      "avg_duration_ms": 272.79,
      "p50_duration_ms": 245.91,
      "p95_duration_ms": 446.79,
      "p99_duration_ms": 469.53,
      "max_duration_ms": 485.7,
      "last_called_at": 1775241265.46036,
      "first_called_at": 1775165996.83268,
      "days_since_last_call": 0
    },
    {
      "path": "/users/{user_id}",
      "method": "GET",
      "status": "active",
      "total_calls": 23,
      "error_4xx_count": 2,
      "error_5xx_count": 8,
      "error_rate_pct": 43.48,
      "success_rate_pct": 56.52,
      "avg_duration_ms": 86.2,
      "p50_duration_ms": 66.89,
      "p95_duration_ms": 167.1,
      "p99_duration_ms": 171.65,
      "max_duration_ms": 184.45,
      "last_called_at": 1775241273.30783,
      "first_called_at": 1775165996.89715,
      "days_since_last_call": 0
    },
    {
      "path": "/",
      "method": "GET",
      "status": "active",
      "total_calls": 22,
      "error_4xx_count": 0,
      "error_5xx_count": 0,
      "error_rate_pct": 0,
      "success_rate_pct": 100,
      "avg_duration_ms": 0.8,
      "p50_duration_ms": 0.62,
      "p95_duration_ms": 1.22,
      "p99_duration_ms": 2.22,
      "max_duration_ms": 2.69,
      "last_called_at": 1775241252.63773,
      "first_called_at": 1775165996.62768,
      "days_since_last_call": 0
    }
  ]
}
```

And finally, we also have: `/lens/report/dead` to get the dead endpoints.

```json
{
  "generated_at": 1775244273.47241,
  "dead_endpoint_count": 0,
  "endpoints": [
    {
      "path": "/",
      "method": "GET",
      "status": "active",
      "total_calls": 22,
      "error_4xx_count": 0,
      "error_5xx_count": 0,
      "error_rate_pct": 0,
      "success_rate_pct": 100,
      "avg_duration_ms": 0.8,
      "p50_duration_ms": 0.62,
      "p95_duration_ms": 1.22,
      "p99_duration_ms": 2.22,
      "max_duration_ms": 2.69,
      "last_called_at": 1775241252.63773,
      "first_called_at": 1775165996.62768,
      "days_since_last_call": 0
    }
  ]
}
```

---

## ⚙️ Advanced Configuration

| Parameter | Default | Description |
|---|---|---|
| `db_path` | `"lens.db"` | Path to SQLite file. Use `":memory:"` for ephemeral testing. |
| `ttl_days` | `None` | Days to keep records. Older records are deleted & DB is vacuumed. |
| `security_enabled` | `False` | Whether to require `report_key` for dashboard/API access. |
| `report_key` | `None` | The secret string used for authentication. |
| `report_path` | `"/lens/report"` | Custom base path for the API reports. |
| `ignore_unmapped` | `True` | If True, 404s to paths not in your FastAPI app won't be recorded. |
| `flush_interval` | `5.0` | Seconds between batch writes to the database. |
| `max_batch_size` | `100` | Flush immediately if this many records are queued. |

---

## Architecture

`fastapi-lens` is designed to be **non-blocking**. Your request path is never slowed down.

Your FastAPI app
│
├── LensMiddleware (Starlette BaseHTTPMiddleware)
│   ├── Intercepts every request (non-blocking)
│   ├── Resolves route template  (/users/42 → /users/{user_id})
│   ├── Pushes to asyncio.Queue  (never slows the request)
│   └── Background task flushes queue → SQLiteStorage (WAL mode)
│
└── /lens/dashboard  (The Premium UI)
└── /lens/report     (JSON APIRouter)

1. **Intercept**: Middleware records timestamps using `time.perf_counter()`.
2. **Queue**: Data is pushed to an `asyncio.Queue` (O(1) operation).
3. **Batch**: A background task drains the queue and writes to SQLite in batches using **WAL mode** for high concurrency.
4. **Cleanup**: A 24-hour cycle task runs `DELETE` and `VACUUM` based on your `ttl_days`.

---

## Contributing 🤝

Contributions are what make the open-source community an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**.

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

Follow the steps in the [CONTRIBUTING.md](https://github.com/AVR216/fastapi-lens/v0.3.2/CONTRIBUTING.md) file.

---

## 📄 License

Distributed under the **MIT License**. See `LICENSE` for more information.