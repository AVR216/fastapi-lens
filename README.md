# fastapi-lens 🔍

> API usage intelligence for FastAPI — lightweight middleware that tells you which endpoints are thriving, which are cold, and which are dead. Now with a **Premium HTML Dashboard**.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com)

---

## Why fastapi-lens?

You build APIs. Over time, routes accumulate. Some are called thousands of times a day. Others haven't been touched in months. You don't know which is which — until now.

`fastapi-lens` is a **zero-infrastructure** solution: no Datadog, no Prometheus, no external services. Just a SQLite file, a JSON API, and a beautiful **real-time dashboard**.

---

## New in v0.2.0: The Lens Dashboard 📊

Visualizing your API health has never been easier. `fastapi-lens` now includes a built-in, premium HTML dashboard with:
- **Real-time Metrics**: Traffic, success rates, and active route counts.
- **Advanced Latency**: P50, P95, and P99 percentiles for every endpoint.
- **Health Indicators**: Visual badges for `active`, `cold`, and `dead` routes.
- **Error Tracking**: Visual breakdown of 4xx and 5xx errors per endpoint.

Access it at: `/lens/dashboard`

---

## Installation

```bash
pip install fastapi-lens
```

---

## Quickstart

```python
from fastapi import FastAPI
from fastapi_lens import LensMiddleware, LensConfig

app = FastAPI()

app.add_middleware(
    LensMiddleware,
    config=LensConfig(
        security_enabled=True,         # Protects dashboard and API
        report_key="your-secret-key",  # Your access key
        db_path="lens.db",             # SQLite file path
    ),
)

@app.get("/items")
def list_items():
    return [{"id": 1}]
```

### Accessing your Data
- **Dashboard**: `http://localhost:8000/lens/dashboard?report_key=your-secret-key`
- **JSON API**: `GET /lens/report` with header `X-Lens-Key: your-secret-key` (or query param `?report_key=...`)

---

## Report endpoints

| Endpoint | Description |
|---|---|
| `GET /lens/dashboard` | **The Visual Dashboard** (SPA) |
| `GET /lens/report` | Full JSON report — all endpoints with advanced metrics |
| `GET /lens/report/top` | Most called endpoints in the current window |
| `GET /lens/report/dead` | Endpoints with no calls in 30+ days |

---

## Advanced Metrics

Unlike basic loggers, `fastapi-lens` provides real performance insights:
- **Percentiles**: Accurate P50, P95, and P99 latency tracking.
- **Error Segregation**: Count 4xx and 5xx errors separately to distinguish between client and server issues.
- **Success Rate**: Automatic percentage calculation based on non-5xx responses.

---

## Configuration

```python
LensConfig(
    db_path="lens.db",           # SQLite path. Use ":memory:" for tests
    security_enabled=False,      # Use True to require report_key
    report_key="lens-secret",    # The key used for Auth
    report_path="/lens/report",  # Customize the API path
    ignore_unmapped=True,        # Ignore requests to routes not in your app
    exclude_paths={              # Always excluded from tracking
        "/lens/report", "/lens/dashboard", "/docs", "/favicon.ico"
    },
    exclude_methods={"HEAD", "OPTIONS"},
    flush_interval=5.0,          # Seconds between batch writes
    max_batch_size=100,          # Flush early if queue exceeds this
    dead_threshold_days=30,      # Days without calls = "dead"
    cold_threshold_days=7,       # Days without calls = "cold"
)
```

---

## Architecture

```
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
```

**Design principles:**
- **Non-blocking**: the request path only does a `queue.put_nowait()`.
- **Batch writes**: SQLite writes are asynchronous and batched.
- **Noise Reduction**: Automatically filters common noise (favicon, robots.txt) and unmapped paths.
- **Zero mandatory deps**: only uses FastAPI/Starlette built-ins.

---

## Contributing

Contributions are welcome! Please see [Contributing](https://github.com/AVR216/fastapi-lens/blob/main/CONTRIBUTING.md) for local setup and testing guidelines.

---

## License

MIT