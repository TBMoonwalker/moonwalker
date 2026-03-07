# Moonwalker
## Summary
Moonwalker can be used to trade on your exchange directly using various signal plugins. It is also capable to create (dynamic) DCA deals.

## Disclaimer
**Moonwalker is meant to be used for educational purposes only. Use with real funds at your own risk**

## Prerequisites
- A Linux server with a static ip address
- Configured API access on your exchange
- Python >= 3.11
- Node.js (for the frontend build)

### Run Script (Recommended)
1. Copy `config.ts.example` to `config.ts` and set `MOONWALKER_API_HOST` and `MOONWALKER_API_PORT`.
2. Start everything with `./run.sh start -p "port"`.
   - Debug logs: `./run.sh start --debug`
   - Trace logs: `./run.sh start --trace`
3. Stop with `./run.sh stop`.

The script builds the Vue frontend, copies assets into the backend, creates a Python venv, installs backend deps, and starts the Quart app. Logs go to `run.log`.

### TA-Lib dependency
You also need to install the ta-lib library for your OS. Please see: https://ta-lib.org/install/#linux-debian-packages

## Documentation
- Configuration and full key reference: `docs/configuration.md`
- Monitoring (Telegram): `docs/monitoring.md`
- Dynamic SO details and formulas: `docs/dynamic-so.md`
- Signal plugin setup (SymSignals, ASAP): `docs/signals.md`
- CI, tests, and logging: `docs/operations.md`
