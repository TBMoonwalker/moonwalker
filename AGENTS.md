# AGENTS.md

This file provides guidance to agentic coding agents (such as Claude Code) when working with code in this repository.

## Build, Lint, and Test Commands

### Mandatory CI Check
- After every code change, run CI from the scripts directory directly: `cd scripts && ./ci.sh`

### Dependency Hygiene (Mandatory)
- Run dependency outdated checks at least weekly and before each release candidate.
- Backend outdated check: `./.venv/bin/python -m pip list --outdated --format=json`
- Frontend outdated check: `cd frontend && npm outdated --json`
- If updates are found, record them in the task summary and explicitly classify each as:
  - patch/minor (safe candidate)
  - major (needs compatibility review)
- Apply dependency updates only in dedicated dependency PRs/changesets unless the task explicitly asks for version upgrades.

### Backend (Python)
- **Run application:** `cd backend && python app.py` or use the `./run.sh` script
- **Install dependencies:** `cd backend && pip install -r requirements.txt`
- **Format code:** `black backend/` (Black is configured with default settings)
- **Lint code:** `ruff check backend/`
- **Type check:** `mypy backend/`
- **Import sort:** `isort backend/`
- **Run tests:** `pytest` (when tests are added)

Note: Test files (test*.py) are gitignored in the repository. Use pytest for testing.

### Frontend (Vue.js)
- **Install dependencies:** `cd frontend && npm install`
- **Build:** `cd frontend && npm run build`
- **Development server:** `cd frontend && npm run dev`
- **Type check:** `cd frontend && npm run type-check`
- **Run tests:** `cd frontend && npm test` (if configured)

### Full Project Build
Use the run.sh script to build and run the entire project:
```bash
./run.sh
```

This script:
1. Copies config files to backend and frontend
2. Installs frontend dependencies and builds Vue app
3. Copies built assets to backend/static/
4. Creates Python virtual environment
5. Installs Python dependencies
6. Starts the Litestar application

## Project Overview

Moonwalker is a cryptocurrency trading bot that connects to exchanges (like Binance) and executes trades based on signals from various plugins. It supports:
- Dynamic DCA (Dollar Cost Averaging) deals
- Multiple signal plugins (ASAP, SymSignals, CSV Signal)
- Various trading strategies (EMA cross, Bbands cross, Ichimoku, etc.)
- Autopilot mode for automatic portfolio management
- REST API and WebSocket interface
- Web-based UI built with Vue.js

## Deployment Model

- Moonwalker is intentionally designed to run as a **single-node, single-instance** application.
- A running Moonwalker instance owns its own database, configuration, watcher/runtime state, and trading engine.
- It is normal for **multiple dashboard clients** to connect to the same instance concurrently (for example desktop, mobile phone, or multiple browser tabs).
- Separate Moonwalker installations are **intentionally isolated** from each other. Do not assume clustering, leader election, cross-instance coordination, or shared state between installations unless a task explicitly adds that.
- When reviewing architecture or proposing changes, optimize for **single-instance reliability and safe multi-client access**, not distributed-system scale by default.

## Review And Code Smell Analysis

- When the user asks for a **review**, **engineering analysis**, **project analysis**, or **code smell** check, treat the standards in this file as **review criteria**, not only as implementation guidance.
- Do not stop at architecture or correctness findings alone. Also inspect lower-severity hygiene categories that are explicitly covered by this file.
- If a review category is checked and no issues are found, say that explicitly instead of silently skipping the category.

### Code Smell Review Checklist

When performing a code smell analysis or engineering-style review, inspect and report findings across all of these categories:

- Architecture and responsibility boundaries
- Hidden coupling and mutable shared state
- API design and unsafe behaviors
- Error handling and exception boundaries
- Async I/O discipline and event-loop safety
- Logging quality and logging safety
- Type safety and schema clarity
- Test coverage gaps and CI enforcement
- Documentation drift
- Performance hotspots that matter for Moonwalker's single-instance deployment model

Logging review must explicitly include:

- f-string logging or other eager string interpolation instead of parameterized logging
- inconsistent exception logging patterns
- use of `exc_info=True` where stack traces are needed
- possible logging of secrets, credentials, or sensitive payloads
- noisy logging that obscures operational signals

Async I/O review must explicitly include:

- blocking I/O on the event loop (`requests`, file I/O, subprocess waits, `time.sleep`, etc.)
- synchronous I/O hidden behind `asyncio.to_thread()` or executors when a native async library is already available
- repeated thread offloading in hot paths where async-native I/O would be clearer and cheaper
- any use of sync libraries in async services/plugins must be called out unless there is a documented compatibility reason

## Architecture

### Backend (Python - Litestar/Async)
The backend is a Python application using Litestar with the following structure:

**Main Entry Point:** `backend/app.py`
- Initializes configuration, database, signal plugins, watcher, and housekeeper
- Sets up the Litestar app with route handlers from the controller package
- Starts background tasks for watching symbols/tickers and running signal plugins

**Key Components:**
1. **Controller** (`backend/controller/`)
   - REST API endpoints for frontend interaction
   - WebSocket endpoints for real-time updates
   - Handles orders, trades, statistics, and data endpoints

2. **Services** (`backend/service/`)
   - `config.py` - Singleton configuration manager backed by DB (`AppConfig`), hot-reload via Redis pub/sub
   - `exchange.py` - Async CCXT wrapper: buy/sell lifecycle, precision, balance, retry logic
   - `dca.py` - Core DCA engine: processes tickers, evaluates TP/SO triggers, places orders
   - `watcher.py` - Real-time OHLCV/trade streaming via CCXT Pro WebSockets with auto-reconnect
   - `trades.py` - Trade persistence layer: CRUD for open/closed trades, aggregation
   - `orders.py` - Order execution and management
   - `database.py` - Tortoise ORM database connection and management
   - `housekeeper.py` - Periodic cleanup of old ticker data and uPNL history
   - `statistic.py` - Portfolio stats, uPNL tracking, profit calculations
   - `autopilot.py` - Dynamic trading parameter adjustment based on locked-fund thresholds
   - `monitoring.py` - Telegram notifications via Telethon for buy/sell events
   - `indicators.py` - TA-Lib wrappers for EMA, RSI, Bollinger Bands, Ichimoku, etc.
   - `signal.py` - Signal plugin loader and lifecycle management
   - `data.py` - Data endpoints and helpers for the controller layer
   - `filter.py` - Symbol filtering (volume, market cap, pair age)
   - `ath.py` - All-Time-High lookups with caching for dynamic SO scaling
   - `redis.py` - Redis client setup and pub/sub helpers
   - `strategy_capability.py` - Strategy availability validation

3. **Signal Plugins** (`backend/signals/`)
   - `asap.py` - Signal plugin for ASAP signals
   - `csv_signal.py` - Signal plugin for importing open trades from CSV source
   - `sym_signals.py` - Signal plugin for 3CQS SymSignals
   - Each plugin implements `SignalPlugin` class with `run()` and `shutdown()` methods

4. **Strategies** (`backend/strategies/`)
   - Trading strategy implementations (EMA cross, BBands cross, Ichimoku, etc.)
   - Each strategy is a module with indicator calculation logic

5. **Models** (`backend/model/`)
   - 9 Tortoise ORM models: `AppConfig`, `AthCache`, `Autopilot`, `Trades`, `OpenTrades`, `ClosedTrades`, `Tickers`, `Listings`, `UpnlHistory`
   - Database: SQLite (configurable via `MOONWALKER_DB_URL`)

6. **Helper** (`backend/helper/`)
   - `logger.py` - Logging factory with different log levels
   - `utils.py` - Utility functions
   - `async_cache.py` - Async-compatible caching decorator

### Frontend (Vue.js)
The frontend is a Vue.js application built with Vite:
- Location: `frontend/`
- Built assets are served by the backend at `/static/`
- Uses Naive UI component library
- Includes Pinia for state management
- Provides trading dashboard, statistics, and configuration interface

## Design System
Always read DESIGN.md before making any visual or UI decisions.
All font choices, colors, spacing, and aesthetic direction are defined there.
Do not deviate without explicit user approval.
In QA mode, flag any code that doesn't match DESIGN.md.

## Development Setup

### Prerequisites
- Python > 3.10.x
- Node.js (for frontend)
- TA-Lib (install separately - see https://ta-lib.org/install/)

### Installation

1. **Backend dependencies:**
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

2. **Frontend dependencies:**
   ```bash
   cd frontend
   npm install
   ```

3. **TA-Lib** (required for technical indicators):
   - Follow OS-specific instructions at https://ta-lib.org/install/

### Running the Application

**Option 1: Using run.sh script**
```bash
./run.sh
```
This script:
1. Copies config files to backend and frontend
2. Installs frontend dependencies and builds Vue app
3. Copies built assets to backend/static/
4. Creates Python virtual environment
5. Installs Python dependencies
6. Starts the Litestar application

**Option 2: Manual setup**
```bash
# Copy example configs
cp config.ini.example config.ini
cp config.ts.example frontend/src/config.ts

# Build frontend
cd frontend
npm run build
cd ..

# Copy built assets to backend
cp -r frontend/dist/assets backend/static/
cp frontend/dist/index.html backend/templates/

# Run backend
cd backend
python app.py
```

The app runs on port 8130 (configurable via `MOONWALKER_PORT` env var or `./run.sh start -p <port>`) by default.

### Configuration

Runtime configuration is **DB-persisted** (`AppConfig` table) and managed via the `Config` singleton in `backend/service/config.py`. Changes propagate across processes via **Redis pub/sub**. The web UI provides a visual config editor; all ~60 keys are documented in `docs/configuration.md`.

Key configuration sections:
- **general**: Timezone, debug mode, port
- **signal**: Signal plugin selection and settings
- **exchange**: Exchange API keys, currency, dry-run mode
- **dca**: DCA settings, max bots, base order size, take profit, stop loss
- **autopilot**: Autopilot mode configuration



## Testing

The project uses standard Python and JavaScript testing approaches:

**Python testing:**
- `backend/tests/` contains regression coverage for config, data/history sync,
  DCA, exchange execution, filters, monitoring, orders, signal plugins, stats,
  strategies, trades, watcher runtime, websocket fan-out, and related services.
- Run tests: `cd scripts && ./ci.sh` (runs pytest with all checks) or
  `pytest backend/tests/` directly

**Frontend testing:**
- Vue Test Utils for component testing
- Run tests: `cd frontend && npm test` (if configured)

## Key Files

- `backend/app.py` - Main application entry point
- `backend/controller/` - API endpoints
- `backend/service/watcher.py` - Ticker and signal watching
- `backend/service/housekeeper.py` - Database maintenance
- `backend/signals/` - Signal plugin implementations
- `backend/strategies/` - Trading strategy implementations
- `frontend/src/` - Vue.js frontend source
- `config.ini.example` - Configuration template
- `run.sh` - Build and run script

## Python Development Standards

### Supported Python Versions

- Target **Python 3.11+** unless stated otherwise.
- Use standard library features when available before adding dependencies.
- Avoid deprecated APIs and syntax.

### Code Style & Formatting

- Follow **PEP 8**.
- Use **Black** for formatting (default settings).
- Maximum line length: **88 characters**.
- Indentation: **4 spaces**, never tabs.
- One logical statement per line.

Example:
```python
def calculate_total(prices: list[float]) -> float:
    return sum(prices)
```

### Naming Conventions

| Element | Convention |
|-------|------------|
| Modules | `snake_case.py` |
| Packages | `snake_case` |
| Classes | `PascalCase` |
| Functions | `snake_case` |
| Variables | `snake_case` |
| Constants | `UPPER_SNAKE_CASE` |
| Private Members | `_leading_underscore` |

Avoid abbreviations unless they are widely understood.

---

### Type Hints & Static Typing

- Use **type hints by default**.
- Prefer built‑in generics (`list[str]`) over `typing.List`.
- Use `Optional[T]` or `T | None` explicitly.
- Validate types with **mypy** or **Pyright**.

Example:
```python
from typing import Iterable

def mean(values: Iterable[float]) -> float | None:
    values = list(values)
    if not values:
        return None
    return sum(values) / len(values)
```

---

### Docstrings & Comments

- Follow **PEP 257**.
- Use **Google‑style docstrings**.
- Docstrings are required for all public modules, classes, and functions.

Example:
```python
def normalize_username(username: str) -> str:
    """Normalize a username for consistent comparison.

    Args:
        username: Raw user‑provided name.

    Returns:
        A normalized, lowercase username.
    """
    return username.strip().lower()
```

**Comments**
- Explain *why*, not *what*.
- Avoid redundant or obvious comments.

---

### Functions & Methods

- Keep functions small and focused.
- Prefer pure functions when possible.
- Avoid hidden side effects.
- Explicit is better than clever.

Bad:
```python
def process(x): return x.strip().lower() if x else None
```

Good:
```python
def process(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip().lower()
```

---

### Classes & Design

- Follow **Single Responsibility Principle**.
- Prefer composition over inheritance.
- Keep public APIs small and explicit.
- Use `@dataclass` when appropriate.

Example:
```python
from dataclasses import dataclass

@dataclass(frozen=True)
class User:
    id: int
    email: str
```

---

### Error Handling

- Catch **specific exceptions only**.
- Never use bare `except:`.
- Raise meaningful, domain‑specific errors.

Example:
```python
class ConfigError(Exception):
    pass


def load_config(path: str) -> dict:
    try:
        with open(path) as file:
            return json.load(file)
    except FileNotFoundError as exc:
        raise ConfigError(f"Missing config: {path}") from exc
```

---

### Immutability & Constants

- Use constants for fixed values.
- Prefer immutable data structures.

```python
MAX_RETRIES = 3
SUPPORTED_FORMATS = ("json", "yaml")
```

---

### Imports & Modules

- Order imports:
  1. Standard library
  2. Third‑party
  3. Local application
- One import per line.
- Avoid wildcard imports.

Example:
```python
import json
from pathlib import Path

import requests

from app.settings import Settings
```

---

### Logging

- Use the `logging` module.
- Never use `print` for production code.
- Do not log secrets or personal data.

```python
import logging

logger = logging.getLogger(__name__)
logger.info("Job started")
```

---

### Asynchronous Code

- Use `async`/`await` for I/O‑bound work.
- Do not block the event loop.
- Prefer `asyncio`, `httpx`, and native async libraries.
- Prefer native async I/O over wrapping synchronous libraries in `asyncio.to_thread()`.
- `asyncio.to_thread()` is acceptable for CPU-bound helpers or narrow compatibility bridges, but it is not the preferred end state for network or filesystem I/O when an async-native library already exists.
- During code smell reviews, treat “non-blocking because it runs in a thread” and “async-native I/O” as different quality levels and call out the latter when it matters.

```python
async def fetch_data(client: httpx.AsyncClient, url: str) -> str:
    response = await client.get(url)
    response.raise_for_status()
    return response.text
```

---

### Testing

- Use **pytest**.
- Write unit tests for all critical logic.
- Tests should be deterministic and isolated.

Example:
```python
def test_mean_empty():
    assert mean([]) is None
```

---

### Security Best Practices

- Treat all external input as untrusted.
- Use parameterized queries for databases.
- Store secrets in environment variables or secret managers.
- Avoid hard‑coding credentials.

---

### Performance Guidelines

- Prefer generators for large data sets.
- Use built‑in functions and libraries.
- Optimize for readability first; measure before optimizing.

```python
squares = (x * x for x in range(10_000))
```

---

### Tooling & Automation

Use the following tools:

| Tool | Purpose |
|-----|--------|
| Black | Formatting |
| Ruff | Linting |
| mypy / Pyright | Type checking |
| pytest | Testing |
| isort | Import sorting |

All tools should be configured in `pyproject.toml`.

---

### Dependency Management

- Use virtual environments.
- Prefer **Poetry** or **pip‑tools**.
- Lock dependency versions.
- Avoid unused dependencies.

---

### Version Control Practices

- Write clear, imperative commit messages.
- Keep commits small and focused.
- Use feature branches.
- Require code review before merging.

---

### Pre‑Merge Checklist

Before merging any change:

- [ ] Code formatted (Black)
- [ ] Linting passes
- [ ] Type checks pass
- [ ] Tests added and passing
- [ ] No secrets or sensitive data committed
- [ ] Documentation updated

---

**Guiding Principle:**
> *Code is read far more often than it is written. Optimize for the reader.*
