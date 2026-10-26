"""Dynamic DCA exchange policy over the shared CCXT transport.

Normal and recovered orders use the same finalization. Inventory accounting for
accumulation never passes through this adapter.
"""

import json
from collections.abc import Awaitable, Callable
from typing import Any, cast

import ccxt.async_support as ccxt
from service.dca.limit_fills import DcaLimitSellManager
from service.dca.limit_orders import DcaLimitOrderManager
from service.dca.sell_execution import DcaSellManager
from service.dca.sell_status import (
    build_partial_sell_status,
    finalize_sell_order_status,
)
from service.exchange import Exchange, logging
from service.exchange_capabilities import (
    ExchangePostSubmissionFailure,
    UnsupportedExchangeCapability,
    require_exchange_placement_capabilities,
)
from service.exchange_contexts import (
    BuyFinalizationContext,
    LimitSellFillContext,
    LimitSellPlacementContext,
    MarketSellExecutionContext,
    SellRoutingContext,
)
from service.exchange_risk import build_buy_precheck_result, normalize_buy_buffer_pct
from service.exchange_types import ExchangeOrderPayload, ParsedOrderStatus
from tenacity import (
    TryAgain,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
)


class DcaExchange(Exchange):
    """Add DCA order policy while retaining one shared transport/client owner."""

    def __init__(self, *, balance_cache_ttl_seconds: float | None = None) -> None:
        super().__init__(balance_cache_ttl_seconds=balance_cache_ttl_seconds)
        self._last_buy_precheck_result: dict[str, Any] | None = None
        self._sell_manager = DcaSellManager(logging, lambda: self.exchange)
        self._limit_order_manager = DcaLimitOrderManager(logging, lambda: self.exchange)
        self._limit_sell_manager = DcaLimitSellManager(logging, lambda: self.exchange)

    async def create_spot_market_buy(
        self,
        order: dict[str, Any],
        config: dict[str, Any],
        *,
        _bybiteu_price_band_retry: bool = False,
    ) -> dict[str, Any] | None:
        """Create a spot buy, refreshing a rejected Bybit EU price band once."""
        try:
            require_exchange_placement_capabilities(
                config,
                order_type=(
                    "limit"
                    if float(order.get("maximum_buy_price") or 0.0) > 0
                    else str(order.get("ordertype") or "market")
                ),
            )
        except UnsupportedExchangeCapability as exc:
            self._last_buy_precheck_result = build_buy_precheck_result(
                ok=False,
                reason="unsupported_exchange_reconciliation",
                symbol=str(order.get("symbol") or ""),
                required_quote=self._resolve_required_buy_quote(order),
            )
            logging.error("%s", exc)
            return None
        await self._ensure_exchange(config)
        await self._ensure_markets_loaded()
        self._last_buy_precheck_result = None
        order_check_range_seconds = self._get_order_check_range_seconds(config)
        order["price"] = await self._get_price_for_symbol(
            order["symbol"],
            prefer_ask=True,
        )
        maximum_buy_price = float(order.get("maximum_buy_price") or 0.0)
        if maximum_buy_price > 0:
            if getattr(self.exchange, "id", None) == "bybiteu":
                try:
                    maximum_buy_price = await self._get_bybiteu_buy_ceiling(
                        order["symbol"], maximum_buy_price
                    )
                except (
                    ccxt.BaseError,
                    TimeoutError,
                    TypeError,
                    ValueError,
                    KeyError,
                ) as exc:
                    self._last_buy_precheck_result = build_buy_precheck_result(
                        ok=False,
                        reason="exchange_price_band_unavailable",
                        symbol=str(order.get("symbol") or ""),
                        maximum_buy_price=maximum_buy_price,
                    )
                    logging.warning(
                        "Skipping Bybit EU recovery buy for %s: price band unavailable (%s).",
                        order.get("symbol"),
                        exc,
                    )
                    return None
            try:
                maximum_buy_price = self._get_capped_buy_price(
                    order["symbol"], maximum_buy_price
                )
            except (ccxt.BaseError, TypeError, ValueError):
                self._last_buy_precheck_result = build_buy_precheck_result(
                    ok=False,
                    reason="invalid_price_or_amount",
                    symbol=str(order.get("symbol") or ""),
                    maximum_buy_price=maximum_buy_price,
                )
                return None
            order["maximum_buy_price"] = maximum_buy_price
        executable_price = float(order.get("price") or 0.0)
        if maximum_buy_price > 0 and executable_price > maximum_buy_price:
            self._last_buy_precheck_result = build_buy_precheck_result(
                ok=False,
                reason="execution_price_above_maximum",
                symbol=str(order.get("symbol") or ""),
                required_quote=self._resolve_required_buy_quote(order),
                executable_price=executable_price,
                maximum_buy_price=maximum_buy_price,
            )
            logging.warning(
                "Skipping recovery buy for %s: executable ask %.12f exceeds "
                "maximum buy price %.12f.",
                order.get("symbol"),
                executable_price,
                maximum_buy_price,
            )
            return None
        amount_sizing_price = (
            maximum_buy_price if maximum_buy_price > 0 else order["price"]
        )
        order["amount"] = await self._get_amount_from_symbol(
            order["ordersize"],
            order["symbol"],
            amount_sizing_price,
        )
        if not order["price"] or not order["amount"] or float(order["amount"]) <= 0:
            self._last_buy_precheck_result = build_buy_precheck_result(
                ok=False,
                reason="invalid_price_or_amount",
                symbol=str(order.get("symbol") or ""),
                required_quote=self._resolve_required_buy_quote(order),
            )
            logging.error(
                "Skipping buy for %s: invalid price/amount (price=%s, amount=%s).",
                order.get("symbol"),
                order.get("price"),
                order.get("amount"),
            )
            return None
        below_minimum, minimum_notional, estimated_notional = (
            self._is_notional_below_minimum(
                order["symbol"],
                float(order["amount"]),
                float(amount_sizing_price),
                is_market_order=maximum_buy_price <= 0,
            )
        )
        if below_minimum:
            self._last_buy_precheck_result = build_buy_precheck_result(
                ok=False,
                reason="amount_below_minimum_notional",
                symbol=str(order.get("symbol") or ""),
                required_quote=minimum_notional,
                available_quote=None,
                executable_price=float(amount_sizing_price),
                maximum_buy_price=(
                    maximum_buy_price if maximum_buy_price > 0 else None
                ),
            )
            logging.warning(
                "Skipping buy for %s: precision-adjusted notional %.12f is "
                "below minimum %.12f.",
                order.get("symbol"),
                estimated_notional,
                minimum_notional,
            )
            return None
        if not await self._preflight_buy_funds(order, config):
            precheck = self._last_buy_precheck_result or {}
            logging.warning(
                "Skipping buy for %s: funds check failed (%s). required=%s available=%s",
                order.get("symbol"),
                precheck.get("reason", "unknown"),
                precheck.get("required_quote"),
                precheck.get("available_quote"),
            )
            return None
        submitted_order = order
        try:
            order = await self._execute_market_buy(submitted_order)
        except (ccxt.InvalidOrder, ccxt.BadRequest) as exc:
            if (
                maximum_buy_price > 0
                and not _bybiteu_price_band_retry
                and self._is_bybiteu_price_band_rejection(exc)
            ):
                # This response explicitly rejected the order. Accepted/uncertain
                # submissions remain in the existing reconciliation path.
                logging.warning(
                    "Refreshing Bybit EU price band and retrying recovery buy for %s once after rejection.",
                    submitted_order.get("symbol"),
                )
                return await self.create_spot_market_buy(
                    submitted_order, config, _bybiteu_price_band_retry=True
                )
            self._last_buy_precheck_result = build_buy_precheck_result(
                ok=False,
                reason="exchange_rejected_order",
                symbol=str(submitted_order.get("symbol") or ""),
                required_quote=self._resolve_required_buy_quote(submitted_order),
                executable_price=executable_price,
                maximum_buy_price=maximum_buy_price or None,
            )
            logging.error(
                "Buy order for %s rejected by the exchange: %s",
                submitted_order.get("symbol"),
                exc,
            )
            return None
        if not order:
            if maximum_buy_price > 0:
                self._last_buy_precheck_result = build_buy_precheck_result(
                    ok=False,
                    reason="execution_ceiling_not_filled",
                    symbol=str(submitted_order.get("symbol") or ""),
                    required_quote=self._resolve_required_buy_quote(submitted_order),
                    executable_price=executable_price,
                    maximum_buy_price=maximum_buy_price,
                )
            return None
        try:
            finalized = await self.finalize_market_buy(
                order=order,
                config=config,
                context=BuyFinalizationContext(
                    parse_order_status=lambda buy_order: self._parse_order_status(
                        buy_order,
                        order_check_range_seconds=order_check_range_seconds,
                    ),
                    get_precision_for_symbol=self._get_precision_for_symbol,
                    resolve_symbol=self._resolve_symbol_with_refresh,
                    get_demo_taker_fee_for_symbol=self._get_demo_taker_fee_for_symbol,
                ),
            )
        except Exception as exc:
            raise ExchangePostSubmissionFailure(
                action="buy",
                symbol=str(order.get("symbol") or submitted_order.get("symbol") or ""),
                order=dict(order),
                cause=exc,
                operation_id=str(order.get("operation_id") or "") or None,
            ) from exc
        if finalized is None:
            raise ExchangePostSubmissionFailure(
                action="buy",
                symbol=str(order.get("symbol") or submitted_order.get("symbol") or ""),
                order=dict(order),
                operation_id=str(order.get("operation_id") or "") or None,
            )
        return finalized

    async def build_spot_buy_order_status(
        self,
        exchange_order: dict[str, Any],
        original_order: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Normalize a reconciled exchange buy without placing another order."""
        await self._ensure_exchange(config)
        await self._ensure_markets_loaded()
        combined_order = cast(
            ExchangeOrderPayload,
            {**original_order, **exchange_order},
        )
        order_check_range_seconds = self._get_order_check_range_seconds(config)
        return await self.finalize_market_buy(
            order=combined_order,
            config=config,
            context=BuyFinalizationContext(
                parse_order_status=lambda buy_order: self._parse_order_status(
                    buy_order,
                    order_check_range_seconds=order_check_range_seconds,
                ),
                get_precision_for_symbol=self._get_precision_for_symbol,
                resolve_symbol=self._resolve_symbol_with_refresh,
                get_demo_taker_fee_for_symbol=self._get_demo_taker_fee_for_symbol,
            ),
        )

    def _get_demo_taker_fee_for_symbol(self, symbol: str) -> float:
        """Return the static market taker fee for demo trading mode."""
        resolved_symbol = self._resolve_symbol(symbol)
        if resolved_symbol is None:
            raise ValueError(f"No market available for symbol {symbol}")
        market = self.exchange.market(resolved_symbol)
        taker_fee = market.get("taker")
        if taker_fee is None:
            raise ValueError(f"No market taker fee available for symbol {symbol}")
        return float(taker_fee)

    async def _preflight_buy_funds(
        self, order: dict[str, Any], config: dict[str, Any]
    ) -> bool:
        """Check quote balance before placing a buy order."""
        self._last_buy_precheck_result = None

        symbol = str(order.get("symbol") or "")
        resolved_symbol = await self._resolve_symbol_with_refresh(symbol)
        if resolved_symbol is None:
            self._last_buy_precheck_result = build_buy_precheck_result(
                ok=False,
                reason="symbol_not_found",
                symbol=symbol,
            )
            return False

        required_quote = self._resolve_required_buy_quote(order)
        if required_quote is None:
            self._last_buy_precheck_result = build_buy_precheck_result(
                ok=False,
                reason="invalid_required_quote",
                symbol=resolved_symbol,
            )
            return False

        buffer_pct = normalize_buy_buffer_pct(config.get("buy_fund_buffer_pct"))
        required_with_buffer = required_quote * (1 + buffer_pct)

        available_quote = await self.get_free_quote_balance(
            config=config,
            symbol=resolved_symbol,
            force_refresh=True,
        )
        if available_quote is None:
            self._last_buy_precheck_result = build_buy_precheck_result(
                ok=False,
                reason="balance_unavailable",
                symbol=resolved_symbol,
                required_quote=required_with_buffer,
                available_quote=None,
                buffer_pct=buffer_pct,
            )
            return False

        if available_quote + 1e-12 < required_with_buffer:
            self._last_buy_precheck_result = build_buy_precheck_result(
                ok=False,
                reason="insufficient_quote_balance",
                symbol=resolved_symbol,
                required_quote=required_with_buffer,
                available_quote=float(available_quote),
                buffer_pct=buffer_pct,
            )
            return False

        self._last_buy_precheck_result = build_buy_precheck_result(
            ok=True,
            reason="ok",
            symbol=resolved_symbol,
            required_quote=required_with_buffer,
            available_quote=float(available_quote),
            buffer_pct=buffer_pct,
        )
        return True

    def get_last_buy_precheck_result(self) -> dict[str, Any] | None:
        """Return metadata from the most recent buy funds pre-check."""
        return self._last_buy_precheck_result

    async def _execute_market_buy(self, order: dict[str, Any]) -> dict[str, Any] | None:
        """Execute a market buy via the dedicated buy manager.

        This private seam is kept explicit because several regression tests
        monkeypatch it to isolate funds-guard behavior from order placement.
        """
        return await self._buy_manager.execute_market_buy(order)

    async def create_spot_sell(
        self,
        order: dict[str, Any],
        config: dict[str, Any],
        *,
        create_market_fallback: (
            Callable[
                [dict[str, Any], dict[str, Any], dict[str, Any]],
                Awaitable[dict[str, Any] | None],
            ]
            | None
        ) = None,
    ) -> dict[str, Any] | None:
        order_type = str(config.get("sell_order_type", "market")).lower()
        try:
            require_exchange_placement_capabilities(
                config,
                order_type=order_type,
            )
        except UnsupportedExchangeCapability as exc:
            logging.error("%s", exc)
            return None
        return await self._sell_manager.create_spot_sell(
            order=order,
            config=config,
            context=SellRoutingContext(
                create_spot_limit_sell=self.create_spot_limit_sell,
                create_spot_market_sell=self.create_spot_market_sell,
                create_spot_market_fallback=(
                    create_market_fallback or self._create_spot_market_fallback
                ),
                can_fallback_to_market_sell=self._can_fallback_to_market_sell,
            ),
        )

    async def _create_spot_market_fallback(
        self,
        order: dict[str, Any],
        config: dict[str, Any],
        _limit_status: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Execute the legacy non-durable fallback for direct adapter callers."""
        return await self.create_spot_market_sell(order, config)

    async def place_spot_limit_sell(
        self, order: dict[str, Any], config: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Place a limit sell without waiting for fill reconciliation."""
        try:
            require_exchange_placement_capabilities(
                config,
                order_type="limit",
            )
        except UnsupportedExchangeCapability as exc:
            logging.error("%s", exc)
            return None
        return await self._limit_order_manager.create_spot_limit_sell(
            order=order,
            config=config,
            context=LimitSellPlacementContext(
                ensure_exchange=self._ensure_exchange,
                ensure_markets_loaded=self._ensure_markets_loaded,
                resolve_symbol=self._resolve_symbol_with_refresh,
                resolve_sell_amount=self._resolve_sell_amount,
                is_notional_below_minimum=self._build_notional_check(
                    is_market_order=False
                ),
                get_price_for_symbol=self._get_price_for_symbol,
                handle_limit_sell_fill=lambda sell_order, _symbol, _cfg, _original: (
                    self._return_limit_sell_order(sell_order)
                ),
            ),
        )

    async def _return_limit_sell_order(
        self, sell_order: dict[str, Any]
    ) -> dict[str, Any]:
        """Return a just-placed limit sell for external lifecycle ownership."""
        return sell_order

    async def _can_fallback_to_market_sell(
        self, order: dict[str, Any], config: dict[str, Any]
    ) -> bool:
        """Check whether market fallback is allowed after limit timeout."""
        if not bool(config.get("limit_sell_fallback_tp_guard", True)):
            return True

        fallback_min_price = order.get("fallback_min_price")
        if fallback_min_price in (None, False):
            return True

        try:
            min_price = float(fallback_min_price)
        except (TypeError, ValueError):
            return True

        try:
            current_price = float(await self._get_price_for_symbol(order["symbol"]))
        except (ccxt.BaseError, RuntimeError, TypeError, ValueError) as exc:
            logging.warning(
                "Skipping market fallback for %s: could not determine current price (%s).",
                order.get("symbol"),
                exc,
            )
            return False

        if current_price < min_price:
            logging.info(
                "Skipping market fallback for %s: current price %.10f is below "
                "minimum fallback price %.10f.",
                order.get("symbol"),
                current_price,
                min_price,
            )
            return False

        return True

    async def _build_sell_order_status(
        self,
        order: dict[str, Any],
        *,
        order_check_range_seconds: int,
    ) -> dict[str, Any] | None:
        """Build normalized sell order status for closed trade processing."""
        order_status = await self._parse_order_status(
            order,
            order_check_range_seconds=order_check_range_seconds,
        )
        if not order_status.get("total_amount"):
            logging.error(
                "Sell order for %s returned empty amount.", order.get("symbol")
            )
            return None

        finalized_status = finalize_sell_order_status(
            order_status,
            total_cost=float(order["total_cost"]),
            actual_pnl=order["actual_pnl"],
        )
        requested_amount = float(
            order.get("requested_total_amount") or order.get("total_amount") or 0.0
        )
        sold_amount = float(finalized_status.get("total_amount") or 0.0)
        remaining_amount = max(0.0, requested_amount - sold_amount)
        if remaining_amount <= 1e-12:
            return finalized_status

        symbol = str(finalized_status.get("symbol") or order.get("symbol") or "")
        reference_price = float(
            finalized_status.get("price") or order.get("current_price") or 0.0
        )
        (
            unsellable,
            unsellable_reason,
            unsellable_min_notional,
            unsellable_estimated_notional,
        ) = self._classify_sell_remainder(
            symbol=symbol,
            remaining_amount=remaining_amount,
            reference_price=reference_price,
            is_market_order=str(order.get("ordertype") or "").lower() != "limit",
        )
        return build_partial_sell_status(
            symbol=symbol,
            partial_amount=sold_amount,
            partial_avg_price=reference_price,
            remaining_amount=remaining_amount,
            executions=list(finalized_status.get("executions") or []),
            unsellable=unsellable,
            unsellable_reason=unsellable_reason,
            unsellable_min_notional=unsellable_min_notional,
            unsellable_estimated_notional=unsellable_estimated_notional,
        )

    def _classify_sell_remainder(
        self,
        *,
        symbol: str,
        remaining_amount: float,
        reference_price: float,
        is_market_order: bool,
    ) -> tuple[bool, str | None, float | None, float | None]:
        """Return whether a sell remainder is immediately unsellable."""
        if remaining_amount <= 0 or self.exchange is None:
            return False, None, None, None

        try:
            precision_sellable_amount = float(
                self.exchange.amount_to_precision(symbol, remaining_amount)
            )
        except (ccxt.BaseError, TypeError, ValueError):
            precision_sellable_amount = remaining_amount

        estimated_notional = (
            remaining_amount * reference_price if reference_price > 0 else None
        )
        if precision_sellable_amount <= 0:
            return True, "amount_precision", None, estimated_notional

        below_min_notional, min_notional, normalized_estimated_notional = (
            self._is_notional_below_minimum(
                symbol,
                precision_sellable_amount,
                reference_price,
                is_market_order=is_market_order,
            )
        )
        if below_min_notional:
            return (
                True,
                "minimum_notional",
                min_notional,
                normalized_estimated_notional,
            )

        return False, None, None, estimated_notional

    async def build_spot_sell_order_status(
        self,
        order: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Build normalized sell status for a pre-existing exchange sell order."""
        return await self._build_sell_order_status(
            order,
            order_check_range_seconds=self._get_order_check_range_seconds(config),
        )

    async def create_spot_limit_sell(
        self, order: dict[str, Any], config: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Create a spot limit sell order and delegate fill handling."""
        try:
            require_exchange_placement_capabilities(
                config,
                order_type="limit",
            )
        except UnsupportedExchangeCapability as exc:
            logging.error("%s", exc)
            return None
        order_check_range_seconds = self._get_order_check_range_seconds(config)
        return await self._limit_order_manager.create_spot_limit_sell(
            order=order,
            config=config,
            context=LimitSellPlacementContext(
                ensure_exchange=self._ensure_exchange,
                ensure_markets_loaded=self._ensure_markets_loaded,
                resolve_symbol=self._resolve_symbol_with_refresh,
                resolve_sell_amount=self._resolve_sell_amount,
                is_notional_below_minimum=self._build_notional_check(
                    is_market_order=False
                ),
                get_price_for_symbol=self._get_price_for_symbol,
                handle_limit_sell_fill=lambda sell_order, resolved_symbol, cfg, original: (
                    self._handle_limit_sell_fill(
                        sell_order,
                        resolved_symbol,
                        cfg,
                        original,
                        order_check_range_seconds=order_check_range_seconds,
                    )
                ),
            ),
        )

    async def _handle_limit_sell_fill(
        self,
        sell_order: dict[str, Any],
        resolved_symbol: str,
        config: dict[str, Any],
        original_order: dict[str, Any],
        *,
        order_check_range_seconds: int,
    ) -> dict[str, Any] | None:
        """Delegate limit-sell timeout and partial-fill reconciliation."""
        return await self._limit_sell_manager.handle_limit_sell_fill(
            sell_order=sell_order,
            resolved_symbol=resolved_symbol,
            config=config,
            original_order=original_order,
            context=LimitSellFillContext(
                parse_order_status=lambda limit_order: self._parse_order_status(
                    limit_order,
                    order_check_range_seconds=order_check_range_seconds,
                ),
                build_sell_order_status=lambda limit_order: (
                    self._build_sell_order_status(
                        limit_order,
                        order_check_range_seconds=order_check_range_seconds,
                    )
                ),
            ),
        )

    @retry(
        wait=wait_fixed(1),
        stop=stop_after_attempt(200),
        retry=retry_if_exception_type(TryAgain),
        reraise=True,
    )
    async def create_spot_market_sell(
        self, order: dict[str, Any], config: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Create a spot market sell order via the sell manager."""
        try:
            require_exchange_placement_capabilities(
                config,
                order_type="market",
            )
        except UnsupportedExchangeCapability as exc:
            logging.error("%s", exc)
            return None
        order_check_range_seconds = self._get_order_check_range_seconds(config)
        return await self._sell_manager.create_spot_market_sell(
            order=order,
            config=config,
            context=MarketSellExecutionContext(
                ensure_exchange=self._ensure_exchange,
                ensure_markets_loaded=self._ensure_markets_loaded,
                resolve_symbol=self._resolve_symbol_with_refresh,
                resolve_sell_amount=self._resolve_sell_amount,
                reduce_amount_by_step=self._reduce_amount_by_step,
                is_notional_below_minimum=self._build_notional_check(
                    is_market_order=True
                ),
                get_price_for_symbol=self._get_price_for_symbol,
                log_remaining_sell_dust=self._log_remaining_sell_dust,
                build_sell_order_status=lambda sell_order: (
                    self._build_sell_order_status(
                        sell_order,
                        order_check_range_seconds=order_check_range_seconds,
                    )
                ),
            ),
        )

    async def finalize_market_buy(
        self,
        *,
        order: ExchangeOrderPayload,
        config: dict[str, Any],
        context: BuyFinalizationContext,
    ) -> ExchangeOrderPayload | None:
        """Enrich a filled buy with normalized trade metadata."""
        exchange = self.exchange
        if exchange is None:
            return None

        logging.debug(
            "Normalizing buy symbol=%s order_id=%s",
            order.get("symbol"),
            order.get("id"),
        )

        order_status: ParsedOrderStatus = await context.parse_order_status(order)
        if "timestamp" in order_status:
            order["timestamp"] = order_status["timestamp"]
        if order_status.get("metadata_json"):
            raw_metadata = order.get("metadata_json")
            try:
                metadata = json.loads(raw_metadata) if raw_metadata else {}
            except (ValueError, TypeError):
                metadata = {}
            if not isinstance(metadata, dict):
                metadata = {}
            accounting_metadata = json.loads(order_status["metadata_json"])
            metadata.update(accounting_metadata)
            # Base-denominated fees must actually reduce inventory to be net.
            if config.get("fee_deduction", False) and order_status.get("base_fee"):
                metadata["feedback_accounting"]["external_buy_fees"] += float(
                    order_status["base_fee"]
                ) * float(order_status.get("price") or 0)
            order["metadata_json"] = json.dumps(metadata, sort_keys=True)
        if "amount" in order_status:
            order["amount"] = order_status["amount"]
        if "total_amount" in order_status:
            order["total_amount"] = order_status["total_amount"]
        elif "amount" in order_status:
            order["total_amount"] = float(order_status["amount"])
        if "price" in order_status:
            order["price"] = order_status["price"]
        if "orderid" in order_status:
            order["orderid"] = order_status["orderid"]
        if "symbol" in order_status:
            order["symbol"] = order_status["symbol"]
        if "side" in order_status:
            order["side"] = order_status["side"]
        if "amount_fee" in order_status:
            order["amount_fee"] = order_status["amount_fee"]
        if "base_fee" in order_status:
            order["base_fee"] = order_status["base_fee"]
        if order_status.get("ordersize") is not None:
            order["ordersize"] = order_status["ordersize"]
        if not order.get("amount") or float(order["amount"]) <= 0:
            logging.error(
                "Buy order for %s returned zero amount. Skipping trade creation.",
                order.get("symbol"),
            )
            return None

        status_symbol = str(order_status.get("symbol") or order.get("symbol") or "")
        if not status_symbol:
            logging.error("Cannot finalize buy: symbol is missing from order data.")
            return None

        order["precision"] = await context.get_precision_for_symbol(status_symbol)
        resolved_symbol = await context.resolve_symbol(status_symbol)
        if resolved_symbol is None:
            logging.error(
                "Cannot finalize buy for %s: symbol not found.",
                status_symbol,
            )
            return None

        order["amount"] = float(order_status.get("amount") or order["amount"])
        order["amount_fee"] = 0.0
        order["fees"] = 0.0

        if config.get("dry_run", True):
            try:
                order["fees"] = context.get_demo_taker_fee_for_symbol(status_symbol)
            except (ValueError, TypeError, ccxt.BaseError) as exc:
                logging.warning(
                    "Demo mode fee lookup for %s failed (%s). "
                    "Using taker fee 0.0 as fallback.",
                    status_symbol,
                    exc,
                )
                order["fees"] = 0.0
        else:
            try:
                fees = await exchange.fetch_trading_fee(symbol=status_symbol)
                order["fees"] = float(fees.get("taker", 0.0))
            except (ccxt.BaseError, TypeError, ValueError) as exc:
                logging.warning(
                    "Fetching fee rate for pair %s failed (%s). Using 0.0 fallback.",
                    order["symbol"],
                    exc,
                )
                order["fees"] = 0.0

        if not config.get("fee_deduction", False):
            order["amount_fee"] = float(order_status.get("base_fee") or 0.0)
            net_amount = max(0.0, float(order["amount"]) - order["amount_fee"])
            order["amount"] = float(net_amount)

            logging.debug(
                "Fee Deduction not active. Real amount %s, deducted amount %s, "
                "base fee %s",
                order_status["amount"],
                order["amount"],
                order["amount_fee"],
            )

        logging.debug(
            "Finalized DCA buy symbol=%s order_id=%s amount=%s base_fee=%s fee_rate=%s",
            order.get("symbol"),
            order.get("orderid") or order.get("id"),
            order.get("amount"),
            order.get("base_fee"),
            order.get("fees"),
        )
        return order
