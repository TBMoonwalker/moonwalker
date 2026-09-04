"""DCA strategy handling and order logic."""

import asyncio
import json
from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import Any

import helper
from service.ath import AthService
from service.autopilot import Autopilot, ResolvedTradingPolicy
from service.config import resolve_timeframe
from service.config_views import (
    DcaRuntimeConfigView,
    SidestepCampaignConfigView,
    TradeLifecycleConfigView,
)
from service.dca_decision import (
    DcaAction,
    DcaEvaluationContext,
    ExitActionContext,
    SidestepExitContext,
    WaitingReentryContext,
    build_dca_evaluation_context,
    calculate_sidestep_exit_fallback_minimum_price,
    calculate_sidestep_reentry_maximum_price,
    evaluate_exit_action_decision,
    evaluate_recovery_trigger_decision,
    evaluate_sidestep_exit_decision,
    evaluate_static_dca_decision,
    evaluate_waiting_reentry_decision,
)
from service.dca_math import (
    calculate_average_entry_price,
    calculate_stop_loss_price,
    calculate_take_profit_price,
)
from service.dca_recovery_sizing import (
    LEGACY_SIZING_MODE,
    RECOVERY_SHADOW_MODE,
    RECOVERY_TARGET_MODE,
    RecoverySizingPolicy,
    calculate_recovery_execution_ceiling,
    calculate_recovery_execution_drift_percent,
    calculate_recovery_sizing,
    normalize_recovery_sizing_mode,
)
from service.dca_safety_orders import (
    SafetyOrderContext,
    calculate_static_deviations,
    derive_safety_order_context,
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
from service.lifecycle_snapshot import LifecycleSnapshotIdentity
from service.orders import Orders
from service.spot_campaign_types import TradeExposureState, TradeLifecycleMode
from service.spot_sidestep_campaign import SpotSidestepCampaignService
from service.statistic import Statistic
from service.strategy_runtime import get_strategy_adapter
from service.trades import Trades
from service.trading_controls import is_mission_automation_paused
from service.trading_maintenance import trading_maintenance_barrier

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
        self.sidestep_campaigns: SpotSidestepCampaignService | None = None
        self._config_snapshot: ContextVar[dict[str, Any] | None] = ContextVar(
            "moonwalker_dca_config_snapshot",
            default=None,
        )
        self._compat_config: dict[str, Any] | None = None
        self._strategy_cache: dict[tuple[str, str, str], object] = {}
        self._pending_tp_confirmations: dict[str, TpConfirmationState] = {}
        self._trailing_tp_peaks: dict[str, float] = {}
        self._last_sidestep_gate_by_symbol: dict[str, tuple[Any, ...]] = {}
        self._last_dynamic_strategy_identity_by_symbol: dict[
            str, tuple[str | None, int | None]
        ] = {}
        self._last_sidestep_exit_identity_by_symbol: dict[
            str, tuple[str | None, int | None]
        ] = {}
        self._last_sidestep_reentry_identity_by_symbol: dict[
            str, tuple[str | None, int | None]
        ] = {}

    async def shutdown(self) -> None:
        """Close exchange resources owned by the DCA runtime."""
        await self.exchange.close()
        await self.ath_service.close()
        await self.orders.close()

    @property
    def config(self) -> dict[str, Any] | None:
        """Return the task-local config or a direct-test compatibility value."""
        active = self._config_snapshot.get()
        return active if active is not None else self._compat_config

    @config.setter
    def config(self, value: dict[str, Any] | None) -> None:
        """Keep direct helper tests compatible without sharing runtime requests."""
        self._compat_config = value

    def __log_sidestep_gate(
        self,
        symbol: str,
        reason: str,
        **context: Any,
    ) -> None:
        """Log sidestep skip/gate reasons once per symbol state change."""
        normalized_symbol = str(symbol or "").strip()
        ordered_context = tuple(sorted(context.items()))
        gate_state = (reason, ordered_context)
        if self._last_sidestep_gate_by_symbol.get(normalized_symbol) == gate_state:
            return

        payload = {
            "symbol": normalized_symbol,
            "sidestep_gate": reason,
            **context,
        }
        logging.debug("Sidestep gate: %s", payload)
        self._last_sidestep_gate_by_symbol[normalized_symbol] = gate_state

    def __clear_sidestep_gate(self, symbol: str) -> None:
        """Forget the last sidestep gate state once evaluation can proceed."""
        normalized_symbol = str(symbol or "").strip()
        self._last_sidestep_gate_by_symbol.pop(normalized_symbol, None)

    @staticmethod
    def __strategy_identity_from_plugin(
        plugin: object,
        symbol: str,
        side: str,
        fallback_slug: str | None,
    ) -> tuple[str | None, int | None]:
        """Return the strategy identity that produced the latest adapter result."""
        identity_reader = getattr(plugin, "last_evaluation_identity", None)
        if callable(identity_reader):
            return identity_reader(symbol, side)
        return fallback_slug, None

    @staticmethod
    def __order_snapshot_payload(trades: dict[str, Any]) -> dict[str, Any]:
        """Return the evaluated identity for execution-bound order requests."""
        snapshot = trades.get("_lifecycle_snapshot")
        if not isinstance(snapshot, LifecycleSnapshotIdentity):
            return {}
        return {"lifecycle_snapshot": snapshot.to_dict()}

    def __get_monotonic_time(self) -> float:
        """Return a monotonic timestamp for TP confirmation timing."""
        return asyncio.get_running_loop().time()

    async def _get_sidestep_campaigns(self) -> SpotSidestepCampaignService:
        """Return the shared sidestep campaign service instance."""
        if self.sidestep_campaigns is None:
            self.sidestep_campaigns = await SpotSidestepCampaignService.instance()
        return self.sidestep_campaigns

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
        sellable_amount = float(
            trades.get("sellable_amount") or trades.get("total_amount") or 0.0
        )
        order = {
            "symbol": trades["symbol"],
            "direction": trades["direction"],
            "side": "sell",
            "type_sell": "order_sell",
            "sell_reason": "take_profit_prearm",
            "actual_pnl": actual_pnl,
            "total_cost": trades["total_cost"],
            "total_amount": sellable_amount,
            "current_price": current_price,
            "limit_price": take_profit_price,
            "tp_price": take_profit_price,
            "fallback_min_price": take_profit_price,
            **self.__order_snapshot_payload(trades),
        }
        return await self.orders.arm_tp_limit_order(order, self.config or {})

    async def __dynamic_dca_strategy(self, symbol: str) -> tuple[bool, bool]:
        result = False
        payload_changed = True
        runtime_config = self.__runtime_config()

        if runtime_config.dca_strategy:
            strategy_timeframe = resolve_timeframe(self.config or {})
            dca_strategy_plugin = await self.__get_strategy_plugin(
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
            self._last_dynamic_strategy_identity_by_symbol[symbol] = (
                self.__strategy_identity_from_plugin(
                    dca_strategy_plugin,
                    symbol,
                    "buy",
                    runtime_config.dca_strategy,
                )
            )
            if hasattr(dca_strategy_plugin, "_last_log_by_symbol"):
                state_map = getattr(dca_strategy_plugin, "_last_log_by_symbol")
                if isinstance(state_map, dict):
                    current_payload = state_map.get(symbol)
                    payload_changed = current_payload != previous_payload

        return result, payload_changed

    async def __sidestep_exit_strategy(self, symbol: str) -> bool:
        """Return whether the configured bearish sidestep strategy wants to exit."""
        sidestep_campaigns = await self._get_sidestep_campaigns()
        if not sidestep_campaigns.is_enabled(self.config):
            return False

        bearish_strategy_name = str(
            (self.config or {}).get("sidestep_bearish_strategy") or ""
        ).strip()
        if not bearish_strategy_name:
            return False

        strategy_timeframe = resolve_timeframe(self.config or {})
        sidestep_config = SidestepCampaignConfigView.from_config(self.config or {})
        sidestep_strategy_plugin = await self.__get_strategy_plugin(
            bearish_strategy_name,
            strategy_timeframe,
            "sidestep_exit",
        )
        result = bool(
            await sidestep_strategy_plugin.run(
                symbol,
                "sell",
                candle_index=-2 if sidestep_config.confirm_closed_candle else None,
            )
        )
        self._last_sidestep_exit_identity_by_symbol[symbol] = (
            self.__strategy_identity_from_plugin(
                sidestep_strategy_plugin,
                symbol,
                "sell",
                bearish_strategy_name,
            )
        )
        return result

    async def __sidestep_reentry_strategy(self, symbol: str) -> bool:
        """Return whether the configured sidestep re-entry strategy wants to rebuy."""
        sidestep_campaigns = await self._get_sidestep_campaigns()
        if not sidestep_campaigns.is_enabled(self.config):
            return False

        reentry_strategy_name = SidestepCampaignConfigView.from_config(
            self.config or {}
        ).reentry_strategy
        if not reentry_strategy_name:
            return False

        strategy_timeframe = resolve_timeframe(self.config or {})
        sidestep_config = SidestepCampaignConfigView.from_config(self.config or {})
        reentry_strategy_plugin = await self.__get_strategy_plugin(
            reentry_strategy_name,
            strategy_timeframe,
            "sidestep_reentry",
        )
        result = bool(
            await reentry_strategy_plugin.run(
                symbol,
                "buy",
                candle_index=-2 if sidestep_config.confirm_closed_candle else None,
            )
        )
        self._last_sidestep_reentry_identity_by_symbol[symbol] = (
            self.__strategy_identity_from_plugin(
                reentry_strategy_plugin,
                symbol,
                "buy",
                reentry_strategy_name,
            )
        )
        return result

    @staticmethod
    def __is_sidestep_mode(trades: dict[str, Any]) -> bool:
        """Return whether the active trade is running in sidestep mode."""
        return (
            str(trades.get("lifecycle_mode") or "")
            == TradeLifecycleMode.SIDESTEP_REENTRY.value
        )

    @staticmethod
    def __is_flat_waiting(trades: dict[str, Any]) -> bool:
        """Return whether the active trade is alive but currently flat."""
        return (
            str(trades.get("exposure_state") or "")
            == TradeExposureState.FLAT_WAITING_REENTRY.value
        )

    async def __update_waiting_virtual_metrics(
        self,
        trades: dict[str, Any],
        current_price: float,
    ) -> None:
        """Persist virtual sidestep waiting metrics for the active-flat mission."""
        waiting_reference_amount = float(trades.get("waiting_reference_amount") or 0.0)
        waiting_reference_quote = float(trades.get("waiting_reference_quote") or 0.0)
        waiting_reference_price = float(trades.get("waiting_reference_price") or 0.0)
        virtual_profit = waiting_reference_quote - (
            current_price * waiting_reference_amount
        )
        virtual_profit_percent = (
            ((waiting_reference_price - current_price) / waiting_reference_price) * 100
            if waiting_reference_price > 0
            else 0.0
        )
        reserved_reentry_quote = float(
            trades.get("reserved_reentry_quote") or waiting_reference_quote
        )
        await self.trades.update_open_trades(
            {
                "current_price": current_price,
                "virtual_waiting_profit": virtual_profit,
                "virtual_waiting_profit_percent": virtual_profit_percent,
                "waiting_reference_price": waiting_reference_price,
                "waiting_reference_amount": waiting_reference_amount,
                "waiting_reference_quote": waiting_reference_quote,
                "reserved_reentry_quote": reserved_reentry_quote,
                "profit": 0.0,
                "profit_percent": 0.0,
                "amount": 0.0,
                "cost": 0.0,
            },
            trades["symbol"],
        )
        await self.statistic.update_statistic_data(
            {
                "type": "waiting_check",
                "symbol": trades["symbol"],
                "botname": trades.get("bot"),
                "current_price": current_price,
                "waiting_reference_price": waiting_reference_price,
                "waiting_reference_amount": waiting_reference_amount,
                "waiting_reference_quote": waiting_reference_quote,
                "virtual_waiting_profit": virtual_profit,
                "virtual_waiting_profit_percent": virtual_profit_percent,
                "reserved_reentry_quote": reserved_reentry_quote,
                "campaign_id": trades.get("campaign_id"),
                "lifecycle_mode": trades.get("lifecycle_mode"),
                "exposure_state": trades.get("exposure_state"),
            }
        )

    async def __attempt_waiting_reentry(
        self,
        trades: dict[str, Any],
        current_price: float,
    ) -> bool:
        """Place a sidestep re-entry buy from the watcher-owned lifecycle loop."""
        preflight_action, preflight_reason = evaluate_waiting_reentry_decision(
            WaitingReentryContext(
                is_sidestep_mode=self.__is_sidestep_mode(trades),
                is_flat_waiting=self.__is_flat_waiting(trades),
                has_campaign_id=bool(trades.get("campaign_id")),
                campaign_found=None,
                cooldown_active=False,
                strategy_signal=None,
                order_size=0.0,
            )
        )
        if preflight_reason != "waiting_campaign_lookup_required":
            if preflight_reason == "waiting_missing_campaign":
                self.__log_sidestep_gate(
                    trades["symbol"],
                    preflight_reason,
                )
            return False
        assert preflight_action is DcaAction.WAIT

        sidestep_campaigns = await self._get_sidestep_campaigns()
        campaign = await sidestep_campaigns.get_campaign_snapshot(
            str(trades.get("campaign_id") or "")
        )
        if campaign is None:
            self.__log_sidestep_gate(
                trades["symbol"],
                "waiting_campaign_not_found",
                campaign_id=str(trades.get("campaign_id") or ""),
            )
            return False

        cooldown_active = False
        cooldown_until = campaign.get("cooldown_until")
        if cooldown_until:
            try:
                cooldown_active = (
                    datetime.fromisoformat(str(cooldown_until).replace("Z", "+00:00"))
                    > datetime.now().astimezone()
                )
            except ValueError:
                pass

        sidestep_config = SidestepCampaignConfigView.from_config(self.config or {})
        has_fresh_long_signal = self.__has_fresh_long_signal(campaign)

        strategy_gate_action, strategy_gate_reason = evaluate_waiting_reentry_decision(
            WaitingReentryContext(
                is_sidestep_mode=True,
                is_flat_waiting=True,
                has_campaign_id=True,
                campaign_found=True,
                cooldown_active=cooldown_active,
                strategy_signal=None,
                order_size=0.0,
                requires_fresh_long_signal=(
                    sidestep_config.reentry_requires_fresh_long_signal
                ),
                has_fresh_long_signal=has_fresh_long_signal,
            )
        )
        if strategy_gate_reason != "sidestep_reentry_strategy_required":
            if strategy_gate_reason == "waiting_cooldown_active":
                self.__log_sidestep_gate(
                    trades["symbol"],
                    strategy_gate_reason,
                    cooldown_until=str(cooldown_until),
                )
            elif strategy_gate_reason == "waiting_fresh_long_signal_required":
                self.__log_sidestep_gate(
                    trades["symbol"],
                    strategy_gate_reason,
                    campaign_id=str(trades.get("campaign_id") or ""),
                )
            return False
        assert strategy_gate_action is DcaAction.WAIT

        self.__clear_sidestep_gate(trades["symbol"])
        strategy_signal = await self.__sidestep_reentry_strategy(trades["symbol"])

        order_size = float(
            trades.get("reserved_reentry_quote")
            or campaign.get("reserved_quote")
            or float((self.config or {}).get("bo") or 0.0)
        )
        reentry_action, reentry_reason = evaluate_waiting_reentry_decision(
            WaitingReentryContext(
                is_sidestep_mode=True,
                is_flat_waiting=True,
                has_campaign_id=True,
                campaign_found=True,
                cooldown_active=False,
                strategy_signal=strategy_signal,
                order_size=order_size,
                current_price=current_price,
                waiting_reference_price=float(
                    trades.get("waiting_reference_price") or 0.0
                ),
                max_reentry_premium_pct=sidestep_config.reentry_max_premium_pct,
                requires_fresh_long_signal=(
                    sidestep_config.reentry_requires_fresh_long_signal
                ),
                has_fresh_long_signal=has_fresh_long_signal,
            )
        )
        if reentry_action is not DcaAction.PLACE_REENTRY_BUY:
            if reentry_reason in {
                "waiting_missing_reserved_quote",
                "waiting_reentry_reference_price_required",
                "waiting_reentry_price_above_limit",
            }:
                self.__log_sidestep_gate(
                    trades["symbol"],
                    reentry_reason,
                    campaign_id=str(trades.get("campaign_id") or ""),
                    current_price=round(current_price, 8),
                    waiting_reference_price=round(
                        float(trades.get("waiting_reference_price") or 0.0),
                        8,
                    ),
                )
            return False

        reentry_strategy_name = SidestepCampaignConfigView.from_config(
            self.config or {}
        ).reentry_strategy
        reentry_identity = self._last_sidestep_reentry_identity_by_symbol.get(
            trades["symbol"],
            (reentry_strategy_name, None),
        )

        logging.info(
            "Sidestep re-entry triggered for %s: campaign=%s reserved_quote=%s "
            "current_price=%s strategy=%s.",
            trades["symbol"],
            trades.get("campaign_id"),
            order_size,
            current_price,
            reentry_strategy_name,
        )
        order = {
            "ordersize": order_size,
            "symbol": trades["symbol"],
            "direction": "long",
            "botname": str(trades.get("bot") or f"sidestep_{trades['symbol']}"),
            "baseorder": True,
            "safetyorder": False,
            "order_count": 0,
            "ordertype": "market",
            "so_percentage": None,
            "side": "buy",
            "current_price": current_price,
            "maximum_buy_price": calculate_sidestep_reentry_maximum_price(
                float(trades.get("waiting_reference_price") or 0.0),
                sidestep_config.reentry_max_premium_pct,
            ),
            "campaign_id": trades.get("campaign_id"),
            "signal_name": None,
            "strategy_name": reentry_strategy_name,
            "strategy_slug": reentry_identity[0] or reentry_strategy_name,
            "strategy_version": reentry_identity[1],
            "timeframe": resolve_timeframe(self.config or {}),
            "metadata_json": None,
            **self.__order_snapshot_payload(trades),
        }
        success = await self.orders.receive_buy_order(order, self.config or {})
        if success:
            logging.info(
                "Sidestep re-entry buy submitted for %s: campaign=%s.",
                trades["symbol"],
                trades.get("campaign_id"),
            )
        else:
            logging.warning(
                "Sidestep re-entry buy rejected for %s: campaign=%s.",
                trades["symbol"],
                trades.get("campaign_id"),
            )
        return success

    @staticmethod
    def __has_fresh_long_signal(campaign: dict[str, Any]) -> bool:
        """Return whether a recorded long signal arrived after the sidestep exit."""
        try:
            metadata = json.loads(str(campaign.get("metadata_json") or "{}"))
            if not isinstance(metadata, dict):
                return False
            long_signal_at = str(metadata.get("last_long_signal_at") or "")
            exit_at = str(metadata.get("last_exit_at") or "")
            if not long_signal_at or not exit_at:
                return False
            return datetime.fromisoformat(long_signal_at.replace("Z", "+00:00")) > (
                datetime.fromisoformat(exit_at.replace("Z", "+00:00"))
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            return False

    async def __tp_strategy(self, symbol: str) -> bool:
        result = False
        runtime_config = self.__runtime_config()

        if runtime_config.tp_strategy:
            strategy_timeframe = resolve_timeframe(self.config or {})
            tp_strategy_plugin = await self.__get_strategy_plugin(
                runtime_config.tp_strategy,
                strategy_timeframe,
                "tp",
            )

            token, currency = symbol.split("/")
            symbol = f"{token}{currency}"

            result = await tp_strategy_plugin.run(symbol, "sell")

        return result

    async def __get_strategy_plugin(
        self,
        name: str,
        timeframe: str,
        kind: str,
    ) -> object:
        cache_key = (kind, name, timeframe)
        cached = self._strategy_cache.get(cache_key)
        if cached:
            return cached

        plugin = await get_strategy_adapter(name, timeframe)
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

    def __get_recovery_policy(
        self,
        trades: dict[str, Any],
    ) -> RecoverySizingPolicy:
        """Return the immutable recovery policy snapshotted for this deal."""
        mode = normalize_recovery_sizing_mode(trades.get("dca_sizing_mode"))
        raw_policy = trades.get("dca_policy_json")
        parsed_policy: dict[str, Any] = {}
        if isinstance(raw_policy, str) and raw_policy.strip():
            try:
                candidate = json.loads(raw_policy)
            except json.JSONDecodeError:
                candidate = {}
            if isinstance(candidate, dict):
                parsed_policy = candidate
        elif isinstance(raw_policy, dict):
            parsed_policy = dict(raw_policy)
        parsed_policy["mode"] = mode
        return RecoverySizingPolicy.from_dict(parsed_policy)

    async def __get_recovery_atr_percent(
        self,
        symbol: str,
        policy: RecoverySizingPolicy,
    ) -> tuple[float, dict[str, float | str]]:
        """Return the current ATR percentage used by recovery DCA."""
        runtime_config = self.__runtime_config()
        _multiplier, details = await self.indicators.calculate_atr_regime_multiplier(
            symbol=symbol,
            timerange=policy.atr_timeframe,
            config=self.config,
            length=policy.atr_length,
            low_k=runtime_config.atr_regime_low_k,
            mid_k=runtime_config.atr_regime_mid_k,
            high_k=runtime_config.atr_regime_high_k,
        )
        return max(0.0, float(details.get("atr_percent", 0.0))), details

    async def __persist_recovery_dca_diagnostics(
        self,
        trades: dict[str, Any],
        details: dict[str, Any],
    ) -> None:
        """Persist a changed recovery decision without writing on every tick."""
        existing: dict[str, Any] = {}
        raw_existing = trades.get("dca_last_decision_json")
        if isinstance(raw_existing, str) and raw_existing.strip():
            try:
                candidate = json.loads(raw_existing)
            except json.JSONDecodeError:
                candidate = {}
            if isinstance(candidate, dict):
                existing = candidate

        stable_keys = (
            "mode",
            "reason",
            "reference_atr_percent",
            "reference_price",
            "spacing_percent",
            "trigger_price",
        )
        if existing and all(
            existing.get(key) == details.get(key) for key in stable_keys
        ):
            return

        await self.trades.update_open_trades(
            {"dca_last_decision_json": json.dumps(details, sort_keys=True)},
            trades["symbol"],
        )

    async def __evaluate_recovery_dca_trigger(
        self,
        trades: dict[str, Any],
        current_price: float,
        actual_pnl: float,
        policy: RecoverySizingPolicy,
        context: DcaEvaluationContext | None = None,
    ) -> tuple[bool, float, dict[str, Any]]:
        """Evaluate ATR spacing and the configured fresh recovery signal."""
        if context is None:
            context = build_dca_evaluation_context(
                trade=trades,
                config=self.config or {},
                current_price=current_price,
                decision_timestamp_ms=int(datetime.now().timestamp() * 1000),
                persisted_policy=policy,
                strategy_name=self.__runtime_config().dca_strategy or None,
                strategy_timeframe=resolve_timeframe(self.config or {}),
                replay_identity=str(trades.get("deal_id") or "") or None,
            )
        atr_percent, atr_details = await self.__get_recovery_atr_percent(
            trades["symbol"],
            policy,
        )
        reference_price = float(trades.get("dca_reference_price") or 0.0)
        if reference_price <= 0:
            if trades.get("safetyorders"):
                reference_price = float(trades["safetyorders"][-1]["price"])
            else:
                reference_price = float(trades.get("bo_price") or 0.0)
        reference_atr_percent = float(trades.get("dca_reference_atr_percent") or 0.0)
        if reference_atr_percent <= 0:
            reference_atr_percent = atr_percent

        preliminary_decision = evaluate_recovery_trigger_decision(
            context,
            reference_price=reference_price,
            reference_atr_percent=reference_atr_percent,
            execution_atr_percent=atr_percent,
            strategy_signal=True,
            strategy_payload_changed=True,
        )
        spacing_percent = float(preliminary_decision.spacing_percent or 0.0)
        trigger_price = float(preliminary_decision.trigger_price or 0.0)
        details: dict[str, Any] = {
            "enabled": "true",
            "mode": policy.mode,
            "atr_percent": atr_percent,
            "atr_regime": str(atr_details.get("regime", "mid")),
            "reference_atr_percent": reference_atr_percent,
            "reference_price": reference_price,
            "spacing_percent": spacing_percent,
            "trigger_price": trigger_price,
            "current_price": current_price,
            "actual_pnl": actual_pnl,
        }

        persisted_trigger = float(trades.get("dca_next_trigger_price") or 0.0)
        persisted_reference_atr = float(trades.get("dca_reference_atr_percent") or 0.0)
        if (
            abs(persisted_trigger - trigger_price) > 1e-12
            or persisted_reference_atr <= 0
        ):
            updated_policy_state = {
                "dca_reference_price": reference_price,
                "dca_reference_atr_percent": reference_atr_percent,
                "dca_next_trigger_price": trigger_price,
            }
            await self.trades.update_open_trades(
                updated_policy_state,
                trades["symbol"],
            )
            trades.update(updated_policy_state)
            if isinstance(
                trades.get("_lifecycle_snapshot"),
                LifecycleSnapshotIdentity,
            ):
                trades["_lifecycle_snapshot"] = LifecycleSnapshotIdentity.from_trade(
                    trades,
                    self.config or {},
                )

        if preliminary_decision.reason_code in {
            "missing_deal_budget",
            "waiting_for_atr_spacing",
        }:
            details["reason"] = preliminary_decision.reason_code
            await self.__persist_recovery_dca_diagnostics(trades, details)
            return False, round(actual_pnl, 1), details

        strategy_result = await self.__dynamic_dca_strategy(trades["symbol"])
        payload_changed = True
        if isinstance(strategy_result, tuple):
            strategy_buy_signal, payload_changed = strategy_result
        else:
            strategy_buy_signal = bool(strategy_result)
        decision = evaluate_recovery_trigger_decision(
            context,
            reference_price=reference_price,
            reference_atr_percent=reference_atr_percent,
            execution_atr_percent=atr_percent,
            strategy_signal=strategy_buy_signal,
            strategy_payload_changed=payload_changed,
        )
        details["reason"] = decision.reason_code
        if not decision.should_place:
            await self.__persist_recovery_dca_diagnostics(trades, details)
            return False, round(actual_pnl, 1), details

        return True, round(actual_pnl, 1), details

    async def __resolve_recovery_safety_order_size(
        self,
        trades: dict[str, Any],
        current_price: float,
        policy: RecoverySizingPolicy,
        trigger_details: dict[str, Any],
    ) -> tuple[float, dict[str, Any]]:
        """Size a recovery SO to place TP within an ATR-derived rebound."""
        runtime_config = self.__runtime_config()
        free_quote_balance = await self.exchange.get_free_quote_balance(
            self.config or {},
            trades["symbol"],
        )
        budget_ratio = min(
            1.0,
            max(0.0, runtime_config.trade_safety_order_budget_ratio or 0.95),
        )
        maximum_available_quote = (
            float(free_quote_balance) * budget_ratio
            if free_quote_balance is not None
            else None
        )
        maximum_buy_price = 0.0
        if policy.execution_guard_enabled:
            execution_atr_percent = float(trigger_details.get("atr_percent") or 0.0)
            execution_trigger_price = float(trigger_details.get("trigger_price") or 0.0)
            maximum_buy_price = calculate_recovery_execution_ceiling(
                execution_trigger_price,
                execution_atr_percent,
                policy,
            )
        minimum_order_quote = await self.exchange.get_minimum_buy_notional(
            self.config or {},
            trades["symbol"],
            is_market_order=maximum_buy_price <= 0,
            amount_sizing_price=maximum_buy_price or current_price,
        )
        sizing = calculate_recovery_sizing(
            total_cost=float(trades.get("total_cost") or 0.0),
            total_amount=float(trades.get("total_amount") or 0.0),
            fill_price=current_price,
            take_profit_percent=runtime_config.take_profit,
            fee_ratio=float(trades.get("fee") or 0.0),
            atr_percent=float(trigger_details.get("atr_percent") or 0.0),
            policy=policy,
            minimum_order_quote=float(minimum_order_quote or 0.0),
            maximum_available_quote=maximum_available_quote,
        )
        details = {
            **trigger_details,
            **sizing.to_dict(),
            "mode": policy.mode,
            "minimum_order_quote": float(minimum_order_quote or 0.0),
            "free_quote_balance": (
                float(free_quote_balance) if free_quote_balance is not None else -1.0
            ),
            "budget_ratio": budget_ratio,
            "final_size": round(float(sizing.final_quote), 8),
            "skip": "false" if sizing.should_place else "true",
            "error": "" if sizing.should_place else sizing.reason,
        }
        await self.trades.update_open_trades(
            {
                "dca_last_decision_json": json.dumps(details, sort_keys=True),
            },
            trades["symbol"],
        )
        return round(float(sizing.final_quote), 8), details

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

        total_cost = trades["total_cost"] + (trades["total_cost"] * trades["fee"])
        average_buy_price = calculate_average_entry_price(
            trades["total_cost"],
            trades["fee"],
            trades["total_amount"],
        )

        # Calculate TP/SL
        take_profit_price = calculate_take_profit_price(
            average_buy_price,
            trading_policy.take_profit,
        )
        if self.__is_sidestep_mode(trades) and trades.get("campaign_id"):
            sidestep_campaigns = await self._get_sidestep_campaigns()
            campaign = await sidestep_campaigns.get_campaign_snapshot(
                str(trades.get("campaign_id") or "")
            )
            if campaign is not None:
                principal_quote = float(campaign.get("principal_quote") or total_cost)
                cumulative_realized_quote = float(
                    campaign.get("cumulative_realized_quote") or 0.0
                )
                tp_target_percent = float(
                    campaign.get("tp_percent") or trading_policy.take_profit or 0.0
                )
                required_unrealized_quote = (
                    principal_quote * (tp_target_percent / 100.0)
                ) - cumulative_realized_quote
                if trades["total_amount"] > 0:
                    take_profit_price = (
                        required_unrealized_quote + total_cost
                    ) / trades["total_amount"]
        stop_loss_price = calculate_stop_loss_price(
            average_buy_price,
            trading_policy.stop_loss,
        )
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

        expected_snapshot = trades.get("_lifecycle_snapshot")
        if not isinstance(expected_snapshot, LifecycleSnapshotIdentity):
            expected_snapshot = None
        if expected_snapshot is None:
            reconciled = await self.orders.reconcile_tp_limit_order(
                trades,
                self.config or {},
            )
        else:
            reconciled = await self.orders.reconcile_tp_limit_order(
                trades,
                self.config or {},
                expected_snapshot=expected_snapshot,
            )
        if reconciled:
            return

        sellable_amount = float(
            trades.get("sellable_amount") or trades.get("total_amount") or 0.0
        )
        has_tp_limit_order = bool(trades.get("tp_limit_order_id"))
        if has_tp_limit_order and (
            not prearm_supported
            or self.__tp_limit_order_outdated(
                trades,
                tp_price=take_profit_price,
                total_amount=sellable_amount,
            )
        ):
            if expected_snapshot is None:
                canceled = await self.orders.cancel_tp_limit_order(
                    trades["symbol"],
                    self.config or {},
                )
            else:
                canceled = await self.orders.cancel_tp_limit_order(
                    trades["symbol"],
                    self.config or {},
                    expected_snapshot=expected_snapshot,
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
            if await self.__tp_strategy(trades["symbol"]):
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

        prearm_ready = (
            not sell
            and prearm_supported
            and not has_tp_limit_order
            and self.__tp_limit_prearm_ready(
                current_price=current_price,
                tp_price=take_profit_price,
                margin_percent=runtime_config.tp_limit_prearm_margin_percent,
            )
        )
        exit_action, exit_reason, resolved_sell_reason = evaluate_exit_action_decision(
            ExitActionContext(
                sell_signal=sell,
                sell_reason=sell_reason,
                is_unsellable=is_unsellable,
                has_tp_limit_order=has_tp_limit_order,
                tp_limit_prearm_supported=prearm_supported,
                tp_limit_prearm_ready=prearm_ready,
            )
        )
        sell = exit_action is DcaAction.SELL
        if exit_reason == "waiting_for_tp_limit_fill":
            logging.debug(
                "TP reached for %s with proactive limit order already armed; "
                "waiting for exchange fill reconciliation.",
                trades["symbol"],
            )
        elif exit_action is DcaAction.SELL:
            sell_reason = resolved_sell_reason
            if has_tp_limit_order:
                if expected_snapshot is None:
                    canceled = await self.orders.cancel_tp_limit_order(
                        trades["symbol"],
                        self.config or {},
                    )
                else:
                    canceled = await self.orders.cancel_tp_limit_order(
                        trades["symbol"],
                        self.config or {},
                        expected_snapshot=expected_snapshot,
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
                    take_profit_price if current_price >= take_profit_price else None
                ),
                **self.__order_snapshot_payload(trades),
            }
            await self.orders.receive_sell_order(order, self.config or {})
        elif exit_action is DcaAction.ARM_TP_LIMIT:
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
        dynamic_so_details: dict[str, Any] = {"enabled": "false"}
        recovery_policy = self.__get_recovery_policy(trades)
        recovery_trigger_details: dict[str, Any] = {}
        decision_context = build_dca_evaluation_context(
            trade=trades,
            config=self.config or {},
            current_price=current_price,
            decision_timestamp_ms=int(datetime.now().timestamp() * 1000),
            persisted_policy=recovery_policy,
            strategy_name=runtime_config.dca_strategy or None,
            strategy_timeframe=resolve_timeframe(self.config or {}),
            replay_identity=str(trades.get("deal_id") or "") or None,
        )

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
                if recovery_policy.mode == RECOVERY_TARGET_MODE:
                    (
                        new_so,
                        next_so_percentage,
                        recovery_trigger_details,
                    ) = await self.__evaluate_recovery_dca_trigger(
                        trades,
                        current_price,
                        actual_pnl,
                        recovery_policy,
                        decision_context,
                    )
                else:
                    new_so, next_so_percentage = (
                        await self.__evaluate_dynamic_dca_trigger(
                            trades,
                            actual_pnl,
                            trigger_threshold,
                            last_so_percentage,
                        )
                    )
            else:
                static_decision = evaluate_static_dca_decision(
                    decision_context,
                    total_pnl=total_pnl,
                    step_scale=step_scale,
                    price_deviation=price_deviation,
                    safety_orders_count=int(trades["safetyorders_count"]),
                )
                new_so = static_decision.should_place
                trigger_threshold = float(static_decision.trigger_threshold or 0.0)
                next_so_percentage = float(static_decision.next_so_percentage or 0.0)

            if new_so:
                if recovery_policy.mode == RECOVERY_TARGET_MODE:
                    safety_order_size, dynamic_so_details = (
                        await self.__resolve_recovery_safety_order_size(
                            trades,
                            current_price,
                            recovery_policy,
                            recovery_trigger_details,
                        )
                    )
                else:
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
                    if recovery_policy.mode == RECOVERY_SHADOW_MODE:
                        shadow_atr, shadow_atr_details = (
                            await self.__get_recovery_atr_percent(
                                trades["symbol"],
                                recovery_policy,
                            )
                        )
                        _shadow_size, shadow_details = (
                            await self.__resolve_recovery_safety_order_size(
                                trades,
                                current_price,
                                recovery_policy,
                                {
                                    "enabled": "true",
                                    "mode": RECOVERY_SHADOW_MODE,
                                    "atr_percent": shadow_atr,
                                    "atr_regime": str(
                                        shadow_atr_details.get("regime", "mid")
                                    ),
                                    "reason": "legacy_trigger_shadow_evaluation",
                                },
                            )
                        )
                        dynamic_so_details["recovery_shadow"] = shadow_details
                if dynamic_so_details.get("skip") == "true":
                    logging.error(
                        "Skipping safety order for %s: %s",
                        trades["symbol"],
                        dynamic_so_details.get("error", "size resolution skipped"),
                    )
                    placed_new_so = False
                else:
                    maximum_buy_price = 0.0
                    if (
                        recovery_policy.mode == RECOVERY_TARGET_MODE
                        and recovery_policy.execution_guard_enabled
                    ):
                        execution_atr_percent = float(
                            dynamic_so_details.get("atr_percent") or 0.0
                        )
                        execution_trigger_price = float(
                            dynamic_so_details.get("trigger_price") or 0.0
                        )
                        execution_drift_percent = (
                            calculate_recovery_execution_drift_percent(
                                execution_atr_percent,
                                recovery_policy,
                            )
                        )
                        maximum_buy_price = calculate_recovery_execution_ceiling(
                            execution_trigger_price,
                            execution_atr_percent,
                            recovery_policy,
                        )
                        dynamic_so_details.update(
                            {
                                "execution_guard_enabled": True,
                                "execution_drift_percent": execution_drift_percent,
                                "maximum_buy_price": maximum_buy_price,
                            }
                        )
                    dca_strategy_name = (
                        runtime_config.dca_strategy
                        if dynamic_dca and runtime_config.dca_strategy
                        else None
                    )
                    dca_identity = self._last_dynamic_strategy_identity_by_symbol.get(
                        trades["symbol"],
                        (dca_strategy_name, None),
                    )
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
                        "maximum_buy_price": (
                            maximum_buy_price if maximum_buy_price > 0 else None
                        ),
                        "strategy_name": dca_strategy_name,
                        "strategy_slug": dca_identity[0] or dca_strategy_name,
                        "strategy_version": dca_identity[1],
                        "timeframe": (
                            resolve_timeframe(self.config or {})
                            if dynamic_dca and runtime_config.dca_strategy
                            else None
                        ),
                        "metadata_json": (
                            json.dumps(
                                {"recovery_so": dynamic_so_details},
                                sort_keys=True,
                            )
                            if recovery_policy.mode == RECOVERY_TARGET_MODE
                            else None
                        ),
                        **self.__order_snapshot_payload(trades),
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
        token = self._config_snapshot.set(dict(config))
        try:
            async with trading_maintenance_barrier.operation() as admitted:
                if not admitted:
                    logging.info(
                        "Skipping ticker evaluation for %s during maintenance.",
                        ticker.get("ticker", {}).get("symbol"),
                    )
                    return
                await self._process_ticker_data(ticker)
        finally:
            self._config_snapshot.reset(token)

    async def _process_ticker_data(self, ticker: dict[str, Any]) -> None:
        """Evaluate one ticker inside the trading maintenance barrier."""
        # New price action for DCA calculation
        if ticker["type"] == "ticker_price":
            price = ticker["ticker"]["price"]
            symbol = str(ticker["ticker"]["symbol"] or "")
            trades = await self.trades.get_trades_for_orders(symbol)
            if not trades:
                if TradeLifecycleConfigView.from_config(
                    self.config or {}
                ).is_sidestep_mode():
                    self.__log_sidestep_gate(
                        symbol,
                        "no_active_trade",
                        source="watcher_symbol_only",
                    )
                return
            if trades:
                runtime_config = self.__runtime_config()
                sidestep_campaigns = await self._get_sidestep_campaigns()
                ensured_campaign_id = (
                    await sidestep_campaigns.ensure_campaign_for_open_trade(
                        trades,
                        self.config or {},
                    )
                )
                if ensured_campaign_id and not trades.get("campaign_id"):
                    trades = {
                        **trades,
                        "campaign_id": ensured_campaign_id,
                        "lifecycle_mode": TradeLifecycleMode.SIDESTEP_REENTRY.value,
                    }
                trades["_lifecycle_snapshot"] = LifecycleSnapshotIdentity.from_trade(
                    trades,
                    self.config or {},
                )
                self.__clear_sidestep_gate(trades["symbol"])

                if self.__is_flat_waiting(trades):
                    await self.__update_waiting_virtual_metrics(trades, price)
                    if is_mission_automation_paused(trades):
                        logging.debug(
                            "Skipping waiting re-entry for %s because mission automation is paused.",
                            trades["symbol"],
                        )
                        return
                    await self.__attempt_waiting_reentry(trades, price)
                    return

                if is_mission_automation_paused(trades):
                    logging.debug(
                        "Skipping automated DCA/TP for %s because mission automation is paused.",
                        trades["symbol"],
                    )
                    return

                # Check Autopilot
                profit = await self.statistic.get_profit()
                trading_policy = await self.autopilot.resolve_trading_policy(
                    trades["symbol"],
                    float(profit.get("funds_locked") or 0.0),
                    self.config,
                )

                if await self.__should_sidestep_exit(trades, price, trading_policy):
                    return

                # Check DCA (classic lifecycle only)
                if (
                    runtime_config.dca_enabled
                    and not trades.get("is_unsellable", False)
                    and not self.__is_sidestep_mode(trades)
                ):
                    await self.__calculate_dca(price, trades)

                # Check TP
                await self.__calculate_tp(price, trades, trading_policy)

    async def __should_sidestep_exit(
        self,
        trades: dict[str, Any],
        current_price: float,
        trading_policy: ResolvedTradingPolicy,
    ) -> bool:
        """Sell early into flat-waiting mode when the bearish sidestep says so."""
        sidestep_campaigns = await self._get_sidestep_campaigns()
        total_amount = float(trades.get("total_amount") or 0.0)
        total_cost = float(trades.get("total_cost") or 0.0)
        total_fee = float(trades.get("fee") or 0.0)
        take_profit_price = 0.0
        if total_amount > 0:
            average_buy_price = calculate_average_entry_price(
                total_cost,
                total_fee,
                total_amount,
            )
            take_profit_price = calculate_take_profit_price(
                average_buy_price,
                trading_policy.take_profit,
            )

        decision_context = SidestepExitContext(
            enabled=sidestep_campaigns.is_enabled(self.config),
            is_sidestep_mode=self.__is_sidestep_mode(trades),
            is_flat_waiting=self.__is_flat_waiting(trades),
            is_unsellable=bool(trades.get("is_unsellable", False)),
            has_campaign=bool(trades.get("campaign_id")),
            total_amount=total_amount,
            current_price=current_price,
            take_profit_price=take_profit_price,
            strategy_signal=None,
        )
        preflight_action, preflight_reason = evaluate_sidestep_exit_decision(
            decision_context
        )
        if preflight_reason != "sidestep_exit_strategy_required":
            log_context: dict[str, Any] = {}
            if preflight_reason == "exit_tp_gate":
                log_context = {
                    "current_price": round(float(current_price), 8),
                    "tp_price": round(float(take_profit_price), 8),
                }
            if preflight_reason in {
                "active_missing_campaign",
                "active_missing_amount",
                "exit_tp_gate",
            }:
                self.__log_sidestep_gate(
                    trades["symbol"],
                    preflight_reason,
                    **log_context,
                )
            return False
        assert preflight_action is DcaAction.WAIT

        self.__clear_sidestep_gate(trades["symbol"])
        strategy_signal = await self.__sidestep_exit_strategy(trades["symbol"])
        exit_action, _reason = evaluate_sidestep_exit_decision(
            SidestepExitContext(
                **{
                    **decision_context.__dict__,
                    "strategy_signal": strategy_signal,
                }
            )
        )
        if exit_action is not DcaAction.SELL:
            return False

        if current_price >= take_profit_price:
            self.__log_sidestep_gate(
                trades["symbol"],
                "exit_tp_gate",
                current_price=round(float(current_price), 8),
                tp_price=round(float(take_profit_price), 8),
            )
            return False

        actual_pnl = self.utils.calculate_actual_pnl(trades, current_price)
        bearish_strategy_name = SidestepCampaignConfigView.from_config(
            self.config or {}
        ).bearish_strategy
        bearish_identity = self._last_sidestep_exit_identity_by_symbol.get(
            trades["symbol"],
            (bearish_strategy_name, None),
        )

        logging.info(
            "Sidestep exit triggered for %s: campaign=%s current_price=%s "
            "tp_price=%s actual_pnl=%s.",
            trades["symbol"],
            trades.get("campaign_id"),
            current_price,
            take_profit_price,
            actual_pnl,
        )
        order = {
            "symbol": trades["symbol"],
            "direction": trades["direction"],
            "side": "sell",
            "type_sell": "order_sell",
            "sell_reason": "sidestep_exit",
            "actual_pnl": actual_pnl,
            "total_cost": trades["total_cost"],
            "current_price": current_price,
            "tp_price": take_profit_price,
            "campaign_id": trades.get("campaign_id"),
            "strategy_name": bearish_strategy_name,
            "strategy_slug": bearish_identity[0] or bearish_strategy_name,
            "strategy_version": bearish_identity[1],
            "timeframe": resolve_timeframe(self.config or {}),
            **self.__order_snapshot_payload(trades),
        }
        sidestep_config = SidestepCampaignConfigView.from_config(self.config or {})
        fallback_minimum_price = calculate_sidestep_exit_fallback_minimum_price(
            current_price,
            sidestep_config.exit_max_market_fallback_slippage_pct,
        )
        if fallback_minimum_price is not None:
            order["fallback_min_price"] = fallback_minimum_price
        await self.orders.receive_sell_order(order, self.config or {})
        return True

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
            "dynamic_so_mode": dynamic_so_details.get(
                "mode",
                LEGACY_SIZING_MODE,
            ),
            "dynamic_so_reason": dynamic_so_details.get("reason"),
            "dynamic_so_atr_percent": dynamic_so_details.get("atr_percent", 0.0),
            "dynamic_so_trigger_price": dynamic_so_details.get(
                "trigger_price",
                0.0,
            ),
            "dynamic_so_target_recovery_percent": dynamic_so_details.get(
                "target_recovery_percent",
                0.0,
            ),
            "dynamic_so_projected_tp_price": dynamic_so_details.get(
                "projected_tp_price",
                0.0,
            ),
            "dynamic_so_remaining_deal_quote": dynamic_so_details.get(
                "remaining_deal_quote",
                -1.0,
            ),
        }
        await self.statistic.update_statistic_data(logging_json)
