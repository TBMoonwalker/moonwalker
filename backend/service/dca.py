"""DCA strategy handling and order logic."""

import asyncio
import importlib
from datetime import datetime, timedelta
from typing import Any

import helper
from service.ath import AthService
from service.autopilot import Autopilot, ResolvedTradingPolicy
from service.config import resolve_timeframe
from service.config_views import DcaRuntimeConfigView
from service.dca_safety_orders import (
    SafetyOrderContext,
    calculate_static_deviations,
    derive_safety_order_context,
    evaluate_static_dca_trigger,
)
from service.dca_tp_state import (
    TpConfirmationState,
    apply_trailing_take_profit,
    clear_tp_confirmation,
    evaluate_tp_confirmation,
    get_tp_confirmation_ticks,
)
from service.exchange import Exchange
from service.indicators import Indicators
from service.orders import Orders
from service.statistic import Statistic
from service.strategy_capability import ensure_strategy_supported
from service.trades import Trades

logging = helper.LoggerFactory.get_logger("logs/dca.log", "dca")


class Dca:
    """DCA engine for processing ticker data and managing orders."""

    def __init__(self) -> None:
        """Initialize DCA services and runtime state."""

        self.autopilot = Autopilot()
        self.ath_service = AthService()
        self.exchange = Exchange()
        self.indicators = Indicators()
        self.orders = Orders()
        self.statistic = Statistic()
        self.trades = Trades()
        self.utils = helper.Utils()
        self.config: dict[str, Any] | None = None
        self._strategy_cache: dict[tuple[str, str, str], object] = {}
        self._pending_tp_confirmations: dict[str, TpConfirmationState] = {}
        self._trailing_tp_peaks: dict[str, float] = {}

    def __get_monotonic_time(self) -> float:
        """Return a monotonic timestamp for TP confirmation timing."""
        return asyncio.get_running_loop().time()

    def __runtime_config(self) -> DcaRuntimeConfigView:
        """Return the typed DCA runtime settings for the current config snapshot."""
        return DcaRuntimeConfigView.from_config(self.config or {})

    def __tp_confirmation_enabled(self) -> bool:
        """Return whether TP spike confirmation is enabled."""
        return self.__runtime_config().tp_spike_confirm_enabled

    def __get_tp_confirmation_seconds(self) -> float:
        """Return the TP confirmation duration in seconds."""
        return self.__runtime_config().tp_spike_confirm_seconds

    def __get_tp_confirmation_ticks(self) -> int:
        """Return the optional TP confirmation tick count."""
        return self.__runtime_config().tp_spike_confirm_ticks

    def __clear_tp_confirmation(
        self,
        symbol: str,
        *,
        reason: str,
        current_price: float | None = None,
        tp_price: float | None = None,
    ) -> None:
        """Clear pending TP confirmation state and log why it was removed."""
        clear_tp_confirmation(
            self._pending_tp_confirmations,
            logger=logging,
            symbol=symbol,
            reason=reason,
            current_price=current_price,
            tp_price=tp_price,
        )

    def __evaluate_tp_confirmation(
        self,
        *,
        symbol: str,
        trade_timestamp: int,
        current_price: float,
        tp_price: float,
    ) -> bool:
        """Return whether TP remained above threshold long enough to sell."""
        return evaluate_tp_confirmation(
            self._pending_tp_confirmations,
            logger=logging,
            now=self.__get_monotonic_time(),
            symbol=symbol,
            trade_timestamp=trade_timestamp,
            current_price=current_price,
            tp_price=tp_price,
            seconds_required=self.__get_tp_confirmation_seconds(),
            ticks_required=self.__get_tp_confirmation_ticks(),
        )

    @staticmethod
    def __tp_limit_prearm_ready(
        *,
        current_price: float,
        tp_price: float,
        margin_percent: float,
    ) -> bool:
        """Return whether price is close enough to TP to arm a standing limit."""
        if tp_price <= 0:
            return False
        arm_price = tp_price * (1 - (max(0.0, margin_percent) / 100.0))
        return current_price >= arm_price

    def __tp_limit_prearm_supported(
        self,
        runtime_config: DcaRuntimeConfigView,
        *,
        is_unsellable: bool,
    ) -> bool:
        """Return whether the current config supports proactive TP limit arming."""
        sell_order_type = str(
            (self.config or {}).get("sell_order_type", "market")
        ).lower()
        return (
            bool(runtime_config.tp_limit_prearm_enabled)
            and sell_order_type == "limit"
            and runtime_config.trailing_tp <= 0
            and not runtime_config.tp_strategy
            and not runtime_config.tp_spike_confirm_enabled
            and not is_unsellable
        )

    @staticmethod
    def __tp_limit_order_outdated(
        trades: dict[str, Any],
        *,
        tp_price: float,
        total_amount: float,
    ) -> bool:
        """Return whether a standing TP limit no longer matches the trade."""
        order_id = str(trades.get("tp_limit_order_id") or "").strip()
        if not order_id:
            return False
        stored_price = float(trades.get("tp_limit_order_price") or 0.0)
        stored_amount = float(trades.get("tp_limit_order_amount") or 0.0)
        price_tolerance = max(abs(tp_price) * 1e-8, 1e-12)
        amount_tolerance = max(abs(total_amount) * 1e-8, 1e-12)
        return (
            abs(stored_price - tp_price) > price_tolerance
            or abs(stored_amount - total_amount) > amount_tolerance
        )

    async def __arm_tp_limit_order(
        self,
        *,
        trades: dict[str, Any],
        current_price: float,
        take_profit_price: float,
        actual_pnl: float,
    ) -> bool:
        """Place a proactive TP limit order at the exact TP price."""
        order = {
            "symbol": trades["symbol"],
            "direction": trades["direction"],
            "side": "sell",
            "type_sell": "order_sell",
            "sell_reason": "take_profit_prearm",
            "actual_pnl": actual_pnl,
            "total_cost": trades["total_cost"],
            "total_amount": trades["total_amount"],
            "current_price": current_price,
            "limit_price": take_profit_price,
            "tp_price": take_profit_price,
            "fallback_min_price": take_profit_price,
        }
        return await self.orders.arm_tp_limit_order(order, self.config or {})

    async def __dynamic_dca_strategy(self, symbol: str) -> tuple[bool, bool]:
        result = False
        payload_changed = True
        runtime_config = self.__runtime_config()

        if runtime_config.dca_strategy:
            strategy_timeframe = resolve_timeframe(self.config or {})
            dca_strategy_plugin = self.__get_strategy_plugin(
                runtime_config.dca_strategy,
                strategy_timeframe,
                "dca",
            )

            previous_payload = None
            if hasattr(dca_strategy_plugin, "_last_log_by_symbol"):
                state_map = getattr(dca_strategy_plugin, "_last_log_by_symbol")
                if isinstance(state_map, dict):
                    previous_payload = state_map.get(symbol)

            result = await dca_strategy_plugin.run(symbol, "buy")
            if hasattr(dca_strategy_plugin, "_last_log_by_symbol"):
                state_map = getattr(dca_strategy_plugin, "_last_log_by_symbol")
                if isinstance(state_map, dict):
                    current_payload = state_map.get(symbol)
                    payload_changed = current_payload != previous_payload

        return result, payload_changed

    def __tp_strategy(self, symbol: str) -> bool:
        result = False
        runtime_config = self.__runtime_config()

        if runtime_config.tp_strategy:
            strategy_timeframe = resolve_timeframe(self.config or {})
            tp_strategy_plugin = self.__get_strategy_plugin(
                runtime_config.tp_strategy,
                strategy_timeframe,
                "tp",
            )

            token, currency = symbol.split("/")
            symbol = f"{token}{currency}"

            result = tp_strategy_plugin.run(symbol, "sell")

        return result

    def __get_strategy_plugin(self, name: str, timeframe: str, kind: str) -> object:
        ensure_strategy_supported(name)
        cache_key = (kind, name, timeframe)
        cached = self._strategy_cache.get(cache_key)
        if cached:
            return cached

        module = importlib.import_module(f"strategies.{name}")
        plugin = module.Strategy(timeframe=timeframe)
        self._strategy_cache[cache_key] = plugin
        return plugin

    async def __resolve_safety_order_size(
        self,
        trades: dict[str, Any],
        current_price: float,
        actual_pnl: float,
        volume_scale: float,
        so_index: int,
        threshold_percentage: float,
        dynamic_dca: bool,
    ) -> tuple[float, dict[str, float | str]]:
        runtime_config = self.__runtime_config()
        if dynamic_dca:
            return await self.__resolve_dynamic_dca_safety_order_size(
                trades=trades,
                current_price=current_price,
                actual_pnl=actual_pnl,
                so_index=so_index,
                threshold_percentage=threshold_percentage,
            )

        base_size = runtime_config.safety_order_size
        if trades["safetyorders"]:
            base_size = float(trades["safetyorders"][-1]["ordersize"]) * volume_scale
        final_size = round(base_size, 8)

        return final_size, {
            "base_size": round(base_size, 8),
            "final_size": final_size,
            "enabled": "false",
        }

    async def __resolve_dynamic_dca_safety_order_size(
        self,
        trades: dict[str, Any],
        current_price: float,
        actual_pnl: float,
        so_index: int,
        threshold_percentage: float,
    ) -> tuple[float, dict[str, float | str]]:
        runtime_config = self.__runtime_config()
        base_cost = runtime_config.base_order_amount
        if base_cost <= 0:
            return 0.0, {
                "error": "Dynamic DCA requires a positive base order amount (bo).",
                "skip": "true",
            }

        loss_factor = 1 + min(abs(actual_pnl) / 20.0, 2.0)
        threshold_delta = threshold_percentage - actual_pnl
        threshold_factor = 1.0
        if threshold_delta > 0:
            threshold_factor += min(threshold_delta / 10.0, 1.0)

        ath, window = await self.ath_service.get_recent_ath(
            symbol=trades["symbol"],
            config=self.config,
            cache_ttl_seconds=runtime_config.dynamic_dca_ath_cache_ttl,
        )
        if ath <= 0:
            ath = current_price
        ath_distance = max(0.0, (ath - current_price) / ath) if ath > 0 else 0.0
        ath_factor = 1 + ath_distance

        vol_factor, atr_details = await self.indicators.calculate_atr_regime_multiplier(
            symbol=trades["symbol"],
            timerange=runtime_config.atr_timeframe,
            config=self.config,
            length=runtime_config.atr_length,
            low_k=runtime_config.atr_regime_low_k,
            mid_k=runtime_config.atr_regime_mid_k,
            high_k=runtime_config.atr_regime_high_k,
        )

        progression_factor = 1 + min(max(so_index, 1) * 0.15, 0.75)

        raw_cost = (
            base_cost
            * loss_factor
            * threshold_factor
            * ath_factor
            * vol_factor
            * progression_factor
        )

        budget_ratio = runtime_config.trade_safety_order_budget_ratio
        if budget_ratio <= 0:
            budget_ratio = 0.95
        budget_ratio = min(budget_ratio, 1.0)

        free_quote_balance = await self.exchange.get_free_quote_balance(
            self.config,
            trades["symbol"],
        )
        if free_quote_balance is None:
            available_budget = raw_cost
        else:
            available_budget = free_quote_balance * budget_ratio

        final_cost = min(raw_cost, available_budget)
        final_cost = round(final_cost, 8)

        details: dict[str, float | str] = {
            "base_cost": round(base_cost, 8),
            "raw_cost": round(raw_cost, 8),
            "final_size": final_cost,
            "loss_factor": round(loss_factor, 6),
            "threshold_factor": round(threshold_factor, 6),
            "ath_factor": round(ath_factor, 6),
            "ath_distance": round(ath_distance, 6),
            "vol_factor": round(vol_factor, 6),
            "progression_factor": round(progression_factor, 6),
            "budget_ratio": round(budget_ratio, 6),
            "free_quote_balance": (
                round(float(free_quote_balance), 8)
                if free_quote_balance is not None
                else -1.0
            ),
            "available_budget": round(float(available_budget), 8),
            "threshold": round(float(threshold_percentage), 6),
            "window": window,
            "atr_regime": str(atr_details.get("regime", "mid")),
            "atr_percent": float(atr_details.get("atr_percent", 0.0)),
            "enabled": "true",
        }

        if final_cost < base_cost:
            details["skip"] = "true"
            details["error"] = (
                "Dynamic DCA SO skipped: final cost below base order amount."
            )

        return final_cost, details

    async def __calculate_tp(
        self,
        current_price: float,
        trades: dict[str, Any],
        trading_policy: ResolvedTradingPolicy,
    ) -> None:
        runtime_config = self.__runtime_config()
        trailing_tp = runtime_config.trailing_tp
        max_safety_orders = runtime_config.max_safety_orders
        sell = False
        sell_reason: str | None = None
        is_unsellable = bool(trades.get("is_unsellable", False))
        tp_confirmation_pending = False
        tp_confirmation_ticks = 0

        # Last sell fee has to be considered
        total_cost = trades["total_cost"] + (trades["total_cost"] * trades["fee"])
        average_buy_price = total_cost / trades["total_amount"]

        # Calculate TP/SL
        take_profit_price = average_buy_price * (1 + (trading_policy.take_profit / 100))
        stop_loss_price = average_buy_price * (1 - (trading_policy.stop_loss / 100))
        tp_reached = not is_unsellable and current_price >= take_profit_price
        prearm_supported = self.__tp_limit_prearm_supported(
            runtime_config,
            is_unsellable=is_unsellable,
        )

        if tp_reached and trailing_tp <= 0 and self.__tp_confirmation_enabled():
            trade_timestamp = int(float(trades["timestamp"]))
            sell = self.__evaluate_tp_confirmation(
                symbol=trades["symbol"],
                trade_timestamp=trade_timestamp,
                current_price=current_price,
                tp_price=take_profit_price,
            )
            tp_confirmation_pending = not sell
            if sell:
                sell_reason = "take_profit"
        elif tp_reached:
            self.__clear_tp_confirmation(
                trades["symbol"],
                reason="tp_confirmation_not_required",
                current_price=current_price,
                tp_price=take_profit_price,
            )
            sell = True
            sell_reason = "take_profit"
        elif trailing_tp <= 0:
            self.__clear_tp_confirmation(
                trades["symbol"],
                reason="price_fell_below_tp",
                current_price=current_price,
                tp_price=take_profit_price,
            )

        # Check if SL is reached
        if (
            not is_unsellable
            and current_price <= stop_loss_price
            and max_safety_orders == trades["safetyorders_count"]
        ):
            self.__clear_tp_confirmation(
                trades["symbol"],
                reason="stop_loss_triggered",
                current_price=current_price,
                tp_price=take_profit_price,
            )
            sell = True
            sell_reason = "stop_loss"

        # Actual PNL in percent (value for profit calculation)
        actual_pnl = self.utils.calculate_actual_pnl(trades, current_price)

        if await self.orders.reconcile_tp_limit_order(trades, self.config or {}):
            return

        has_tp_limit_order = bool(trades.get("tp_limit_order_id"))
        if has_tp_limit_order and (
            not prearm_supported
            or self.__tp_limit_order_outdated(
                trades,
                tp_price=take_profit_price,
                total_amount=float(trades["total_amount"]),
            )
        ):
            canceled = await self.orders.cancel_tp_limit_order(
                trades["symbol"],
                self.config or {},
            )
            if not canceled:
                return
            trades = {
                **trades,
                "tp_limit_order_id": None,
                "tp_limit_order_price": None,
                "tp_limit_order_amount": None,
                "tp_limit_order_armed_at": None,
            }
            has_tp_limit_order = False

        # TP strategy
        if not is_unsellable and runtime_config.tp_strategy and sell:
            logging.debug("Check if we should sell ...")
            if self.__tp_strategy(trades["symbol"]):
                sell = True
            else:
                sell = False
                sell_reason = None

        # Trailing TP
        if not is_unsellable and trailing_tp > 0:
            trailing_sell = apply_trailing_take_profit(
                self._trailing_tp_peaks,
                logger=logging,
                symbol=trades["symbol"],
                actual_pnl=actual_pnl,
                trailing_tp=trailing_tp,
                take_profit=trading_policy.take_profit,
                sell_signal=sell,
            )
            if trailing_sell and not sell:
                sell_reason = "trailing_take_profit"
            sell = trailing_sell

        # Sell if Autopilot is enabled and SL is set
        if not is_unsellable and trading_policy.stop_loss_timeout > 0:
            last_trade_date = datetime.fromtimestamp(
                int(float(trades["timestamp"]) / 1000)
            )
            trade_duration_max_date = datetime.now() - timedelta(
                days=trading_policy.stop_loss_timeout
            )
            if last_trade_date < trade_duration_max_date and actual_pnl >= -abs(
                trading_policy.stop_loss
            ):
                logging.debug(
                    "Selling %s because of autopilot settings.",
                    trades["symbol"],
                )
                self.__clear_tp_confirmation(
                    trades["symbol"],
                    reason="autopilot_timeout_triggered",
                    current_price=current_price,
                    tp_price=take_profit_price,
                )
                sell = True
                sell_reason = "autopilot_timeout"

        # TP reached - sell order (market)
        if sell:
            if has_tp_limit_order and sell_reason == "take_profit" and prearm_supported:
                logging.debug(
                    "TP reached for %s with proactive limit order already armed; "
                    "waiting for exchange fill reconciliation.",
                    trades["symbol"],
                )
                sell = False
            else:
                if has_tp_limit_order:
                    canceled = await self.orders.cancel_tp_limit_order(
                        trades["symbol"],
                        self.config or {},
                    )
                    if not canceled:
                        return
                    has_tp_limit_order = False
                self.__clear_tp_confirmation(
                    trades["symbol"],
                    reason="sell_submitted",
                    current_price=current_price,
                    tp_price=take_profit_price,
                )
                order = {
                    "symbol": trades["symbol"],
                    "direction": trades["direction"],
                    "side": "sell",
                    "type_sell": "order_sell",
                    "sell_reason": sell_reason,
                    "actual_pnl": actual_pnl,
                    "total_cost": trades["total_cost"],
                    "current_price": current_price,
                    "tp_price": take_profit_price,
                    "limit_price": (
                        take_profit_price
                        if sell_reason == "take_profit"
                        and str((self.config or {}).get("sell_order_type", "")).lower()
                        == "limit"
                        else None
                    ),
                    "fallback_min_price": (
                        take_profit_price
                        if current_price >= take_profit_price
                        else None
                    ),
                }
                await self.orders.receive_sell_order(order, self.config or {})
        elif (
            prearm_supported
            and not has_tp_limit_order
            and self.__tp_limit_prearm_ready(
                current_price=current_price,
                tp_price=take_profit_price,
                margin_percent=runtime_config.tp_limit_prearm_margin_percent,
            )
        ):
            has_tp_limit_order = await self.__arm_tp_limit_order(
                trades=trades,
                current_price=current_price,
                take_profit_price=take_profit_price,
                actual_pnl=actual_pnl,
            )

        if is_unsellable:
            logging.debug(
                "Skipping automated sell for %s due unsellable remainder (%s).",
                trades["symbol"],
                trades.get("unsellable_reason"),
            )

        tp_confirmation_pending, tp_confirmation_ticks = get_tp_confirmation_ticks(
            self._pending_tp_confirmations,
            trades["symbol"],
        )

        # Logging configuration
        logging_json = {
            "type": "tp_check",
            "symbol": trades["symbol"],
            "botname": trades["bot"],
            "total_cost": trades["total_cost"],
            "total_amount": trades["total_amount"],
            "current_price": current_price,
            "avg_price": average_buy_price,
            "tp_price": take_profit_price,
            "actual_pnl": actual_pnl,
            "sell": sell,
            "direction": trades["direction"],
            "autopilot_mode": trading_policy.mode,
            "adaptive_tp_applied": trading_policy.adaptive_tp_applied,
            "adaptive_reason_code": trading_policy.adaptive_reason_code,
            "adaptive_trust_score": trading_policy.adaptive_trust_score,
            "baseline_take_profit": trading_policy.baseline_take_profit,
            "unsellable": is_unsellable,
            "unsellable_reason": trades.get("unsellable_reason"),
            "tp_confirmation_pending": tp_confirmation_pending,
            "tp_confirmation_ticks": tp_confirmation_ticks,
            "tp_limit_order_id": trades.get("tp_limit_order_id"),
            "tp_limit_order_armed": has_tp_limit_order,
        }
        await self.statistic.update_statistic_data(logging_json)

    async def __calculate_dca(
        self, current_price: float, trades: dict[str, Any]
    ) -> None:
        runtime_config = self.__runtime_config()
        dynamic_dca = runtime_config.dynamic_dca
        volume_scale = runtime_config.safety_order_volume_scale
        if volume_scale <= 0:
            logging.warning(
                "Invalid safety order volume scale (os=%s). Falling back to 1.0.",
                volume_scale,
            )
            volume_scale = 1.0
        step_scale = runtime_config.step_scale
        max_safety_orders = runtime_config.max_safety_orders
        price_deviation = runtime_config.safety_order_step_percentage
        # Apply price deviation for the first safety order
        next_so_percentage = price_deviation
        trigger_threshold = -abs(next_so_percentage)
        safety_order_size = runtime_config.safety_order_size
        new_so = False
        placed_new_so = False
        dynamic_so_details: dict[str, float | str] = {"enabled": "false"}

        # Actual PNL in percent
        actual_pnl = self.utils.calculate_actual_pnl(trades, current_price)

        # Total PNL from base order
        total_pnl = ((current_price - trades["bo_price"]) / trades["bo_price"]) * 100

        max_deviation, actual_deviation = self.__calculate_deviations(
            step_scale, price_deviation, trades["safetyorders_count"]
        )

        so_context = self.__evaluate_existing_safety_orders(
            trades["safetyorders"],
            max_safety_orders,
            volume_scale,
            step_scale,
            price_deviation,
            safety_order_size,
            next_so_percentage,
            trigger_threshold,
        )
        last_so_price = so_context.last_so_price
        safety_order_size = so_context.safety_order_size
        next_so_percentage = so_context.next_so_percentage
        trigger_threshold = so_context.trigger_threshold

        # Dynamic DCA safety orders must progress deeper (more negative) than
        # the most recently persisted SO percentage to avoid rebound buys.
        last_so_percentage = so_context.last_so_percentage

        if max_safety_orders and (trades["safetyorders_count"] < max_safety_orders):
            new_so = False

            if dynamic_dca:
                new_so, next_so_percentage = await self.__evaluate_dynamic_dca_trigger(
                    trades, actual_pnl, trigger_threshold, last_so_percentage
                )
            else:
                new_so, trigger_threshold, next_so_percentage = (
                    self.__evaluate_static_dca_trigger(
                        total_pnl, max_deviation, actual_deviation
                    )
                )

            if new_so:
                (
                    safety_order_size,
                    dynamic_so_details,
                ) = await self.__resolve_safety_order_size(
                    trades=trades,
                    current_price=current_price,
                    actual_pnl=actual_pnl,
                    volume_scale=volume_scale,
                    so_index=trades["safetyorders_count"] + 1,
                    threshold_percentage=trigger_threshold,
                    dynamic_dca=bool(dynamic_dca),
                )
                if dynamic_so_details.get("skip") == "true":
                    logging.error(
                        "Skipping safety order for %s: %s",
                        trades["symbol"],
                        dynamic_so_details.get("error", "size resolution skipped"),
                    )
                    placed_new_so = False
                else:
                    order = {
                        "ordersize": safety_order_size,
                        "symbol": trades["symbol"],
                        "direction": trades["direction"],
                        "botname": trades["bot"],
                        "baseorder": False,
                        "safetyorder": True,
                        "order_count": trades["safetyorders_count"] + 1,
                        "ordertype": trades["ordertype"],
                        "so_percentage": next_so_percentage,
                        "side": "buy",
                    }
                    placed_new_so = await self.orders.receive_buy_order(
                        order, self.config
                    )

            # Logging configuration
            await self.__log_dca_check(
                trades=trades,
                placed_new_so=placed_new_so,
                last_so_price=last_so_price,
                safety_order_size=safety_order_size,
                next_so_percentage=next_so_percentage,
                actual_pnl=actual_pnl,
                dynamic_so_details=dynamic_so_details,
            )
        else:
            logging.info(
                "Max safety orders reached for %s (configured=%s, current=%s). "
                "Not opening more.",
                trades["symbol"],
                max_safety_orders,
                trades["safetyorders_count"],
            )

    def __calculate_deviations(
        self, step_scale: float, price_deviation: float, safetyorders_count: int
    ) -> tuple[float, float]:
        """Calculate max/actual deviation for static DCA progression."""
        return calculate_static_deviations(
            step_scale,
            price_deviation,
            safetyorders_count,
        )

    def __evaluate_existing_safety_orders(
        self,
        safetyorders: list[dict[str, Any]],
        max_safety_orders: int,
        volume_scale: float,
        step_scale: float,
        price_deviation: float,
        safety_order_size: float,
        next_so_percentage: float,
        trigger_threshold: float,
    ) -> SafetyOrderContext:
        """Derive SO context from already placed safety orders."""
        return derive_safety_order_context(
            safetyorders=safetyorders,
            max_safety_orders=max_safety_orders,
            volume_scale=volume_scale,
            step_scale=step_scale,
            price_deviation=price_deviation,
            safety_order_size=safety_order_size,
            next_so_percentage=next_so_percentage,
            trigger_threshold=trigger_threshold,
        )

    async def process_ticker_data(
        self, ticker: dict[str, Any], config: dict[str, Any]
    ) -> None:
        """Process incoming ticker data and trigger DCA actions."""
        # Get config
        self.config = config

        # New price action for DCA calculation
        if ticker["type"] == "ticker_price":
            price = ticker["ticker"]["price"]
            trades = await self.trades.get_trades_for_orders(ticker["ticker"]["symbol"])
            if trades:
                runtime_config = self.__runtime_config()

                # Check Autopilot
                profit = await self.statistic.get_profit()
                trading_policy = await self.autopilot.resolve_trading_policy(
                    trades["symbol"],
                    float(profit.get("funds_locked") or 0.0),
                    self.config,
                )

                # Check DCA (only when DCA is enabled)
                if runtime_config.dca_enabled and not trades.get(
                    "is_unsellable", False
                ):
                    await self.__calculate_dca(price, trades)

                # Check TP
                await self.__calculate_tp(price, trades, trading_policy)

    async def __evaluate_dynamic_dca_trigger(
        self,
        trades: dict[str, Any],
        actual_pnl: float,
        trigger_threshold: float,
        last_so_percentage: float | None,
    ) -> tuple[bool, float]:
        new_so = False
        next_so_percentage = last_so_percentage or trigger_threshold
        if actual_pnl <= trigger_threshold:
            strategy_result = await self.__dynamic_dca_strategy(trades["symbol"])
            payload_changed = True
            if isinstance(strategy_result, tuple):
                strategy_buy_signal, payload_changed = strategy_result
            else:
                strategy_buy_signal = bool(strategy_result)

            if strategy_buy_signal:
                if not payload_changed:
                    logging.debug(
                        "Skip dynamic SO for %s: strategy payload unchanged from previous evaluation.",
                        trades["symbol"],
                    )
                else:
                    normalized_actual_pnl = round(actual_pnl, 1)
                    if (
                        last_so_percentage is not None
                        and normalized_actual_pnl >= last_so_percentage
                    ):
                        logging.debug(
                            "Skip dynamic SO for %s: actual_pnl=%s (normalized=%s) is not deeper than last_so_percentage=%s",
                            trades["symbol"],
                            round(actual_pnl, 4),
                            round(normalized_actual_pnl, 4),
                            round(last_so_percentage, 4),
                        )
                    else:
                        next_so_percentage = normalized_actual_pnl
                        new_so = True
        return new_so, next_so_percentage

    def __evaluate_static_dca_trigger(
        self, total_pnl: float, max_deviation: float, actual_deviation: float
    ) -> tuple[bool, float, float]:
        return evaluate_static_dca_trigger(
            total_pnl,
            max_deviation,
            actual_deviation,
        )

    async def __log_dca_check(
        self,
        trades: dict[str, Any],
        placed_new_so: bool,
        last_so_price: float,
        safety_order_size: float,
        next_so_percentage: float,
        actual_pnl: float,
        dynamic_so_details: dict[str, Any],
    ) -> None:
        logging_json = {
            "type": "dca_check",
            "symbol": trades["symbol"],
            "botname": trades["bot"],
            "so_orders": trades["safetyorders_count"] + int(placed_new_so),
            "last_so_price": last_so_price,
            "new_so_size": safety_order_size,
            "price_deviation": next_so_percentage,
            "actual_pnl": actual_pnl,
            "new_so": placed_new_so,
            "dynamic_so_scale": dynamic_so_details.get("vol_factor", 1.0),
            "dynamic_so_window": dynamic_so_details.get("window", "off"),
            "dynamic_so_drawdown": dynamic_so_details.get("ath_distance", 0.0),
            "dynamic_so_loss": dynamic_so_details.get("loss_factor", 0.0),
        }
        await self.statistic.update_statistic_data(logging_json)
