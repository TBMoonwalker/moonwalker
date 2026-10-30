# Documentation

Moonwalker runs as a single-node, single-instance application. Multiple
dashboard clients can connect to that instance.

## Tutorials

- [Compare accumulation strategies before starting a holding](tutorial-accumulation-backtest.md)

## Operator guides

- [Start, manage and close an accumulation holding](howto-operate-accumulation.md)
- [Recover an accumulation holding](howto-recover-accumulation.md)
- [Configuration and settings reference](configuration.md)
- [Expert safeguards and safety-order sizing modes](dynamic-so.md)
- [AI Trust local calibration](ai-trust.md)
- [Signal plugins](signals.md)
- [Strategy Builder](strategies.md)
- [Telegram monitoring](monitoring.md)
- [Operations, backups, logs, and dashboard streams](operations.md)
- [Deny a symbol from future entries](designs/denylist-symbol-from-open-trade.md)
- [Move accumulation coins to a hardware wallet](designs/accumulation-hardware-wallet-custody.md)

## API and development

- [API and WebSocket reference](api.md)
- [Developer documentation, architecture ownership, and documentation policy](development.md)
- [Accumulation mode: setup, strategy, manual exits, recovery and replay](accumulation.md)
- [Dashboard history loading](designs/delta-loading.md)
- [Dependency management and supply-chain policy](dependencies.md)
- [Update dependencies after supply-chain review](howto-update-dependencies.md)
- [Why accumulation has its own lifecycle](explanation-accumulation-lifecycle.md)
- [Product record](../PRODUCT.md)
- [Design system](../DESIGN.md)
- [Project backlog](../TODOS.md)
- [Release notes](../CHANGELOG.md)

This index describes maintained documentation. Temporary agent plans and local
audit reports are archived separately; their durable decisions and outstanding
work are retained in the developer notes and backlog.


For shared exchange execution ownership, see [development](development.md#shared-order-execution-ownership).
The [accumulation lifecycle](explanation-accumulation-lifecycle.md) explains the
mode-specific accounting boundary and CSV purchase history; the
[API reference](api.md) documents the additive trade-history fields.
