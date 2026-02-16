# AGENTS.md

This file provides guidance to agentic coding agents (such as Claude Code) when working with code in this repository.

## Build, Lint, and Test Commands

### Mandatory CI Check
- After every code change, run CI from the scripts directory directly: `cd scripts && ./ci.sh`

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
6. Starts the Quart application

## Project Overview

Moonwalker is a cryptocurrency trading bot that connects to exchanges (like Binance) and executes trades based on signals from various plugins. It supports:
- Dynamic DCA (Dollar Cost Averaging) deals
- Multiple signal plugins (ASAP, SymSignals)
- Various trading strategies (EMA cross, Bbands cross, Ichimoku, etc.)
- Autopilot mode for automatic portfolio management
- REST API and WebSocket interface
- Web-based UI built with Vue.js

## Architecture

### Backend (Python - Quart/Async)
The backend is a Python application using Quart (async Flask) framework with the following structure:

**Main Entry Point:** `backend/app.py`
- Initializes configuration, database, signal plugins, watcher, and housekeeper
- Sets up Quart app with blueprints from controller
- Starts background tasks for watching symbols/tickers and running signal plugins

**Key Components:**
1. **Controller** (`backend/controller/`)
   - REST API endpoints for frontend interaction
   - WebSocket endpoints for real-time updates
   - Handles orders, trades, statistics, and data endpoints

2. **Services** (`backend/service/`)
   - `database.py` - Tortoise ORM database connection and management
   - `watcher.py` - Monitors exchange tickers and symbol signals via WebSocket
   - `housekeeper.py` - Cleans up old ticker data and manages database maintenance

3. **Signal Plugins** (`backend/signals/`)
   - `asap.py` - Signal plugin for ASAP signals
   - `sym_signals.py` - Signal plugin for 3CQS SymSignals
   - Each plugin implements `SignalPlugin` class with `run()` and `shutdown()` methods

4. **Strategies** (`backend/strategies/`)
   - Trading strategy implementations (EMA cross, BBands cross, Ichimoku, etc.)
   - Each strategy is a module with indicator calculation logic

5. **Models** (`backend/model/`)
   - Tortoise ORM data models for trades, tickers, open trades, listings
   - Database schema definitions

6. **Helper** (`backend/helper/`)
   - `config.py` - Configuration loading from config.ini
   - `logger.py` - Logging factory with different log levels
   - `utils.py` - Utility functions

### Frontend (Vue.js)
The frontend is a Vue.js application built with Vite:
- Location: `frontend/`
- Built assets are served by the backend at `/static/`
- Uses Naive UI component library
- Includes Pinia for state management
- Provides trading dashboard, statistics, and configuration interface

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
6. Starts the Quart application

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

The app runs on port 8120 (configurable in config.ini) by default.

### Configuration

Main configuration file: `config.ini` (based on `config.ini.example`)

Key configuration sections:
- **general**: Timezone, debug mode, port
- **signal**: Signal plugin selection and settings
- **exchange**: Exchange API keys, currency, dry-run mode
- **dca**: DCA settings, max bots, base order size, take profit, stop loss
- **autopilot**: Autopilot mode configuration



## Testing

The project uses standard Python and JavaScript testing approaches:

**Python testing:**
- No explicit test files in repository (test*.py files are gitignored)
- Use pytest for testing: `pip install pytest`

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
