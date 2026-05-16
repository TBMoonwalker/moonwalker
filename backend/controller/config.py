"""Configuration API endpoints."""

import json
import math
from typing import Any

import helper
from controller.responses import json_response
from litestar.connection import Request
from litestar.exceptions import SerializationException
from litestar.handlers import get, post, put
from model import AppConfig, OpenTrades
from service.backup_restore import BackupService
from service.config import (
    Config,
    build_legacy_trade_mode_key_message,
    build_removed_config_key_message,
    is_legacy_trade_mode_key,
    is_removed_config_key,
)
from service.config_persistence import should_persist_config_value
from service.config_views import TradeLifecycleConfigView
from service.spot_sidestep_campaign import SpotSidestepCampaignService
from service.trade_lifecycle_config import (
    TRADE_MODE_COMPATIBILITY_KEYS,
    TRADE_MODE_LEGACY_KEYS,
    TradeModeConfigError,
    TradeModeSwitchGuard,
    build_blocked_live_mode_switch_error,
    resolve_trade_mode_config,
)
from service.trading_controls import GLOBAL_TRADING_PAUSED_KEY

logging = helper.LoggerFactory.get_logger("logs/config.log", "config_data")

CSV_SIGNAL_NAME = "csv_signal"
LIVE_ACTIVATION_KEY = "dry_run"
LIVE_ACTIVATION_DENIED_MESSAGE = (
    "Live activation must go through /config/live/activate. "
    "Generic config saves cannot switch dry run off."
)
backup_service = BackupService()
ConfigUpdateMap = dict[str, dict[str, Any]]


def _extract_config_update_value(raw_value: Any) -> Any:
    """Extract normalized `value` from config update payloads."""
    if isinstance(raw_value, dict) and "value" in raw_value:
        return raw_value["value"]
    return raw_value


def _is_config_update_payload(raw_value: Any) -> bool:
    """Return whether a config update payload matches the supported API shape."""
    return isinstance(raw_value, dict) and "value" in raw_value and "type" in raw_value


def _has_required_value(value: Any) -> bool:
    """Return whether the config value counts as meaningfully configured."""
    if value is None:
        return False
    if isinstance(value, str):
        normalized = value.strip().lower()
        return bool(normalized and normalized != "false")
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, list):
        return len(value) > 0
    return True


def _has_positive_number(value: Any) -> bool:
    """Return whether the config value is a finite positive number."""
    if value is None or isinstance(value, bool):
        return False
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(numeric_value) and numeric_value > 0


def _parse_signal_settings(raw_value: Any) -> dict[str, Any]:
    """Return normalized signal settings payload from string or object input."""
    if isinstance(raw_value, dict):
        return raw_value
    if isinstance(raw_value, str):
        try:
            return json.loads(raw_value.replace("'", '"'))
        except Exception:  # noqa: BLE001 - defensive parsing for config rows.
            return {}
    return {}


def _get_config_snapshot(config: Config) -> dict[str, Any]:
    """Return a best-effort config snapshot for readiness checks."""
    snapshot = getattr(config, "snapshot", None)
    if callable(snapshot):
        return snapshot()
    return {}


def _get_raw_config_snapshot(config: Config) -> dict[str, Any]:
    """Return the persisted config snapshot without derived trade-mode fields."""
    raw_snapshot = getattr(config, "raw_snapshot", None)
    if callable(raw_snapshot):
        return raw_snapshot()
    return _get_config_snapshot(config)


def _merge_config_snapshot_with_updates(
    config_snapshot: dict[str, Any],
    updates: ConfigUpdateMap,
) -> dict[str, Any]:
    """Return the candidate config snapshot after applying typed API updates."""
    merged = dict(config_snapshot)
    for key, raw_value in updates.items():
        value_type = str(raw_value.get("type", "")).strip()
        value = _extract_config_update_value(raw_value)
        if should_persist_config_value(value_type, value):
            merged[key] = value
        else:
            merged.pop(key, None)
    return merged


def _updates_touch_trade_mode(updates: ConfigUpdateMap) -> bool:
    """Return whether the request mutates the canonical trade-mode field."""
    return any(key in TRADE_MODE_COMPATIBILITY_KEYS for key in updates)


def _requested_trade_mode_snapshot(
    config_snapshot: dict[str, Any],
    updates: ConfigUpdateMap,
) -> dict[str, Any]:
    """Return the mode-resolution snapshot after dropping stale legacy bridge keys."""
    merged_snapshot = _merge_config_snapshot_with_updates(config_snapshot, updates)
    if "trade_mode" in updates:
        for key in TRADE_MODE_LEGACY_KEYS:
            merged_snapshot.pop(key, None)
    return merged_snapshot


async def _get_trade_mode_switch_guard(
    config_snapshot: dict[str, Any],
    *,
    strict: bool = True,
) -> TradeModeSwitchGuard:
    """Return lightweight runtime guard data for trade-mode switch UX."""
    current_trade_mode = resolve_trade_mode_config(
        config_snapshot,
        source="runtime",
        require_explicit_sidestep_reentry=False,
    ).trade_mode
    try:
        open_trade_count = await OpenTrades.all().count()
        waiting_campaign_count = (
            await SpotSidestepCampaignService.count_waiting_campaigns()
        )
    except Exception:  # noqa: BLE001 - keep snapshot reads resilient.
        if strict:
            raise
        logging.warning(
            "Falling back to an unlocked trade-mode guard after a runtime guard read failed.",
            exc_info=True,
        )
        open_trade_count = 0
        waiting_campaign_count = 0
    blocked = open_trade_count > 0 or waiting_campaign_count > 0
    message = None
    if blocked:
        message = (
            "Close open trades and clear waiting sidestep campaigns before "
            "switching trade modes."
        )
    return TradeModeSwitchGuard(
        current_trade_mode=current_trade_mode,
        blocked=blocked,
        open_trade_count=open_trade_count,
        waiting_campaign_count=waiting_campaign_count,
        message=message,
    )


async def _prepare_trade_mode_updates(
    config_snapshot: dict[str, Any],
    updates: ConfigUpdateMap,
) -> ConfigUpdateMap:
    """Validate canonical trade-mode updates against runtime switch rules."""
    prepared_updates = dict(updates)
    if not _updates_touch_trade_mode(prepared_updates):
        return prepared_updates

    merged_snapshot = _requested_trade_mode_snapshot(config_snapshot, prepared_updates)
    current_trade_mode = resolve_trade_mode_config(
        config_snapshot,
        source="runtime",
        require_explicit_sidestep_reentry=False,
    ).trade_mode
    requested_trade_mode = resolve_trade_mode_config(
        merged_snapshot,
        source="save",
        require_explicit_sidestep_reentry=False,
    ).trade_mode

    if requested_trade_mode != current_trade_mode:
        guard = await _get_trade_mode_switch_guard(config_snapshot, strict=True)
        if guard.blocked:
            raise build_blocked_live_mode_switch_error(
                source="save",
                current_trade_mode=current_trade_mode,
                requested_trade_mode=requested_trade_mode,
                open_trade_count=guard.open_trade_count,
                waiting_campaign_count=guard.waiting_campaign_count,
            )

    prepared_updates["trade_mode"] = {
        "value": requested_trade_mode,
        "type": "str",
    }
    return prepared_updates


def _find_live_activation_blockers(
    config_snapshot: dict[str, Any],
) -> list[dict[str, str]]:
    """Return config blockers that prevent a safe dry-run-to-live transition."""
    blockers: list[dict[str, str]] = []
    always_required_keys = [
        ("timezone", "Add a timezone."),
        ("signal", "Choose a signal source."),
        ("exchange", "Choose an exchange."),
        ("timeframe", "Choose a timeframe."),
        ("key", "Add the exchange API key."),
        ("secret", "Add the exchange API secret."),
        ("currency", "Choose a quote currency."),
        ("max_bots", "Set max bots."),
        ("bo", "Set the base order amount."),
        ("tp", "Set the take profit."),
        ("history_lookback_time", "Set the history lookback window."),
    ]

    for key, message in always_required_keys:
        if not _has_required_value(config_snapshot.get(key)):
            blockers.append({"key": key, "message": message})

    capital_limit = config_snapshot.get("capital_max_fund")
    if not _has_positive_number(capital_limit):
        blockers.append(
            {
                "key": "capital_max_fund",
                "message": "Set a positive global max fund.",
            }
        )

    dca_enabled = bool(config_snapshot.get("dca"))
    if dca_enabled:
        lifecycle = TradeLifecycleConfigView.from_config(config_snapshot)
        if lifecycle.is_sidestep_mode():
            if not _has_required_value(lifecycle.bearish_exit_strategy):
                blockers.append(
                    {
                        "key": "sidestep_bearish_strategy",
                        "message": "Choose a bearish sidestep strategy.",
                    }
                )
            if not _has_required_value(lifecycle.reentry_strategy):
                blockers.append(
                    {
                        "key": "sidestep_reentry_strategy",
                        "message": "Choose a sidestep re-entry strategy.",
                    }
                )
        else:
            dynamic_dca_enabled = lifecycle.trade_mode == "dynamic_dca"
            dca_required_keys = (
                [
                    ("mstc", "Set max safety order count."),
                    ("sos", "Set the first safety order deviation."),
                ]
                if dynamic_dca_enabled
                else [
                    ("so", "Set the safety order amount."),
                    ("mstc", "Set max safety order count."),
                    ("sos", "Set the first safety order deviation."),
                    ("ss", "Set the safety order step scale."),
                    ("os", "Set the safety order volume scale."),
                ]
            )
            for key, message in dca_required_keys:
                if not _has_required_value(config_snapshot.get(key)):
                    blockers.append({"key": key, "message": message})

    signal_name = str(config_snapshot.get("signal", "") or "").strip().lower()
    signal_settings = _parse_signal_settings(config_snapshot.get("signal_settings"))
    if signal_name == "asap" and not _has_required_value(
        config_snapshot.get("symbol_list")
    ):
        blockers.append(
            {
                "key": "symbol_list",
                "message": "Add ASAP symbols or a symbol list URL.",
            }
        )
    elif signal_name == "sym_signals":
        for key, message in [
            ("api_url", "Add the SymSignals URL."),
            ("api_key", "Add the SymSignals key."),
            ("api_version", "Add the SymSignals API version."),
        ]:
            if not _has_required_value(signal_settings.get(key)):
                blockers.append({"key": f"signal_settings.{key}", "message": message})
    elif signal_name == CSV_SIGNAL_NAME:
        if not _has_required_value(signal_settings.get("csv_source")):
            blockers.append(
                {
                    "key": "signal_settings.csv_source",
                    "message": "Add a CSV source or inline CSV payload.",
                }
            )

    return blockers


def _is_dry_run_enabled(raw_value: Any) -> bool:
    """Return whether a raw config value resolves to dry-run mode."""
    normalized = _extract_config_update_value(raw_value)
    if isinstance(normalized, str):
        return normalized.strip().lower() not in {"false", "0", "no", "off", ""}
    return bool(normalized)


def _validate_live_activation_boundary(
    config: Config,
    updates: dict[str, Any],
) -> str | None:
    """Return an error when generic config updates try to switch the system live."""
    raw_value = updates.get(LIVE_ACTIVATION_KEY)
    if raw_value is None:
        return None
    current_dry_run = _is_dry_run_enabled(config.get(LIVE_ACTIVATION_KEY, True))
    requested_dry_run = _is_dry_run_enabled(raw_value)
    if current_dry_run and not requested_dry_run:
        return LIVE_ACTIVATION_DENIED_MESSAGE
    return None


def _validate_removed_config_keys(updates: ConfigUpdateMap) -> str | None:
    """Return an error when the payload references a removed config key."""
    for key in updates:
        if is_legacy_trade_mode_key(key):
            return build_legacy_trade_mode_key_message(key)
        if is_removed_config_key(key):
            return build_removed_config_key_message(key)
    return None


async def _validate_csv_signal_switch(
    config: Config, raw_signal_update: Any
) -> str | None:
    """Return error message if switching to csv_signal while open trades exist."""
    new_signal_raw = _extract_config_update_value(raw_signal_update)
    if not isinstance(new_signal_raw, str):
        return None

    new_signal = new_signal_raw.strip()
    if not new_signal or new_signal.lower() != CSV_SIGNAL_NAME:
        return None

    current_signal = str(config.get("signal", "") or "").strip().lower()
    if current_signal == CSV_SIGNAL_NAME:
        return None

    open_trade_count = await OpenTrades.all().count()
    if open_trade_count > 0:
        return (
            "Cannot switch signal plugin to 'csv_signal' while open trades exist. "
            "Close all open trades first."
        )
    return None


def _config_update_conflict(message: str | TradeModeConfigError) -> Any:
    """Return the shared conflict response shape for config update failures."""
    if isinstance(message, TradeModeConfigError):
        return json_response(message.to_response_body(), message.status_code)
    return json_response({"error": message, "message": message}, 409)


def _config_update_failed_response() -> Any:
    """Return the shared persistence failure response for config updates."""
    return json_response({"error": "Update failed - check config.log"}, 400)


async def _read_request_json_object(
    request: Request[Any, Any, Any],
    *,
    invalid_json_message: str,
) -> tuple[dict[str, Any] | None, Any | None]:
    """Read a request body and return a JSON object or a shaped error response."""
    try:
        data = await request.json()
    except SerializationException:
        return None, json_response({"error": invalid_json_message}, 400)

    if not isinstance(data, dict):
        return None, json_response({"error": invalid_json_message}, 400)
    return data, None


async def _parse_single_config_update_request(
    key: str,
    request: Request[Any, Any, Any],
) -> tuple[ConfigUpdateMap | None, Any | None]:
    """Normalize the single-key config update request into the shared shape."""
    data, error_response = await _read_request_json_object(
        request,
        invalid_json_message="Payload must be a JSON object",
    )
    if error_response is not None or data is None:
        return None, error_response

    if "value" not in data:
        return None, json_response({"error": "Missing 'value' in request"}, 400)

    value = data["value"]
    if not _is_config_update_payload(value):
        return None, json_response(
            {"error": "Config value must be an object with 'value' and 'type'."},
            400,
        )

    return {key: value}, None


async def _parse_batch_config_update_request(
    request: Request[Any, Any, Any],
) -> tuple[ConfigUpdateMap | None, Any | None]:
    """Normalize the batch config update request into the shared shape."""
    data, error_response = await _read_request_json_object(
        request,
        invalid_json_message="'data' must be a JSON object",
    )
    if error_response is not None or data is None:
        return None, error_response

    invalid_keys = [
        key for key, value in data.items() if not _is_config_update_payload(value)
    ]
    if invalid_keys:
        invalid_key_list = ", ".join(sorted(invalid_keys))
        return None, json_response(
            {
                "error": (
                    "Config updates must be objects with 'value' and 'type'. "
                    f"Invalid keys: {invalid_key_list}"
                )
            },
            400,
        )

    return data, None


async def _validate_config_updates(
    config: Config,
    updates: ConfigUpdateMap,
) -> tuple[ConfigUpdateMap | None, Any | None]:
    """Validate shared config update invariants before persistence."""
    error_message = _validate_removed_config_keys(updates)
    if error_message:
        return None, _config_update_conflict(error_message)

    try:
        prepared_updates = await _prepare_trade_mode_updates(
            _get_raw_config_snapshot(config),
            updates,
        )
    except TradeModeConfigError as exc:
        return None, _config_update_conflict(exc)

    if "signal" in prepared_updates:
        error_message = await _validate_csv_signal_switch(
            config,
            prepared_updates["signal"],
        )
        if error_message:
            return None, _config_update_conflict(error_message)

    error_message = _validate_live_activation_boundary(config, prepared_updates)
    if error_message:
        return None, _config_update_conflict(error_message)

    return prepared_updates, None


@get(path="/config/all")
async def get_config() -> Any:
    """Return the current configuration as JSON.

    Returns:
        JSON response containing the full configuration cache.
    """
    config = await Config.instance()
    snapshot = config.snapshot()
    snapshot["trade_mode_switch_guard"] = (
        await _get_trade_mode_switch_guard(snapshot, strict=False)
    ).to_dict()
    snapshot["config_updated_at"] = await _get_latest_config_updated_at()
    return snapshot


async def _get_latest_config_updated_at() -> str | None:
    """Return the latest persisted config update timestamp as ISO text."""
    latest_row = await AppConfig.all().order_by("-updated_at").first()
    return latest_row.updated_at.isoformat() if latest_row else None


@get(path="/config/freshness")
async def get_config_freshness() -> Any:
    """Return the latest config update timestamp for stale-client detection."""
    return {
        "updated_at": await _get_latest_config_updated_at(),
    }


@get(path="/config/backup/export")
async def export_backup(include_trade_data: bool = False) -> Any:
    """Export config backup with optional trade data."""
    return await backup_service.export_backup(include_trade_data)


@get(path="/config/single/{key:str}")
async def get_config_key(key: str) -> Any:
    """Get a specific config value.

    Args:
        key: Configuration key to retrieve.

    Returns:
        JSON response with the config value, or 404 if not found.
    """
    config = await Config.instance()
    value = config.get(key)
    if value is None:
        return json_response({"error": "Key not found"}, 404)
    return {key: value}


@put(path="/config/single/{key:str}")
async def update_config_key(key: str, request: Request[Any, Any, Any]) -> Any:
    """Update a specific config key via JSON body.

    Args:
        key: Configuration key to update.

    Request body:
        {"value": {"value": new_value, "type": "str|bool|int|float"}}

    Returns:
        JSON response with success/error status.
    """
    updates, error_response = await _parse_single_config_update_request(key, request)
    if error_response is not None or updates is None:
        return error_response
    value = updates[key]

    config = await Config.instance()
    prepared_updates, validation_error = await _validate_config_updates(config, updates)
    if validation_error is not None or prepared_updates is None:
        return validation_error

    # Save to DB and trigger Pub/Sub
    try:
        if len(prepared_updates) == 1 and key in prepared_updates:
            success = await config.set(key, prepared_updates[key])
        else:
            success = await config.batch_set(prepared_updates)
    except TradeModeConfigError as exc:
        return _config_update_conflict(exc)
    except ValueError as exc:
        return _config_update_conflict(str(exc))
    if success:
        return {"message": f"Config '{key}' updated", "value": value}
    return _config_update_failed_response()


@post(path="/config/multiple")
async def update_multiple_config_keys(request: Request[Any, Any, Any]) -> Any:
    """Update multiple config keys via JSON body.

    Request body:
        {
            "key1": {"value": new_value, "type": "str|bool|int|float"},
            "key2": {"value": new_value, "type": "str|bool|int|float"},
            ...
        }

    Returns:
        JSON response with success/error status.
    """
    updates, error_response = await _parse_batch_config_update_request(request)
    if error_response is not None or updates is None:
        return error_response

    config = await Config.instance()
    prepared_updates, validation_error = await _validate_config_updates(config, updates)
    if validation_error is not None or prepared_updates is None:
        return validation_error

    try:
        success = await config.batch_set(prepared_updates)
    except TradeModeConfigError as exc:
        return _config_update_conflict(exc)
    except ValueError as exc:
        return _config_update_conflict(str(exc))

    if success:
        return {"message": "Config updated"}
    return _config_update_failed_response()


@post(path="/config/live/activate")
async def activate_live_trading(request: Request[Any, Any, Any]) -> Any:
    """Switch the instance from dry run to live mode after server-side checks."""
    try:
        data = await request.json()
    except SerializationException:
        data = {}

    if data is None:
        data = {}
    if not isinstance(data, dict):
        return json_response({"error": "Payload must be a JSON object"}, 400)

    confirm = bool(data.get("confirm", False))
    if not confirm:
        return json_response(
            {
                "error": "Live activation requires an explicit confirm flag.",
                "message": "Live activation requires an explicit confirm flag.",
            },
            400,
        )

    config = await Config.instance()
    config_snapshot = _get_config_snapshot(config)
    blockers = _find_live_activation_blockers(config_snapshot)

    if blockers:
        logging.warning(
            "Blocked live activation attempt with %s blocker(s): %s",
            len(blockers),
            ", ".join(blocker["key"] for blocker in blockers),
        )
        return json_response(
            {
                "error": "Live activation blocked until setup is complete.",
                "message": "Live activation blocked until setup is complete.",
                "blockers": blockers,
            },
            409,
        )

    if not bool(config_snapshot.get(LIVE_ACTIVATION_KEY, True)):
        logging.info("Live activation skipped because live trading is already active.")
        return {
            "message": "Live trading is already active.",
            "already_live": True,
        }

    success = await config.set(
        LIVE_ACTIVATION_KEY,
        {"value": False, "type": "bool"},
    )
    if not success:
        logging.error("Live activation failed during config persistence.")
        return json_response(
            {"error": "Live activation failed - check config.log"},
            400,
        )

    logging.info("Live activation succeeded.")
    return {
        "message": "Live trading activated.",
        "already_live": False,
    }


async def _read_confirm_flag(
    request: Request[Any, Any, Any],
) -> tuple[bool | None, Any]:
    """Return the explicit confirm flag or a shaped error response."""
    try:
        data = await request.json()
    except SerializationException:
        data = {}

    if data is None:
        data = {}
    if not isinstance(data, dict):
        return None, json_response({"error": "Payload must be a JSON object"}, 400)

    confirm = bool(data.get("confirm", False))
    if not confirm:
        return None, json_response(
            {
                "error": "This action requires an explicit confirm flag.",
                "message": "This action requires an explicit confirm flag.",
            },
            400,
        )
    return True, None


@post(path="/config/trading/pause")
async def pause_trading(request: Request[Any, Any, Any]) -> Any:
    """Pause Moonwalker for new exposure while existing exits continue."""
    _, error_response = await _read_confirm_flag(request)
    if error_response is not None:
        return error_response

    config = await Config.instance()
    if bool(config.get(GLOBAL_TRADING_PAUSED_KEY, False)):
        return {
            "message": "Moonwalker is already paused for new exposure.",
            "status": "already_paused",
            "trading_paused": True,
        }

    success = await config.set(
        GLOBAL_TRADING_PAUSED_KEY,
        {"value": True, "type": "bool"},
    )
    if not success:
        logging.error("Global trading pause failed during config persistence.")
        return json_response(
            {"error": "Trading pause failed - check config.log"},
            400,
        )

    logging.info("Moonwalker paused for new exposure.")
    return {
        "message": "Moonwalker paused for new exposure.",
        "status": "paused",
        "trading_paused": True,
    }


@post(path="/config/trading/resume")
async def resume_trading(request: Request[Any, Any, Any]) -> Any:
    """Resume Moonwalker so new exposure is allowed again."""
    _, error_response = await _read_confirm_flag(request)
    if error_response is not None:
        return error_response

    config = await Config.instance()
    if not bool(config.get(GLOBAL_TRADING_PAUSED_KEY, False)):
        return {
            "message": "Moonwalker is already accepting new exposure.",
            "status": "already_resumed",
            "trading_paused": False,
        }

    success = await config.set(
        GLOBAL_TRADING_PAUSED_KEY,
        {"value": False, "type": "bool"},
    )
    if not success:
        logging.error("Global trading resume failed during config persistence.")
        return json_response(
            {"error": "Trading resume failed - check config.log"},
            400,
        )

    logging.info("Moonwalker resumed for new exposure.")
    return {
        "message": "Moonwalker resumed for new exposure.",
        "status": "resumed",
        "trading_paused": False,
    }


@post(path="/config/backup/restore")
async def restore_backup(request: Request[Any, Any, Any]) -> Any:
    """Restore config-only or full backup payloads."""
    try:
        data = await request.json()
    except SerializationException:
        return json_response({"error": "Payload must be a JSON object"}, 400)

    if not isinstance(data, dict):
        return json_response({"error": "Payload must be a JSON object"}, 400)

    backup_payload = data.get("backup")
    restore_trade_data = bool(data.get("restore_trade_data", False))
    if not isinstance(backup_payload, dict):
        return json_response({"error": "Missing backup payload."}, 400)

    try:
        summary = await backup_service.restore_backup(
            backup_payload,
            restore_trade_data=restore_trade_data,
        )
    except TradeModeConfigError as exc:
        return json_response(exc.to_response_body(), exc.status_code)
    except ValueError as exc:
        return json_response({"error": str(exc)}, 400)
    except Exception as exc:  # noqa: BLE001 - surface restore failures to UI.
        logging.error("Backup restore failed: %s", exc, exc_info=True)
        return json_response({"error": "Backup restore failed."}, 500)

    restored_scope = "full backup" if restore_trade_data else "configuration"
    return {
        "message": f"Restored {restored_scope} successfully.",
        "result": summary,
    }


route_handlers = [
    get_config,
    get_config_freshness,
    export_backup,
    get_config_key,
    update_config_key,
    update_multiple_config_keys,
    activate_live_trading,
    pause_trading,
    resume_trading,
    restore_backup,
]
