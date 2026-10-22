"""ASAP/CSV entry adapters; neither path submits a base order or converts a trade."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, replace
from typing import Any

import ccxt.async_support as ccxt
import model
from helper.async_completion import finish_before_cancellation
from service import signal_runtime
from service.accumulation_commands import AccumulationCommandResult
from service.accumulation_contracts import AccumulationStateError
from service.accumulation_exchange import (
    AccumulationExchangeAdapter,
    accumulation_account_scope,
)
from service.accumulation_import import AccumulationImport, parse_accumulation_csv
from service.accumulation_lifecycle import (
    AccumulationLifecycleService,
    AccumulationReadiness,
    AccumulationValidationRequest,
    _result,
)
from service.accumulation_staged_entry import StagedEntryCommand, stage_entry_command
from service.order_requests import normalize_order_symbol
from service.strategy_runtime import load_accumulation_strategy_version
from service.trading_controls import is_global_trading_paused


@dataclass(frozen=True)
class AccumulationEntryResult:
    """Per-symbol staging outcome, including an explicit validation retry identity."""

    symbol: str
    operation_id: str | None
    reason: str


class AccumulationEntryService:
    """Use only from the gated runtime or with a simulated exchange in tests."""

    def __init__(
        self, adapter: AccumulationExchangeAdapter, notify: Callable[[str], None]
    ) -> None:
        self.adapter = adapter
        self.lifecycle = AccumulationLifecycleService(adapter.readiness)
        self.notify = notify

    def _config(self, source: str) -> dict[str, Any]:
        config = self.adapter.config()
        if config.get("trade_mode") != "accumulation" or config.get("signal") != source:
            raise AccumulationStateError(
                "Accumulation entry requires its selected ASAP/CSV plugin."
            )
        if is_global_trading_paused(config):
            raise AccumulationStateError("Trading is paused.")
        version = config.get("accumulation_strategy_version_id")
        if type(version) is not int or version < 1:
            raise AccumulationStateError(
                "Select an exact compatible accumulation strategy version."
            )
        maximum = config.get("max_bots")
        if type(maximum) is not int or maximum < 1:
            raise AccumulationStateError("A positive managed-symbol limit is required.")
        return config

    async def asap(self) -> tuple[AccumulationEntryResult, ...]:
        """Register explicit fixed symbols; the strategy decides the first purchase."""
        config = self._config("asap")
        raw = config.get("symbol_list")
        if not isinstance(raw, str) or not raw.strip() or "http" in raw.lower():
            raise AccumulationStateError(
                "Accumulation ASAP requires a fixed symbol list."
            )
        symbols = sorted(
            {
                normalize_order_symbol(item.strip())
                for item in raw.split(",")
                if item.strip()
            }
        )
        if any(
            len(symbol.split("/")) != 2
            or symbol.split("/")[1] != config["currency"]
            or ":" in symbol
            for symbol in symbols
        ):
            raise AccumulationStateError(
                "ASAP symbols must use the configured spot quote."
            )
        await load_accumulation_strategy_version(
            config["accumulation_strategy_version_id"]
        )
        return tuple(
            [await self._enter(symbol, "asap", config, None) for symbol in symbols]
        )

    async def csv(self, content: str) -> tuple[AccumulationEntryResult, ...]:
        """Stage complete declarations before validating and adopting owned inventory."""
        config = self._config("csv_signal")
        imports = parse_accumulation_csv(
            content, config["currency"], now_ms=self.adapter.clock_ms()
        )
        await load_accumulation_strategy_version(
            config["accumulation_strategy_version_id"]
        )
        return tuple(
            [await self._enter(item.symbol, "csv", config, item) for item in imports]
        )

    async def _finish_before_cancellation(
        self, operation: Coroutine[Any, Any, AccumulationCommandResult]
    ) -> AccumulationCommandResult:
        """Let bounded entry validation release its DB resources before stopping.

        Cancelling Tortoise's SQLite transaction entry after it acquires the
        connection lock can strand that lock. Keep each operation's transaction
        entry/exit in one task. Readiness network reads have their own timeouts;
        this boundary never places an exchange order.
        """
        return await finish_before_cancellation(
            operation, name="accumulation:entry-validation"
        )

    async def _stage_activation(self, **kwargs: Any) -> AccumulationCommandResult:
        return await self._finish_before_cancellation(
            self.lifecycle.stage_activation(**kwargs)
        )

    async def _enter(
        self,
        symbol: str,
        source: str,
        config: dict[str, Any],
        imported: AccumulationImport | None,
    ) -> AccumulationEntryResult:
        scope = accumulation_account_scope(config)
        identity = json.dumps(
            [scope, symbol, source, imported.to_dict() if imported else None],
            sort_keys=True,
        )
        operation_id = "entry-" + hashlib.sha256(identity.encode()).hexdigest()[:56]
        # Share ordinary signal admission's reservation boundary. No exchange reads
        # occur while this lock is held; validating activations already occupy slots.
        async with signal_runtime._PENDING_ADMISSION_LOCK:
            if self.adapter.config() != config:
                raise AccumulationStateError("Entry configuration changed.")
            existing = await model.AccumulationActivation.get_or_none(symbol=symbol)
            if existing is not None:
                if existing.account_scope != scope:
                    raise AccumulationStateError(
                        "Symbol belongs to another account scope."
                    )
                prior = await model.AccumulationLifecycleOperation.get_or_none(
                    operation_id=operation_id, activation=existing
                )
                if source == "csv" and prior is None:
                    raise AccumulationStateError(
                        "CSV declaration changed; explicit staged correction is required."
                    )
                return AccumulationEntryResult(
                    symbol,
                    prior.operation_id if prior else None,
                    "STOPPED" if existing.state == "stopped" else "ALREADY_REGISTERED",
                )
            occupied = (
                set(await signal_runtime.get_active_open_symbols())
                | signal_runtime._PENDING_ADMISSION_SYMBOLS
            )
            if symbol in occupied:
                raise AccumulationStateError("Symbol is already managed or reserved.")
            if len(occupied) >= config["max_bots"]:
                return AccumulationEntryResult(symbol, None, "WAIT_CAPACITY")
            staged = await self._stage_activation(
                symbol=symbol,
                account_scope=scope,
                strategy_version_id=config["accumulation_strategy_version_id"],
                source=source,
                operation_id=operation_id,
                imported_inventory=imported,
            )
        try:
            await self._complete(staged.operation_id, scope, config)
        except (AccumulationStateError, ccxt.BaseError, TimeoutError, OSError):
            # Keep the durable declaration paused. Repeated plugin polls do not
            # retry a failed ownership check; the operator must request validation.
            return AccumulationEntryResult(symbol, operation_id, "WAIT_VALIDATION")
        self.notify(symbol)
        return AccumulationEntryResult(symbol, operation_id, "ENABLED")

    async def _complete(
        self, operation_id: str, scope: str, config: dict[str, Any]
    ) -> AccumulationCommandResult:
        return await self._finish_before_cancellation(
            self._validate_entry(operation_id, scope, config)
        )

    async def _validate_entry(
        self, operation_id: str, scope: str, config: dict[str, Any]
    ) -> AccumulationCommandResult:
        """Bind validation to the entry settings, including changes before warmup."""

        async def validate(
            request: AccumulationValidationRequest,
        ) -> AccumulationReadiness:
            if self.adapter.config() != config:
                raise AccumulationStateError(
                    "Entry configuration changed before validation."
                )
            ready = await self.adapter.readiness(request)

            async def commit() -> None:
                if self.adapter.config() != config:
                    raise AccumulationStateError(
                        "Entry configuration changed before adoption."
                    )
                if ready.validate_commit is None:
                    raise AccumulationStateError(
                        "Entry ownership commit validation is missing."
                    )
                await ready.validate_commit()

            return replace(ready, validate_commit=commit)

        return await AccumulationLifecycleService(validate).complete_rebase(
            operation_id, account_scope=scope
        )

    async def submit_staged(self, payload: dict[str, Any]) -> AccumulationCommandResult:
        """Correct, abandon or explicitly validate the entry shown to the operator."""
        command = StagedEntryCommand.from_dict(payload, now_ms=self.adapter.clock_ms())
        scope = accumulation_account_scope(self.adapter.config())
        result = await stage_entry_command(command, account_scope=scope)
        self.notify(command.symbol)
        if command.action != "retry_entry" or result.status != "pending":
            return result
        operation = await model.AccumulationLifecycleOperation.get(
            operation_id=command.operation_id
        )
        source = json.loads(operation.request_json)["source"]
        try:
            config = self._config("csv_signal" if source == "csv" else "asap")
            result = await self._complete(command.operation_id, scope, config)
        except (AccumulationStateError, ccxt.BaseError, TimeoutError, OSError):
            # A lost response, competing correction or failed readiness check must
            # report the journal's outcome, never a stale optimistic result.
            await operation.refresh_from_db()
            return _result(operation)
        self.notify(command.symbol)
        return result
