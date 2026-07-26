"""Regression coverage for public configuration credential redaction."""

import json

from service.config import Config
from service.config_redaction import (
    REDACTED_SECRET_VALUE,
    merge_redacted_config_overrides,
    redact_config_value,
    restore_redacted_config_value,
)


# Regression: ISSUE-001 — saved credentials must never be returned to dashboard clients.
def test_public_config_snapshot_redacts_direct_and_nested_credentials(
    monkeypatch,
) -> None:
    """Public snapshots expose markers while leaving ordinary settings intact."""
    config = Config()
    monkeypatch.setattr(
        config,
        "snapshot",
        lambda: {
            "exchange": "binance",
            "key": "exchange-key",
            "secret": "exchange-secret",
            "delisting_schedule_api_key": "schedule-key",
            "delisting_schedule_api_secret": "schedule-secret",
            "marketcap_cmc_api_key": "market-data-key",
            "monitoring_telegram_bot_token": "telegram-token",
            "signal_settings": json.dumps(
                {
                    "api_url": "https://signals.example.test",
                    "api_key": "signal-key",
                    "headers": {
                        "Authorization": "Bearer private-token",
                        "Cookie": "session=private-cookie",
                        "X-Auth": "custom-private-token",
                        "Accept": "application/json",
                    },
                    "subscribe_message": {
                        "action": "subscribe",
                        "token": ["nested", "private-token"],
                    },
                }
            ),
        },
    )

    snapshot = config.public_snapshot()
    signal_settings = json.loads(snapshot["signal_settings"])

    assert snapshot["exchange"] == "binance"
    assert snapshot["key"] == REDACTED_SECRET_VALUE
    assert snapshot["secret"] == REDACTED_SECRET_VALUE
    assert snapshot["delisting_schedule_api_key"] == REDACTED_SECRET_VALUE
    assert snapshot["delisting_schedule_api_secret"] == REDACTED_SECRET_VALUE
    assert snapshot["marketcap_cmc_api_key"] == REDACTED_SECRET_VALUE
    assert snapshot["monitoring_telegram_bot_token"] == REDACTED_SECRET_VALUE
    assert signal_settings["api_url"] == "https://signals.example.test"
    assert signal_settings["api_key"] == REDACTED_SECRET_VALUE
    assert signal_settings["headers"] == {
        "Authorization": REDACTED_SECRET_VALUE,
        "Cookie": REDACTED_SECRET_VALUE,
        "X-Auth": REDACTED_SECRET_VALUE,
        "Accept": REDACTED_SECRET_VALUE,
    }
    assert signal_settings["subscribe_message"] == REDACTED_SECRET_VALUE


# Regression: ISSUE-001 — saving unrelated edits must preserve server-side credentials.
def test_redacted_config_updates_restore_existing_credentials() -> None:
    """Redaction markers and empty credential fields resolve to current values."""
    current = {
        "exchange": "binance",
        "key": "exchange-key",
        "secret": "exchange-secret",
        "delisting_schedule_api_key": "schedule-key",
        "delisting_schedule_api_secret": "schedule-secret",
    }

    merged = merge_redacted_config_overrides(
        current,
        {
            "exchange": "kraken",
            "key": REDACTED_SECRET_VALUE,
            "secret": "",
            "delisting_schedule_api_key": REDACTED_SECRET_VALUE,
            "delisting_schedule_api_secret": "",
        },
    )

    assert merged == {
        "exchange": "kraken",
        "key": "exchange-key",
        "secret": "exchange-secret",
        "delisting_schedule_api_key": "schedule-key",
        "delisting_schedule_api_secret": "schedule-secret",
    }


# Regression: ISSUE-001 — nested signal credentials survive non-secret edits.
def test_signal_settings_restore_nested_redaction_markers() -> None:
    """Signal edits preserve nested API keys and authorization headers."""
    current = json.dumps(
        {
            "api_url": "https://old.example.test",
            "api_key": "signal-key",
            "headers": {
                "Authorization": "Bearer private-token",
                "Cookie": "session=private-cookie",
                "Accept": "application/json",
            },
            "subscribe_message": {
                "action": "subscribe",
                "token": ["nested", "private-token"],
            },
        }
    )
    incoming = json.loads(redact_config_value("signal_settings", current))
    incoming["api_url"] = "https://new.example.test"

    restored = json.loads(
        restore_redacted_config_value(
            "signal_settings",
            json.dumps(incoming),
            current,
        )
    )

    assert restored == {
        "api_url": "https://new.example.test",
        "api_key": "signal-key",
        "headers": {
            "Authorization": "Bearer private-token",
            "Cookie": "session=private-cookie",
            "Accept": "application/json",
        },
        "subscribe_message": {
            "action": "subscribe",
            "token": ["nested", "private-token"],
        },
    }
