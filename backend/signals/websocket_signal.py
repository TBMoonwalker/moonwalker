"""Plain WebSocket JSON signal plugin implementation."""

import asyncio
import json
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import helper
from service.autopilot import Autopilot
from service.config import resolve_history_lookback_days
from service.data import Data
from service.filter import Filter
from service.indicators import Indicators
from service.orders import Orders
from service.signal_runtime import (
    build_common_runtime_settings,
    get_active_open_symbols,
    is_max_bots_reached,
    log_signal_admission_decisions,
    log_signal_entry_order_decisions,
    parse_signal_settings,
    resolve_max_bots_log_interval,
    resolve_signal_admission_batch,
    resolve_signal_entry_orders,
    update_waiting_log_state,
)
from service.spot_sidestep_campaign import SpotSidestepCampaignService
from service.statistic import Statistic
from service.strategy_capability import (
    get_configured_strategy_history_lookback_days,
    get_configured_strategy_min_history_candles,
)
from tortoise.exceptions import BaseORMException
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, WebSocketException

logging = helper.LoggerFactory.get_logger("logs/signal.log", "websocket_signal")


@dataclass(frozen=True)
class WebsocketSignalSettings:
    """Parsed connection and admission settings for the JSON websocket stream."""

    websocket_url: str
    headers: dict[str, str]
    subscribe_message: Any | None
    required_decision: str
    min_confidence: float
    accepted_exchanges: tuple[str, ...]
    accepted_market_states: tuple[str, ...]
    reconnect_delay_seconds: float
    max_error_reconnect_delay_seconds: float


@dataclass(frozen=True)
class SignalTradeCandidate:
    """Validated websocket signal ready for Moonwalker admission checks."""

    symbol: str
    source_symbol: str
    signal_name: str
    strategy_name: str | None
    timeframe: str
    metadata_json: str


class SignalPlugin:
    """Signal plugin for plain websocket JSON trade signals."""

    DEFAULT_RECONNECT_DELAY_SECONDS = 10.0
    DEFAULT_MAX_ERROR_RECONNECT_DELAY_SECONDS = 300.0
    RECENT_SIGNAL_CACHE_SIZE = 2048

    def __init__(self, watcher_queue: asyncio.Queue):
        """Initialize the websocket signal plugin."""
        self.utils = helper.Utils()
        self.autopilot = Autopilot()
        self.orders = Orders()
        self.statistic = Statistic()
        self.data = Data(persist_exchange=True)
        self.filter = Filter()
        self.indicators = Indicators()
        self.config: dict[str, Any] | None = None
        self.status = True
        self.watcher_queue = watcher_queue
        self._max_bots_blocked = False
        self._max_bots_last_log = 0.0
        self._max_bots_log_interval_sec = 60.0
        self._currency = "USDC"
        self._pair_denylist: list[str] | None = None
        self._pair_allowlist: list[str] | None = None
        self._strategy_timeframe = "1m"
        self._required_history_days = 0
        self._required_history_candles = 0
        self._settings: WebsocketSignalSettings | None = None
        self._seen_signal_ids: set[str] = set()
        self._recent_signal_ids: deque[str] = deque(
            maxlen=self.RECENT_SIGNAL_CACHE_SIZE
        )

    def _prepare_runtime_settings(self) -> None:
        """Cache parsed config settings used by the websocket hot path."""
        if self.config is None:
            raise ValueError("Plugin config must be assigned before runtime setup")

        runtime = build_common_runtime_settings(self.config)
        self._currency = str(self.config.get("currency", "USDC")).upper()
        self._pair_denylist = runtime.pair_denylist
        self._pair_allowlist = runtime.pair_allowlist
        self._strategy_timeframe = runtime.strategy_timeframe
        self._settings = self._parse_settings(self.config)
        configured_history_days = resolve_history_lookback_days(
            self.config,
            timeframe=self._strategy_timeframe,
        )
        strategy_history_days = get_configured_strategy_history_lookback_days(
            self.config,
            self._strategy_timeframe,
            include_signal_strategy=False,
        )
        self._required_history_days = max(
            configured_history_days,
            strategy_history_days,
        )
        self._required_history_candles = get_configured_strategy_min_history_candles(
            self.config,
            include_signal_strategy=False,
        )

    def _parse_settings(self, config: dict[str, Any]) -> WebsocketSignalSettings:
        """Parse websocket-specific settings from signal_settings."""
        raw_settings = parse_signal_settings(config.get("signal_settings"))
        websocket_url = str(
            raw_settings.get("websocket_url") or raw_settings.get("api_url") or ""
        ).strip()
        if not websocket_url:
            raise ValueError(
                "Missing websocket URL in signal_settings.websocket_url or "
                "signal_settings.api_url."
            )

        headers = raw_settings.get("headers") or {}
        if not isinstance(headers, dict):
            raise TypeError("signal_settings.headers must be a dictionary")

        accepted_exchanges = self._parse_string_list(
            raw_settings.get("accepted_exchanges"),
            default=(str(config.get("exchange", "")).lower(),),
            lower=True,
        )
        accepted_market_states = self._parse_string_list(
            raw_settings.get("accepted_market_states"),
            default=tuple(),
            lower=True,
        )

        return WebsocketSignalSettings(
            websocket_url=websocket_url,
            headers={str(key): str(value) for key, value in headers.items()},
            subscribe_message=raw_settings.get("subscribe_message"),
            required_decision=str(
                raw_settings.get("required_decision", "take_trade")
            ).strip(),
            min_confidence=self._parse_float(
                raw_settings.get("min_confidence"),
                default=0.0,
            ),
            accepted_exchanges=accepted_exchanges,
            accepted_market_states=accepted_market_states,
            reconnect_delay_seconds=self._parse_float(
                raw_settings.get("reconnect_delay_seconds"),
                default=self.DEFAULT_RECONNECT_DELAY_SECONDS,
            ),
            max_error_reconnect_delay_seconds=self._parse_float(
                raw_settings.get("max_error_reconnect_delay_seconds"),
                default=self.DEFAULT_MAX_ERROR_RECONNECT_DELAY_SECONDS,
            ),
        )

    @staticmethod
    def _parse_string_list(
        raw_value: Any,
        *,
        default: tuple[str, ...],
        lower: bool,
    ) -> tuple[str, ...]:
        """Parse an optional string/list config value into a normalized tuple."""
        if raw_value is None:
            values = list(default)
        elif isinstance(raw_value, str):
            values = [value.strip() for value in raw_value.split(",")]
        elif isinstance(raw_value, list | tuple | set):
            values = [str(value).strip() for value in raw_value]
        else:
            raise TypeError("Expected a string or list setting")

        normalized = [value.lower() if lower else value for value in values if value]
        return tuple(normalized)

    @staticmethod
    def _parse_float(raw_value: Any, *, default: float) -> float:
        """Parse a float setting with a conservative fallback."""
        if raw_value is None:
            return default
        return float(raw_value)

    def __log_max_bots_waiting(self) -> None:
        """Log max-bot saturation with state/interval throttling."""
        (
            self._max_bots_blocked,
            self._max_bots_last_log,
            should_log,
        ) = update_waiting_log_state(
            self._max_bots_blocked,
            self._max_bots_last_log,
            self._max_bots_log_interval_sec,
        )
        if should_log:
            logging.debug("Max bots reached, waiting for a free slot.")

    async def __check_max_bots(self) -> bool:
        """Return True when configured capacity blocks new trades."""
        if self.config is None:
            return True
        try:
            return await is_max_bots_reached(
                self.config,
                self.statistic,
                self.autopilot,
            )
        except (BaseORMException, RuntimeError, TypeError, ValueError) as exc:
            logging.error(
                "Couldn't get actual list of bots - not starting new deals! "
                "Cause: %s",
                exc,
            )
            return True

    async def __has_sufficient_strategy_history(self, symbol: str) -> bool:
        """Return True when local history satisfies configured DCA/TP warmup."""
        if self._required_history_candles <= 0:
            return True

        available_candles = await self.data.get_resampled_history_candle_count(
            symbol,
            self._strategy_timeframe,
            self._required_history_candles,
        )
        if available_candles >= self._required_history_candles:
            return True

        logging.warning(
            "Not watching %s because only %s/%s %s candles are available after "
            "history sync.",
            symbol,
            available_candles,
            self._required_history_candles,
            self._strategy_timeframe,
        )
        return False

    async def run(self, config: dict[str, Any]) -> None:
        """Connect to the configured websocket and process JSON trade signals."""
        self.config = config
        self._max_bots_log_interval_sec = resolve_max_bots_log_interval(self.config)
        self._prepare_runtime_settings()
        if self._settings is None:
            raise ValueError("Websocket signal settings were not initialized")

        consecutive_errors = 0
        while self.status:
            try:
                async with connect(
                    self._settings.websocket_url,
                    additional_headers=self._settings.headers or None,
                ) as websocket:
                    logging.info(
                        "Established websocket signal connection to %s.",
                        self._settings.websocket_url,
                    )
                    consecutive_errors = 0
                    await self.__send_subscription(websocket)

                    while self.status:
                        raw_message = await websocket.recv()
                        await self.__process_raw_message(raw_message)
            except ConnectionClosed as exc:
                logging.warning(
                    "Websocket signal connection closed. Reconnecting in %s seconds. "
                    "Cause: %s",
                    self._settings.reconnect_delay_seconds,
                    exc,
                )
            except (
                OSError,
                RuntimeError,
                TypeError,
                ValueError,
                WebSocketException,
            ) as exc:
                consecutive_errors += 1
                reconnect_delay = min(
                    self._settings.reconnect_delay_seconds
                    * (2 ** (consecutive_errors - 1)),
                    self._settings.max_error_reconnect_delay_seconds,
                )
                logging.error(
                    "Websocket signal error. Reconnecting in %s seconds. Cause: %s",
                    reconnect_delay,
                    exc,
                )
                await asyncio.sleep(reconnect_delay)
                continue

            if self.status:
                await asyncio.sleep(self._settings.reconnect_delay_seconds)

    async def __send_subscription(self, websocket: Any) -> None:
        """Send an optional subscription payload after connection."""
        if self._settings is None or self._settings.subscribe_message is None:
            return

        message = self._settings.subscribe_message
        if not isinstance(message, str):
            message = json.dumps(message, sort_keys=True)
        await websocket.send(message)

    async def __process_raw_message(self, raw_message: Any) -> None:
        """Decode a websocket frame and process every signal payload inside it."""
        try:
            payload = self.__decode_message(raw_message)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
            logging.warning("Ignoring invalid websocket signal payload: %s", exc)
            return

        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    await self.__process_signal_payload(item)
                else:
                    logging.debug("Ignoring non-object websocket signal item.")
            return

        if isinstance(payload, dict):
            await self.__process_signal_payload(payload)
            return

        logging.debug("Ignoring websocket signal payload that is not an object.")

    @staticmethod
    def __decode_message(raw_message: Any) -> Any:
        """Decode websocket text or bytes into JSON."""
        if isinstance(raw_message, bytes):
            raw_message = raw_message.decode("utf-8")
        if isinstance(raw_message, str):
            return json.loads(raw_message)
        if isinstance(raw_message, dict | list):
            return raw_message
        raise TypeError("Unsupported websocket message type")

    async def __process_signal_payload(self, payload: dict[str, Any]) -> None:
        """Validate and process one decoded websocket signal object."""
        if str(payload.get("type", "")).strip().lower() == "keepalive":
            logging.debug(
                "Received websocket signal keepalive %s.",
                payload.get("connection_id") or "without connection id",
            )
            return

        candidate = await self.__build_trade_candidate(payload)
        if candidate is None:
            return

        max_bots = await self.__check_max_bots()
        if max_bots:
            self.__log_max_bots_waiting()
            return

        self._max_bots_blocked = False
        await self.__open_trade(candidate)

    async def __build_trade_candidate(
        self,
        payload: dict[str, Any],
    ) -> SignalTradeCandidate | None:
        """Return a trade candidate when the websocket payload is admissible."""
        if self.config is None or self._settings is None:
            return None

        required_decision = self._settings.required_decision
        decision = str(payload.get("decision", "")).strip()
        if decision != required_decision:
            logging.debug(
                "Ignoring websocket signal %s because decision is %s.",
                payload.get("signal_id"),
                decision or "missing",
            )
            return None

        exchange = str(payload.get("exchange", "")).strip().lower()
        if (
            self._settings.accepted_exchanges
            and exchange not in self._settings.accepted_exchanges
        ):
            logging.debug(
                "Ignoring websocket signal %s because exchange %s is not accepted.",
                payload.get("signal_id"),
                exchange or "missing",
            )
            return None

        market_state = str(payload.get("market_state", "")).strip().lower()
        if (
            self._settings.accepted_market_states
            and market_state not in self._settings.accepted_market_states
        ):
            logging.debug(
                "Ignoring websocket signal %s because market_state is %s.",
                payload.get("signal_id"),
                market_state or "missing",
            )
            return None

        confidence = self.__parse_confidence(payload.get("confidence"))
        if confidence is None or confidence < self._settings.min_confidence:
            logging.debug(
                "Ignoring websocket signal %s because confidence is %s.",
                payload.get("signal_id"),
                confidence,
            )
            return None

        if not self.__is_signal_fresh(payload):
            return None

        dedupe_key = self.__dedupe_key(payload)
        if dedupe_key and dedupe_key in self._seen_signal_ids:
            logging.debug("Ignoring duplicate websocket signal %s.", dedupe_key)
            return None
        if dedupe_key:
            self.__remember_signal(dedupe_key)

        symbol = self.__normalize_symbol(payload.get("symbol"))
        if symbol is None:
            logging.debug(
                "Ignoring websocket signal %s because symbol is invalid.",
                payload.get("signal_id"),
            )
            return None

        if not await self.__check_entry_filters(symbol):
            return None

        timeframe = str(payload.get("timeframe") or self._strategy_timeframe).strip()
        strategy_name = (
            str(payload.get("strategy_family") or "").strip()
            or str(self.config.get("signal_strategy") or "").strip()
            or None
        )
        signal_name = f"websocket_signal:{payload.get('signal_id') or 'unknown'}"
        metadata_json = self.__build_metadata_json(payload)
        return SignalTradeCandidate(
            symbol=symbol,
            source_symbol=str(payload.get("symbol", "")).strip().upper(),
            signal_name=signal_name,
            strategy_name=strategy_name,
            timeframe=timeframe,
            metadata_json=metadata_json,
        )

    @staticmethod
    def __parse_confidence(raw_value: Any) -> float | None:
        """Parse confidence as a numeric score."""
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            return None

    def __is_signal_fresh(self, payload: dict[str, Any]) -> bool:
        """Return True when expires_at is absent or still in the future."""
        expires_at = payload.get("expires_at")
        if not expires_at:
            return True

        expires_at_dt = self.__parse_datetime(expires_at)
        if expires_at_dt is None:
            logging.debug(
                "Ignoring websocket signal %s because expires_at is invalid.",
                payload.get("signal_id"),
            )
            return False
        if expires_at_dt <= datetime.now(UTC):
            logging.debug(
                "Ignoring expired websocket signal %s.",
                payload.get("signal_id"),
            )
            return False
        return True

    @staticmethod
    def __parse_datetime(raw_value: Any) -> datetime | None:
        """Parse an ISO-8601 timestamp into an aware UTC datetime."""
        try:
            value = str(raw_value).replace("Z", "+00:00")
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    @staticmethod
    def __dedupe_key(payload: dict[str, Any]) -> str | None:
        """Return the best available idempotency key for a signal payload."""
        signal_id = str(payload.get("signal_id") or "").strip()
        if signal_id:
            return signal_id
        sequence = payload.get("sequence")
        if sequence is None:
            return None
        return f"sequence:{sequence}"

    def __remember_signal(self, dedupe_key: str) -> None:
        """Remember a signal id while bounding memory growth."""
        if len(self._recent_signal_ids) == self._recent_signal_ids.maxlen:
            oldest = self._recent_signal_ids.popleft()
            self._seen_signal_ids.discard(oldest)
        self._recent_signal_ids.append(dedupe_key)
        self._seen_signal_ids.add(dedupe_key)

    def __normalize_symbol(self, raw_symbol: Any) -> str | None:
        """Normalize incoming compact or slash-separated symbols."""
        symbol = str(raw_symbol or "").strip().upper()
        if not symbol:
            return None
        if "/" in symbol:
            return symbol
        if not symbol.endswith(self._currency):
            return None
        return self.utils.split_symbol(symbol, self._currency)

    async def __check_entry_filters(self, symbol: str) -> bool:
        """Apply common Moonwalker signal filters to a normalized symbol."""
        symbol_only = symbol.split("/")[0]
        if not self.filter.is_on_allowed_list(symbol, self._pair_allowlist):
            logging.info(
                "Symbol %s is not in your allowlist. Ignoring websocket signal.",
                symbol,
            )
            return False
        if self.filter.is_on_deny_list(symbol_only, self._pair_denylist):
            logging.info(
                "Symbol %s is set in your denylist. Ignoring websocket signal.",
                symbol,
            )
            return False
        if self.config is not None and self.config.get("btc_pulse", False):
            btc_pulse = await self.indicators.calculate_btc_pulse(
                self.config.get("currency", "USDC"),
                self._strategy_timeframe,
            )
            if not btc_pulse:
                logging.info("BTC-Pulse is in downtrend - not starting new deals!")
                return False
        return True

    def __build_metadata_json(self, payload: dict[str, Any]) -> str:
        """Build persisted metadata from non-secret signal fields."""
        metadata = {
            "websocket_signal": {
                "exchange": payload.get("exchange"),
                "symbol": payload.get("symbol"),
                "timeframe": payload.get("timeframe"),
                "strategy_family": payload.get("strategy_family"),
                "decision": payload.get("decision"),
                "confidence": payload.get("confidence"),
                "observed_at": payload.get("observed_at"),
                "expires_at": payload.get("expires_at"),
                "market_state": payload.get("market_state"),
                "rationale_codes": payload.get("rationale_codes"),
                "feature_snapshot": payload.get("feature_snapshot"),
                "publish_reason": payload.get("publish_reason"),
                "signal_id": payload.get("signal_id"),
                "sequence": payload.get("sequence"),
                "created_at": payload.get("created_at"),
                "timezone": payload.get("timezone"),
            }
        }
        return json.dumps(metadata, sort_keys=True)

    @staticmethod
    def __merge_metadata(entry_metadata_json: str, signal_metadata_json: str) -> str:
        """Merge entry-sizing metadata with websocket signal provenance."""
        try:
            entry_metadata = json.loads(entry_metadata_json)
        except (json.JSONDecodeError, TypeError):
            entry_metadata = {}
        try:
            signal_metadata = json.loads(signal_metadata_json)
        except (json.JSONDecodeError, TypeError):
            signal_metadata = {}
        if isinstance(entry_metadata, dict) and isinstance(signal_metadata, dict):
            entry_metadata.update(signal_metadata)
            return json.dumps(entry_metadata, sort_keys=True)
        return signal_metadata_json

    async def __open_trade(self, candidate: SignalTradeCandidate) -> None:
        """Run admission, history warmup, and buy order creation for one signal."""
        if self.config is None:
            return

        token_old_enough = await self.data.is_token_old_enough(
            self.config,
            candidate.symbol,
        )
        if not token_old_enough:
            return

        sidestep_campaigns = await SpotSidestepCampaignService.instance()
        await sidestep_campaigns.record_long_signal(
            candidate.symbol,
            signal_name=candidate.signal_name,
            strategy_name=candidate.strategy_name,
            timeframe=candidate.timeframe,
            metadata_json=candidate.metadata_json,
            source="websocket_signal",
        )

        running_symbols = await get_active_open_symbols()
        if candidate.symbol.upper() in running_symbols:
            return

        admission_batch = await resolve_signal_admission_batch(
            self.config,
            self.statistic,
            self.autopilot,
            [candidate.symbol],
        )
        log_signal_admission_decisions(admission_batch.decisions)
        if not admission_batch.admitted_symbols:
            if admission_batch.has_capacity_block:
                self.__log_max_bots_waiting()
            return

        try:
            if (
                self.config.get("trade_mode") == "dynamic_dca"
                or self._required_history_candles > 0
            ):
                success = await self.data.add_history_data_for_symbol(
                    candidate.symbol,
                    self._required_history_days,
                    self.config,
                    success_timeframe=self._strategy_timeframe,
                    success_minimum_candles=self._required_history_candles,
                )
                if not success:
                    logging.error(
                        "Not trading %s because history add failed. Please check "
                        "data.log.",
                        candidate.symbol,
                    )
                    return
                if not await self.__has_sufficient_strategy_history(candidate.symbol):
                    return

            entry_orders = await resolve_signal_entry_orders(
                self.config,
                self.statistic,
                self.autopilot,
                [candidate.symbol],
                signal_name=candidate.signal_name,
                strategy_name=candidate.strategy_name,
                timeframe=candidate.timeframe,
            )
            log_signal_entry_order_decisions(entry_orders.values())
            entry_order = entry_orders[candidate.symbol]
            await self.watcher_queue.put([candidate.symbol])
            order = {
                "ordersize": entry_order.order_size,
                "symbol": candidate.symbol,
                "direction": "long",
                "botname": f"websocket_signal_{candidate.source_symbol}",
                "baseorder": True,
                "safetyorder": False,
                "order_count": 0,
                "ordertype": "market",
                "so_percentage": None,
                "side": "buy",
                "signal_name": entry_order.signal_name,
                "strategy_name": entry_order.strategy_name,
                "timeframe": entry_order.timeframe,
                "metadata_json": self.__merge_metadata(
                    entry_order.metadata_json,
                    candidate.metadata_json,
                ),
                "baseline_order_size": entry_order.baseline_order_size,
                "entry_size_applied": entry_order.entry_size_applied,
                "entry_size_reason_code": entry_order.reason_code,
                "entry_size_fallback_applied": False,
                "entry_size_fallback_reason": None,
            }
            logging.info("Triggering new trade for %s", candidate.symbol)
            await self.orders.receive_buy_order(order, self.config)
        finally:
            await admission_batch.release_symbol(candidate.symbol)
            await admission_batch.release()

    async def shutdown(self) -> None:
        """Stop the websocket signal loop and release data resources."""
        self.status = False
        await self.data.close()
