# Contributing to fastapi-lens 🔍

We're glad you're interested in contributing! This project aims to be a lightweight, zero-dependency observability tool for FastAPI.

## Development Setup

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/yourusername/fastapi-lens.git
    cd fastapi-lens
    ```

2.  **Create a virtual environment**:
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # On Windows: .venv\Scripts\activate
    ```

3.  **Install dependencies**:
    ```bash
    pip install -e .[dev]
    ```

## Running Tests

We use `pytest` for testing. Since we use `asyncio`, we also use `pytest-asyncio`.

```bash
pytest
```

To run with more verbose output:
```bash
pytest -v
```

## Code Quality

Please ensure your code follows the existing style. We use `ruff` for linting.

```bash
ruff check .
```

## Flow for New Features

1.  **Storage**: If adding a new storage backend, implement the `Storage` interface in `fastapi_lens/storage/`.
2.  **Middleware**: Changes to request interception should be made in `fastapi_lens/middleware/lens.py`.
3.  **API**: New report endpoints should be added to the router factory in `fastapi_lens/api/report.py`.
4.  **Dashboard**: The dashboard is a single-file SPA embedded in `report.py` for portability.

## Pull Requests

1.  Create a new branch for your feature or bugfix.
2.  Add tests for any new functionality.
3.  Ensure all tests pass.
4.  Submit a PR with a clear description of the changes.

## Security

If you find a security vulnerability, please do NOT open an issue. Instead, contact the maintainers directly.

---

Thank you for helping make `fastapi-lens` better!
