# Operations

## CI / Tests
Run all backend linting, type checks, and tests:
```bash
./scripts/ci.sh
```

## Logging
You can see information about DCA and TP status in `statistics.log`. Other logs
are available as well (for exchange, controller, monitoring, etc.).

### Debug
Start Moonwalker with:
```bash
./run.sh start -d
```

### Trace
Start Moonwalker with:
```bash
./run.sh start -t
```
or:
```bash
./run.sh start --trace
```

### Log Level Environment Variable
You can override log level directly with `MOONWALKER_LOG_LEVEL`:
- `TRACE`
- `DEBUG`
- `INFO`
- `WARNING`
- `ERROR`
- `CRITICAL`

Examples:
```bash
MOONWALKER_LOG_LEVEL=INFO ./run.sh start
MOONWALKER_LOG_LEVEL=TRACE ./run.sh start
```

Priority order:
1. `MOONWALKER_LOG_LEVEL` (if set)
2. `MOONWALKER_DEBUG=True` (set by `./run.sh start --debug`)
3. Default `INFO`

## Statistics API
- Canonical endpoint: `/statistic/profit-overall/timeline`
