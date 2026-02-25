"""DCA strategy handling and order logic."""

import importlib
from datetime import datetime, timedelta
from typing import Any

import helper
from service.ath import AthService
from service.autopilot import Autopilot
from service.config import resolve_timeframe
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

        # Class attributes
        Dca.pnl = {}

    async def __dynamic_dca_strategy(self, symbol: str) -> tuple[bool, bool]:
        result = False
        payload_changed = True

        if self.config.get("dca_strategy", None):
            strategy_timeframe = resolve_timeframe(self.config)
            dca_strategy_plugin = self.__get_strategy_plugin(
                self.config.get("dca_strategy"),
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

        if self.config.get("tp_strategy", None):
            strategy_timeframe = resolve_timeframe(self.config)
            tp_strategy_plugin = self.__get_strategy_plugin(
                self.config.get("tp_strategy"),
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
        if dynamic_dca:
            return await self.__resolve_dynamic_dca_safety_order_size(
                trades=trades,
                current_price=current_price,
                actual_pnl=actual_pnl,
                so_index=so_index,
                threshold_percentage=threshold_percentage,
            )

        configured_so_size = float(self.config.get("so", 0) or 0)
        base_size = configured_so_size
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
        base_cost = float(self.config.get("bo", 0.0) or 0.0)
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
            cache_ttl_seconds=int(self.config.get("dynamic_dca_ath_cache_ttl", 60)),
        )
        if ath <= 0:
            ath = current_price
        ath_distance = max(0.0, (ath - current_price) / ath) if ath > 0 else 0.0
        ath_factor = 1 + ath_distance

        atr_timeframe = str(
            self.config.get(
                "dynamic_so_atr_timeframe",
                self.config.get("dynamic_dca_ath_timeframe", "1h"),
            )
            or "1h"
        ).strip()
        atr_length = int(self.config.get("dynamic_so_atr_length", 14) or 14)
        low_k = float(self.config.get("dynamic_so_atr_regime_low_k", 2.2) or 2.2)
        mid_k = float(self.config.get("dynamic_so_atr_regime_mid_k", 1.8) or 1.8)
        high_k = float(self.config.get("dynamic_so_atr_regime_high_k", 1.4) or 1.4)
        vol_factor, atr_details = await self.indicators.calculate_atr_regime_multiplier(
            symbol=trades["symbol"],
            timerange=atr_timeframe,
            config=self.config,
            length=atr_length,
            low_k=low_k,
            mid_k=mid_k,
            high_k=high_k,
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

        budget_ratio = float(
            self.config.get("trade_safety_order_budget_ratio", 0.95) or 0.95
        )
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
        self, current_price: float, trades: dict[str, Any]
    ) -> None:
        trailing_tp = self.config.get("trailing_tp", 0)
        max_safety_orders = self.config.get("mstc", 0)
        sell = False

        # Last sell fee has to be considered
        total_cost = trades["total_cost"] + (trades["total_cost"] * trades["fee"])
        average_buy_price = total_cost / trades["total_amount"]

        # Calculate TP/SL
        take_profit_price = average_buy_price * (1 + (self.tp / 100))
        stop_loss_price = average_buy_price * (1 - (self.sl / 100))

        # Check if TP is reached
        if current_price >= take_profit_price:
            sell = True

        # Check if SL is reached
        if (
            current_price <= stop_loss_price
            and max_safety_orders == trades["safetyorders_count"]
        ):
            sell = True

        # Actual PNL in percent (value for profit calculation)
        actual_pnl = self.utils.calculate_actual_pnl(trades, current_price)

        # TP strategy
        if self.config.get("tp_strategy", None) and sell:
            logging.debug("Check if we should sell ...")
            if self.__tp_strategy(trades["symbol"]):
                sell = True
            else:
                sell = False

        # Trailing TP
        if trailing_tp > 0:
            if sell or trades["symbol"] in Dca.pnl:
                # Initialize new symbols
                if trades["symbol"] not in Dca.pnl:
                    Dca.pnl[trades["symbol"]] = 0.0

                if (
                    actual_pnl != Dca.pnl[trades["symbol"]]
                    and Dca.pnl[trades["symbol"]] != 0.0
                ):
                    diff = actual_pnl - Dca.pnl[trades["symbol"]]

                    logging.debug(
                        "TTP Check: %s - Actual PNL: %s, Top-PNL: %s, PNL Difference: %s",
                        trades["symbol"],
                        actual_pnl,
                        Dca.pnl[trades["symbol"]],
                        diff,
                    )

                    # Sell if trailing deviation is reached or actual PNL is under minimum TP
                    if (diff < 0 and abs(diff) > trailing_tp) or (
                        actual_pnl < self.tp and actual_pnl > trailing_tp
                    ):
                        logging.debug(
                            "TTP Sell: %s - Percentage decreased - Take profit with difference: %s",
                            trades["symbol"],
                            diff,
                        )
                        sell = True
                        Dca.pnl.pop(trades["symbol"])
                    else:
                        sell = False
                        if actual_pnl > Dca.pnl[trades["symbol"]]:
                            Dca.pnl[trades["symbol"]] = actual_pnl
                else:
                    Dca.pnl[trades["symbol"]] = actual_pnl
                    sell = False

        # Sell if Autopilot is enabled and SL is set
        if self.sl_timeout > 0:
            last_trade_date = datetime.fromtimestamp(
                int(float(trades["timestamp"]) / 1000)
            )
            trade_duration_max_date = datetime.now() - timedelta(days=self.sl_timeout)
            if last_trade_date < trade_duration_max_date and actual_pnl >= -abs(
                self.sl
            ):
                logging.debug(
                    "Selling %s because of autopilot settings.",
                    trades["symbol"],
                )
                sell = True

        # TP reached - sell order (market)
        if sell:
            order = {
                "symbol": trades["symbol"],
                "direction": trades["direction"],
                "side": "sell",
                "type_sell": "order_sell",
                "actual_pnl": actual_pnl,
                "total_cost": trades["total_cost"],
                "current_price": current_price,
                "tp_price": take_profit_price,
                "fallback_min_price": (
                    take_profit_price if current_price >= take_profit_price else None
                ),
            }
            await self.orders.receive_sell_order(order, self.config)

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
        }
        await self.statistic.update_statistic_data(logging_json)

    async def __calculate_dca(
        self, current_price: float, trades: dict[str, Any]
    ) -> None:
        dynamic_dca = self.config.get("dynamic_dca", False)
        volume_scale = float(self.config.get("os", 1.0) or 1.0)
        if volume_scale <= 0:
            logging.warning(
                "Invalid safety order volume scale (os=%s). Falling back to 1.0.",
                volume_scale,
            )
            volume_scale = 1.0
        step_scale = self.config.get("ss", 0)
        max_safety_orders = self.config.get("mstc", 0)
        price_deviation = self.config.get("sos")
        # Apply price deviation for the first safety order
        next_so_percentage = price_deviation
        trigger_threshold = -abs(next_so_percentage)
        safety_order_size = float(self.config.get("so", 0.0) or 0.0)
        new_so = False
        placed_new_so = False
        dynamic_so_details: dict[str, float | str] = {"enabled": "false"}

        # Actual PNL in percent
        actual_pnl = self.utils.calculate_actual_pnl(trades, current_price)

        # Total PNL from base order
        total_pnl = ((current_price - trades["bo_price"]) / trades["bo_price"]) * 100

        # Evaluate max deviation and actual deviation from base order
        if step_scale == 1:
            # If step scale equals 1
            max_deviation = price_deviation * (trades["safetyorders_count"] + 1)
            actual_deviation = price_deviation * trades["safetyorders_count"]
        else:
            # If step scale is other than 1
            max_deviation = (
                price_deviation * (1 - step_scale ** (trades["safetyorders_count"] + 1))
            ) / (1 - step_scale)
            max_deviation = round(max_deviation, 2)
            actual_deviation = (
                price_deviation * (1 - step_scale ** trades["safetyorders_count"])
            ) / (1 - step_scale)

        # Check if safety orders exist yet
        if trades["safetyorders"] and max_safety_orders:
            safety_order_size = trades["safetyorders"][-1]["ordersize"] * volume_scale
            next_so_percentage = (
                float(trades["safetyorders"][-1]["so_percentage"]) * step_scale
            )
            if len(trades["safetyorders"]) >= 2:
                next_so_percentage = -abs(next_so_percentage) + -abs(
                    float(trades["safetyorders"][-2]["so_percentage"])
                )
            else:
                next_so_percentage = -abs(next_so_percentage) + -abs(price_deviation)
            trigger_threshold = -abs(next_so_percentage)

            last_so_price = float(trades["safetyorders"][-1]["price"])
        else:
            last_so_price = 0

        # Dynamic DCA safety orders must progress deeper (more negative) than
        # the most recently persisted SO percentage to avoid rebound buys.
        last_so_percentage: float | None = None
        if trades["safetyorders"]:
            so_values = [
                float(so["so_percentage"])
                for so in trades["safetyorders"]
                if so.get("so_percentage") is not None
            ]
            if so_values:
                # Enforce progression against the deepest persisted SO percentage.
                # This is robust even when DB rows are not returned in timestamp order.
                last_so_percentage = min(so_values)

        # We have not reached the max safety orders
        if max_safety_orders and (trades["safetyorders_count"] < max_safety_orders):

            new_so = False

            if dynamic_dca:
                # Trigger new safety order for dynamic dca
                if actual_pnl <= trigger_threshold:
                    strategy_result = await self.__dynamic_dca_strategy(
                        trades["symbol"]
                    )
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
                            new_so = False
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
                                new_so = False
                            else:
                                # Set next_so_percentage to current percentage
                                next_so_percentage = normalized_actual_pnl
                                new_so = True
            else:
                # Trigger new safety order for static dca
                if total_pnl <= -abs(max_deviation):
                    # Set next_so_percentage to diffence between max deviation and actual deviation
                    next_so_percentage = max_deviation - actual_deviation
                    next_so_percentage = round(next_so_percentage, 2)
                    trigger_threshold = -abs(next_so_percentage)
                    new_so = True

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
            # Send new statistics to statistics module
            await self.statistic.update_statistic_data(logging_json)
        else:
            logging.info(
                "Max safety orders reached for %s (configured=%s, current=%s). "
                "Not opening more.",
                trades["symbol"],
                max_safety_orders,
                trades["safetyorders_count"],
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

                # Check Autopilot
                profit = await self.statistic.get_profit()
                trading_settings = None

                if profit["funds_locked"]:
                    trading_settings = await self.autopilot.calculate_trading_settings(
                        profit["funds_locked"], self.config
                    )
                # Use Autopilots settings
                if trading_settings:
                    self.tp = trading_settings["tp"]
                    self.sl = trading_settings["sl"]
                    self.sl_timeout = trading_settings["sl_timeout"]
                    self.autopilot_mode = trading_settings["mode"]
                # Use base settings
                else:
                    self.tp = self.config.get("tp", 10000)
                    self.sl = self.config.get("sl", 10000)
                    self.sl_timeout = 0
                    self.autopilot_mode = None

                # Check DCA (only when DCA is enabled)
                if self.config.get("dca", False):
                    await self.__calculate_dca(price, trades)

                # Check TP
                await self.__calculate_tp(price, trades)
