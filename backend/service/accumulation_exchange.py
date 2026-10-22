"""Read-only exchange evidence and precision preflight for accumulation.

Own a dedicated Exchange instance so unrelated callers cannot replace its client
while a snapshot is being read. Nothing in this module starts a runtime producer.
Credentials come only from the server config provider, never a dashboard label.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from decimal import Decimal, localcontext
from typing import Any

import ccxt.async_support as ccxt
import model
from service.accumulation_budget import (
    AccumulationFundingSnapshot,
    _budget_state,
    capture_accumulation_funding_token,
)
from service.accumulation_contracts import AccumulationStateError, canonical_decimal
from service.accumulation_evaluation import _guard
from service.accumulation_fill import AccumulationFill, decimal_evidence
from service.accumulation_lifecycle import (
    AccumulationReadiness,
    AccumulationValidationRequest,
)
from service.accumulation_portfolio import (
    AccumulationAdmissionInputs,
    AccumulationOffer,
)
from service.accumulation_strategy import (
    AccumulationCandle,
    AccumulationParameters,
    calculate_accumulation_market,
    rebuild_accumulation_observations,
)
from service.exchange import Exchange
from service.exchange_capabilities import require_exchange_placement_capabilities
from service.exchange_risk import get_min_notional_for_market
from service.strategy_runtime import load_accumulation_strategy_version


def accumulation_account_scope(config: dict[str, Any]) -> str:
    """Bind the credential and venue without persisting an API key or secret.

    This is a credential scope, not an exchange user ID: rotating the API key or
    changing venue requires explicit ownership revalidation, even for the same
    wallet. Authentication is verified by the subsequent signed balance request.
    """
    if type(config.get("dry_run")) is not bool or config.get("market") != "spot":
        raise AccumulationStateError(
            "Accumulation requires a validated demo or live spot account."
        )
    if any(
        not isinstance(config.get(key), str) or not config[key].strip()
        for key in ("exchange", "key", "secret")
    ):
        raise AccumulationStateError("Exchange credentials are unavailable.")
    require_exchange_placement_capabilities(config, order_type="limit")
    identity = [
        config["exchange"].strip().lower(),
        config["key"],
        config.get("exchange_hostname") or "",
        bool(config.get("sandbox", False)) if not config["dry_run"] else False,
        "spot",
    ]
    prefix = "credential-v1:"
    if config["dry_run"]:
        prefix = "credential-demo-v1:"
    return (
        prefix
        + hashlib.sha256(
            json.dumps(identity, separators=(",", ":")).encode()
        ).hexdigest()
    )


@dataclass(frozen=True)
class AccumulationBuyPrecision:
    """Requested and executable principal; precision may reduce but never top up."""

    requested_quote: str
    executable_quote: str
    amount: str
    limit_price: str


@dataclass(frozen=True)
class AccumulationSaleInputs:
    """Fresh owned-wallet evidence and a quantity rounded down to market precision."""

    amount: str
    observed_at_ms: int


@dataclass(frozen=True)
class AccumulationWalletEvidence:
    """Fresh free inventory observed under the current credential scope."""

    account_scope: str
    free_base: str
    observed_at_ms: int


class AccumulationSaleSizeError(AccumulationStateError):
    """A known sale-size restriction leaves the exact holding managed and unsold."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def preflight_accumulation_precision(
    client: Any,
    symbol: str,
    requested_quote: str,
    ceiling: str,
) -> AccumulationBuyPrecision:
    """Use loaded CCXT precision metadata and enforce exact spend/price ceilings."""
    market = client.markets.get(symbol)
    if (
        not isinstance(market, dict)
        or market.get("spot") is not True
        or market.get("active") is not True
    ):
        raise AccumulationStateError("An active canonical spot market is required.")
    with localcontext() as context:
        context.prec = 80
        requested = Decimal(canonical_decimal(requested_quote, positive=True))
        maximum = Decimal(canonical_decimal(ceiling, positive=True))
        price_precision = (market.get("precision") or {}).get("price")
        if price_precision is None:
            raise AccumulationStateError("Price precision is unknown.")
        price = Decimal(
            canonical_decimal(
                ccxt.decimal_to_precision(
                    str(maximum),
                    ccxt.TRUNCATE,
                    price_precision,
                    client.precisionMode,
                ),
                positive=True,
            )
        )
        price = Decimal(
            canonical_decimal(
                client.price_to_precision(symbol, str(price)), positive=True
            )
        )
        amount = Decimal(
            canonical_decimal(
                client.amount_to_precision(symbol, str(requested / price)),
                positive=True,
            )
        )
        executable = amount * price
        if price > maximum or executable > requested:
            raise AccumulationStateError("Precision must not increase price or spend.")
        minimum = get_min_notional_for_market(market, is_market_order=False)
        if minimum is None or executable < Decimal(str(minimum)):
            raise AccumulationStateError(
                "Precision-adjusted buy is below its known minimum."
            )
        limits = market.get("limits") or {}
        for name, value in (("amount", amount), ("price", price), ("cost", executable)):
            bounds = limits.get(name) or {}
            for bound in ("min", "max"):
                raw = bounds.get(bound)
                if raw is None:
                    continue
                limit = Decimal(decimal_evidence(raw))
                if (bound == "min" and value < limit) or (
                    bound == "max" and value > limit
                ):
                    raise AccumulationStateError(
                        "Buy exceeds exchange precision/size limits."
                    )
        return AccumulationBuyPrecision(
            str(requested), str(executable), str(amount), str(price)
        )


class AccumulationExchangeAdapter:
    """Provide bounded authenticated reads, ownership warmup and exact preflight."""

    def __init__(
        self,
        config_provider: Callable[[], dict[str, Any]],
        *,
        exchange: Exchange | None = None,
        clock_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
    ) -> None:
        self.config_provider = config_provider
        self.exchange = exchange or Exchange(balance_cache_ttl_seconds=0)
        self.clock_ms = clock_ms
        self._read_lock = asyncio.Lock()

    async def close(self) -> None:
        """Close the adapter-owned exchange client."""
        await self.exchange.close()

    async def mark_quotes(
        self, symbols: list[str], config: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        """Fetch bounded-time bid marks; missing markets never receive a guessed price."""
        if not symbols:
            return {}
        async with self._read_lock, asyncio.timeout(10):
            client = await self._client(config, symbols[0])
            started = self.clock_ms()
            result = {}
            if getattr(client, "has", {}).get("fetchTickers"):
                tickers = await client.fetch_tickers(symbols)
            else:
                tickers = {}
                for symbol in symbols:
                    book = await client.fetch_order_book(symbol, 5)
                    tickers[symbol] = {
                        "bid": book["bids"][0][0] if book.get("bids") else None,
                        "timestamp": book.get("timestamp"),
                    }
            for symbol in symbols:
                market = client.markets.get(symbol, {})
                if market.get("active") is not True or market.get("spot") is not True:
                    continue
                ticker = tickers.get(symbol)
                if not isinstance(ticker, dict):
                    continue
                observed = ticker.get("timestamp")
                observed = started if observed is None else observed
                if type(observed) is int and 0 <= self.clock_ms() - observed <= 10000:
                    try:
                        result[symbol] = {
                            "bid": decimal_evidence(ticker.get("bid")),
                            "observed_at_ms": min(started, observed),
                        }
                    except ValueError:
                        continue
            await self.account_scope(config)
            return result

    def config(self) -> dict[str, Any]:
        """Read and validate server configuration before taking an account action."""
        value = dict(self.config_provider())
        if isinstance(value.get("currency"), str):
            value["currency"] = value["currency"].strip().upper()
        accumulation_account_scope(value)
        return value

    async def account_scope(self, config: dict[str, Any]) -> str:
        """Reject stale recovery configs before any authenticated order lookup."""
        scope = accumulation_account_scope(config)
        current = self.config()
        if scope != accumulation_account_scope(current) or config.get(
            "secret"
        ) != current.get("secret"):
            raise AccumulationStateError("Exchange account configuration changed.")
        return scope

    async def _client(self, config: dict[str, Any], symbol: str) -> Any:
        await self.account_scope(config)
        await self.exchange.fetch_market_metadata(config)
        client = self.exchange.exchange
        market = client.markets.get(symbol) if client is not None else None
        if (
            not isinstance(market, dict)
            or market.get("spot") is not True
            or market.get("active") is not True
        ):
            raise AccumulationStateError("An active canonical spot market is required.")
        if market.get("symbol") != symbol or (
            config.get("currency") and symbol.split("/")[-1] != config["currency"]
        ):
            raise AccumulationStateError("Symbol or configured quote currency changed.")
        return client

    async def _owned_base(
        self, symbol: str, free: Any, imported_quantity: str = "0"
    ) -> None:
        """Surplus wallet coins stay unmanaged; encumbered or missing base blocks."""
        base = symbol.split("/")[0]
        quantities = [Decimal(canonical_decimal(imported_quantity))]
        for holding in await model.OpenTrades.filter(symbol__startswith=base + "/"):
            if holding.lifecycle_mode == "accumulation":
                owner = await model.AccumulationActivation.get_or_none(
                    holding_id=holding.id
                )
                if owner is None or owner.account_scope != accumulation_account_scope(
                    self.config()
                ):
                    raise AccumulationStateError("Holding ownership requires repair.")
                quantities.append(
                    Decimal(canonical_decimal(holding.accumulation_net_quantity))
                )
            elif holding.lifecycle_mode == "classic_dca":
                quantities.append(Decimal(decimal_evidence(holding.amount)))
            else:
                raise AccumulationStateError("Unknown holding ownership mode.")
        with localcontext() as context:
            context.prec = 512
            quantity = sum(quantities, Decimal(0))
        if quantity > 0 and Decimal(decimal_evidence(free)) < quantity:
            raise AccumulationStateError("Owned base is missing or encumbered.")

    async def account_inventory(
        self, symbol: str, config: dict[str, Any]
    ) -> AccumulationWalletEvidence:
        """Read wallet ownership for explicit credential repair, without rebinding."""
        async with self._read_lock, asyncio.timeout(10):
            client = await self._client(config, symbol)
            scope = await self.account_scope(config)
            started = self.clock_ms()
            balance = await client.fetch_balance()
            if not isinstance(balance, dict) or not isinstance(
                balance.get("free"), dict
            ):
                raise AccumulationStateError("Fresh wallet evidence is unavailable.")
            observed = balance.get("timestamp")
            if observed is None:
                observed = started
            if (
                type(observed) is not int
                or not 0 <= self.clock_ms() - observed <= 10000
            ):
                raise AccumulationStateError("Wallet evidence is stale.")
            orders = await client.fetch_open_orders(symbol)
            if not isinstance(orders, list) or orders:
                raise AccumulationStateError("Open orders prevent account rebinding.")
            free = decimal_evidence(balance["free"].get(symbol.split("/")[0]))
            await self.account_scope(config)
            return AccumulationWalletEvidence(scope, free, min(started, observed))

    async def _reflected_holds(
        self, client: Any, symbol: str, quote: str, scope: str
    ) -> tuple[tuple[str, str], ...]:
        pending = await model.PlacementIntent.all().exclude(
            state__in=["completed", "rejected", "persisted"]
        )
        relevant = [row for row in pending if row.symbol.endswith("/" + quote)]
        symbols = {symbol} | {row.symbol for row in relevant if row.state != "prepared"}
        orders = []
        for pair in sorted(symbols):
            values = await client.fetch_open_orders(pair)
            if not isinstance(values, list):
                raise AccumulationStateError("Open-order evidence is unavailable.")
            if any(
                not isinstance(value, dict) or value.get("symbol") != pair
                for value in values
            ):
                raise AccumulationStateError("Open-order evidence is invalid.")
            orders.extend(values)
        matched = set()
        holds = []
        for row in relevant:
            if row.exchange_name != client.id:
                raise AccumulationStateError("Pending order belongs to another venue.")
            activation = await model.AccumulationActivation.get_or_none(
                symbol=row.symbol
            )
            if activation is not None and activation.account_scope != scope:
                raise AccumulationStateError(
                    "Pending order belongs to another account."
                )
            found = [
                order
                for order in orders
                if (
                    isinstance(order, dict)
                    and order.get("symbol") == row.symbol
                    and (
                        (
                            row.exchange_order_id is not None
                            and str(order.get("id")) == row.exchange_order_id
                        )
                        or (
                            row.client_order_id is not None
                            and order.get("clientOrderId") == row.client_order_id
                        )
                    )
                )
            ]
            if row.state == "prepared":
                if found:
                    raise AccumulationStateError(
                        "Unsubmitted order has unexpected exchange evidence."
                    )
                continue
            if len(found) != 1 or row.side != "buy":
                raise AccumulationStateError(
                    "Pending execution needs reconciliation before budgeting."
                )
            order = found[0]
            if (
                row.exchange_order_id is not None
                and str(order.get("id")) != row.exchange_order_id
            ):
                raise AccumulationStateError("Exchange order identity changed.")
            report = AccumulationFill.from_order(order)
            checkpoint = await model.AccumulationFillCheckpoint.get_or_none(
                placement_id=row.id
            )
            if report.terminal or report.side != "buy":
                raise AccumulationStateError("Pending execution needs reconciliation.")
            if checkpoint is None:
                if Decimal(report.filled) != 0:
                    raise AccumulationStateError(
                        "Unaccounted fill requires reconciliation."
                    )
            elif (
                Decimal(report.filled) != Decimal(checkpoint.filled)
                or Decimal(report.quote_cost) != Decimal(checkpoint.quote_cost)
                or {k: Decimal(v) for k, v in report.fees.items()}
                != {k: Decimal(v) for k, v in json.loads(checkpoint.fees_json).items()}
            ):
                raise AccumulationStateError("Fill evidence changed during budgeting.")
            remaining = Decimal(decimal_evidence(order.get("remaining")))
            price = Decimal(decimal_evidence(order.get("price")))
            if remaining <= 0 or price <= 0:
                raise AccumulationStateError("Exchange hold is not known.")
            holds.append((row.operation_id, str(remaining * price)))
            matched.add(id(order))
        # External orders on this symbol are never cancelled or adopted implicitly.
        if any(
            order.get("symbol") == symbol and id(order) not in matched
            for order in orders
        ):
            raise AccumulationStateError("External order ownership needs validation.")
        return tuple(holds)

    async def read_inputs(
        self, symbol: str, config: dict[str, Any], *, imported_quantity: str = "0"
    ) -> AccumulationAdmissionInputs:
        """Fetch fresh balance, open-order and ask evidence without lifecycle locks."""
        async with self._read_lock, asyncio.timeout(10):
            client = await self._client(config, symbol)
            token = await capture_accumulation_funding_token(config)
            started = self.clock_ms()
            scope = await self.account_scope(config)
            balance = await client.fetch_balance()
            if not isinstance(balance, dict) or not isinstance(
                balance.get("free"), dict
            ):
                raise AccumulationStateError("Fresh free balance is unavailable.")
            base, quote = symbol.split("/")
            # Missing assets are unknown; a verified zero must be explicitly present.
            free_quote = decimal_evidence(balance["free"].get(quote))
            balance_timestamp = balance.get("timestamp")
            if balance_timestamp is not None and (
                type(balance_timestamp) is not int
                or not 0 <= self.clock_ms() - balance_timestamp <= 10000
            ):
                raise AccumulationStateError(
                    "Balance evidence is stale or future-dated."
                )
            await self._owned_base(symbol, balance["free"].get(base), imported_quantity)
            holds = await self._reflected_holds(client, symbol, quote, scope)
            if holds:
                used = Decimal(decimal_evidence((balance.get("used") or {}).get(quote)))
                if sum((Decimal(value) for _, value in holds), Decimal(0)) > used:
                    raise AccumulationStateError(
                        "Order holds disagree with exchange balance."
                    )
            book = await client.fetch_order_book(symbol, limit=5)
            if not isinstance(book, dict) or not book.get("asks"):
                raise AccumulationStateError("Fresh executable ask is unavailable.")
            best_ask = book["asks"][0]
            if not isinstance(best_ask, (list, tuple)) or len(best_ask) < 2:
                raise AccumulationStateError("Executable ask depth is unavailable.")
            ask = canonical_decimal(decimal_evidence(best_ask[0]), positive=True)
            canonical_decimal(decimal_evidence(best_ask[1]), positive=True)
            timestamp = book.get("timestamp")
            observed = started if timestamp is None else timestamp
            if (
                type(observed) is not int
                or not 0 <= self.clock_ms() - observed <= 10000
            ):
                raise AccumulationStateError(
                    "Executable quote is stale or future-dated."
                )
            minimum = get_min_notional_for_market(
                client.markets[symbol], is_market_order=False
            )
            if minimum is None:
                raise AccumulationStateError("Exchange minimum is unknown.")
            await self.account_scope(config)
            return AccumulationAdmissionInputs(
                AccumulationFundingSnapshot(
                    scope, client.id, quote, free_quote, started, token, holds
                ),
                ask,
                min(started, observed),
                str(minimum),
            )

    async def sale_inputs(
        self, symbol: str, quantity: str, config: dict[str, Any]
    ) -> AccumulationSaleInputs:
        """Validate unencumbered owned base and known market-sale size limits."""
        async with self._read_lock, asyncio.timeout(10):
            client = await self._client(config, symbol)
            require_exchange_placement_capabilities(config, order_type="market")
            started = self.clock_ms()
            balance = await client.fetch_balance()
            if not isinstance(balance, dict) or not isinstance(
                balance.get("free"), dict
            ):
                raise AccumulationStateError("Fresh wallet evidence is unavailable.")
            balance_time = balance.get("timestamp", started)
            if balance_time is None:
                balance_time = started
            if type(balance_time) is not int or not (
                0 <= self.clock_ms() - balance_time <= 10000
            ):
                raise AccumulationStateError("Wallet evidence is stale.")
            await self._owned_base(symbol, balance["free"].get(symbol.split("/")[0]))
            orders = await client.fetch_open_orders(symbol)
            if not isinstance(orders, list) or orders:
                raise AccumulationStateError(
                    "Open orders require ownership resolution."
                )
            book = await client.fetch_order_book(symbol, limit=5)
            if not isinstance(book, dict) or not book.get("bids"):
                raise AccumulationStateError("Fresh executable bid is unavailable.")
            bid = book["bids"][0]
            if not isinstance(bid, (list, tuple)) or len(bid) < 2:
                raise AccumulationStateError("Executable bid depth is unavailable.")
            price = Decimal(canonical_decimal(decimal_evidence(bid[0]), positive=True))
            canonical_decimal(decimal_evidence(bid[1]), positive=True)
            observed = book.get("timestamp")
            if observed is None:
                observed = started
            if type(observed) is not int or not (
                0 <= self.clock_ms() - observed <= 10000
            ):
                raise AccumulationStateError("Executable bid is stale.")
            requested = Decimal(canonical_decimal(quantity, positive=True))
            with localcontext() as context:
                context.prec = 80
                try:
                    amount = Decimal(
                        canonical_decimal(
                            client.amount_to_precision(symbol, str(requested))
                        )
                    )
                except ccxt.InvalidOrder as exc:
                    raise AccumulationSaleSizeError("WAIT_PRECISION") from exc
                if amount == 0:
                    raise AccumulationSaleSizeError("WAIT_PRECISION")
            if amount > requested:
                raise AccumulationStateError(
                    "Sale precision must never increase quantity."
                )
            market = client.markets[symbol]
            minimum = get_min_notional_for_market(market, is_market_order=True)
            with localcontext() as context:
                context.prec = 80
                cost = amount * price
            if minimum is None:
                raise AccumulationStateError("Exchange market-sale minimum is unknown.")
            if cost < Decimal(str(minimum)):
                raise AccumulationSaleSizeError("WAIT_MINIMUM")
            for name, value in (("amount", amount), ("cost", cost)):
                bounds = (market.get("limits") or {}).get(name) or {}
                for bound in ("min", "max"):
                    if bounds.get(bound) is None:
                        continue
                    limit = Decimal(decimal_evidence(bounds[bound]))
                    if (bound == "min" and value < limit) or (
                        bound == "max" and value > limit
                    ):
                        raise AccumulationSaleSizeError("WAIT_SIZE_LIMIT")
            await self.account_scope(config)
            return AccumulationSaleInputs(
                str(amount), min(started, observed, balance_time)
            )

    async def admission_inputs(
        self, offer: AccumulationOffer
    ) -> AccumulationAdmissionInputs:
        """Adapter for the internal portfolio coordinator's provider contract."""
        activation = await model.AccumulationActivation.get(
            id=offer.decision.identity.activation_id
        )
        try:
            return await self.read_inputs(activation.symbol, self.config())
        except (ccxt.BaseError, OSError) as exc:
            raise AccumulationStateError(
                "Exchange preflight evidence is unavailable."
            ) from exc

    async def candles(
        self, symbol: str, parameters: AccumulationParameters, *, rebase: bool = False
    ) -> tuple[AccumulationCandle, ...]:
        """Read a bounded completed-candle window; forming candles never enter it."""
        config = self.config()
        async with self._read_lock, asyncio.timeout(30):
            await self._client(config, symbol)
            close = parameters.latest_close(self.clock_ms())
            count = (
                (2 * parameters.history_length - 1)
                if rebase
                else parameters.history_length
            )
            rows = await self.exchange.get_history_for_symbol_batched(
                config,
                symbol,
                parameters.timeframe,
                since=close - count * parameters.interval_ms,
                until=close - 1,
                max_candles=count,
                page_size=min(1000, count),
            )
            result = []
            for row in rows:
                if (
                    not isinstance(row, (list, tuple))
                    or len(row) < 5
                    or type(row[0]) is not int
                ):
                    raise AccumulationStateError("Invalid OHLCV evidence.")
                end = row[0] + parameters.interval_ms
                if end > close:
                    continue
                result.append(
                    AccumulationCandle(
                        end, *(decimal_evidence(value) for value in row[1:5])
                    )
                )
            calculate_accumulation_market(
                result[-parameters.history_length :], parameters, close_ms=close
            )
            await self.account_scope(config)
            return tuple(result)

    async def readiness(
        self, request: AccumulationValidationRequest
    ) -> AccumulationReadiness:
        """Authenticate ownership and rebuild observations without placing a buy."""
        config = self.config()
        scope = await self.account_scope(config)
        if request.account_scope != scope:
            raise AccumulationStateError("Activation account requires revalidation.")
        version = await load_accumulation_strategy_version(request.target_version_id)
        rows = (
            []
            if request.initial_asap
            else await self.candles(request.symbol, version.parameters, rebase=True)
        )
        baseline = version.parameters.latest_close(self.clock_ms())
        if request.imported_inventory is not None:
            inputs = await self.read_inputs(
                request.symbol,
                config,
                imported_quantity=request.imported_inventory.quantity,
            )
        else:
            inputs = await self.read_inputs(request.symbol, config)
        activation = await model.AccumulationActivation.get(id=request.activation_id)
        if (
            activation.revision != request.revision
            or activation.consumption_revision != request.consumption_revision
            or activation.symbol != request.symbol
            or activation.account_scope != scope
            or (rows and rows[-1].close_ms != baseline)
        ):
            raise AccumulationStateError("Lifecycle changed during readiness.")
        guard = _guard(activation.execution_guard_json, activation.consumption_revision)
        observations = (
            rebuild_accumulation_observations(
                rows, version.parameters, guard, baseline_close_ms=baseline
            )
            if rows
            else None
        )
        await self.account_scope(config)

        async def validate_commit() -> None:
            # Caller holds the symbol/capital locks and a DB transaction.
            if (
                self.config() != config
                or not 0 <= self.clock_ms() - inputs.funding.observed_at_ms <= 10000
            ):
                raise AccumulationStateError(
                    "Readiness evidence expired or settings changed."
                )
            token, _, _ = await _budget_state(config)
            if token != inputs.funding.ledger_token:
                raise AccumulationStateError(
                    "Owned inventory changed during readiness."
                )

        return AccumulationReadiness(
            scope,
            version.id,
            baseline,
            asdict(observations) if observations is not None else None,
            validate_commit,
        )
