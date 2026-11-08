"""Regression tests for the read-only backup classification preview.

The classifier is a collect-all projection of the restore's own validation
primitives; these fixtures pin every finding code and the classification
summary against actual payload shapes.
"""

import copy
import json

from service.backup_restore import (
    RECOVERY_MANIFEST_DISPOSITION,
    RECOVERY_MANIFEST_SCHEMA_VERSION,
    TRADE_TABLE_MODELS,
    BackupService,
)


def _empty_trade_data() -> dict:
    return {table_name: [] for table_name in TRADE_TABLE_MODELS}


def _config_payload(rows: list[dict]) -> dict:
    return {"schema_version": 3, "config": rows}


def _full_payload(config_rows: list[dict], trade_data: dict | None = None) -> dict:
    payload = _config_payload(config_rows)
    payload["trade_data"] = (
        trade_data if trade_data is not None else _empty_trade_data()
    )
    return payload


def _finding_codes(result: dict) -> list[str]:
    return [finding["code"] for finding in result["findings"]]


def _finding_by_code(result: dict, code: str) -> dict | None:
    return next((f for f in result["findings"] if f["code"] == code), None)


def _sealed_manifest(intents: list[dict]) -> dict:
    body = {
        "schema_version": RECOVERY_MANIFEST_SCHEMA_VERSION,
        "disposition": RECOVERY_MANIFEST_DISPOSITION,
        "intents": intents,
    }
    return {**body, "sha256": BackupService._recovery_manifest_digest(body)}


def test_classify_reports_pre_4_9_bridge_keys_as_blocking() -> None:
    """Pre-4.9 bridge keys mirror the restore refusal with the replacement."""
    result = BackupService().classify_backup(
        _config_payload(
            [
                {"key": "timezone", "value": "UTC", "value_type": "str"},
                {
                    "key": "trade_lifecycle_mode",
                    "value": "classic_dca",
                    "value_type": "str",
                },
                {"key": "dynamic_dca", "value": True, "value_type": "bool"},
            ]
        ),
        restore_trade_data=False,
    )

    classification = result["classification"]
    assert classification["trade_mode_era"] == "legacy_unspecified"
    assert "pre_4_9_bridge_keys" not in classification
    assert _finding_by_code(result, "legacy_bridge_keys_dropped") is None
    removed = [
        finding
        for finding in result["findings"]
        if finding["code"] == "removed_config_key"
    ]
    assert [finding["detail"]["key"] for finding in removed] == [
        "trade_lifecycle_mode",
        "dynamic_dca",
    ]
    assert all(finding["severity"] == "blocking" for finding in removed)
    assert "trade_mode" in removed[0]["message"]
    assert "forced_dry_run_pause" in _finding_codes(result)


def test_classify_reports_removed_config_key_as_blocking() -> None:
    """Removed config keys mirror the restore refusal with the replacement."""
    result = BackupService().classify_backup(
        _config_payload(
            [
                {
                    "key": "autopilot_max_fund",
                    "value": "300",
                    "value_type": "int",
                }
            ]
        ),
        restore_trade_data=False,
    )

    finding = _finding_by_code(result, "removed_config_key")
    assert finding is not None
    assert finding["severity"] == "blocking"
    assert "capital_max_fund" in finding["message"]


def test_classify_reports_campaign_residue_as_blocking() -> None:
    """Sidestep-era open-trade residue is blocking and names the symbols."""
    trade_data = _empty_trade_data()
    trade_data["open_trades"] = [
        {"id": 1, "symbol": "AAA/USDC", "campaign_id": 7},
        {"id": 2, "symbol": "BBB/USDC", "campaign_id": 7},
        {"id": 3, "symbol": "CCC/USDC", "campaign_id": None},
    ]
    result = BackupService().classify_backup(
        _full_payload([], trade_data), restore_trade_data=True
    )

    finding = _finding_by_code(result, "campaign_residue")
    assert finding is not None
    assert finding["severity"] == "blocking"
    assert finding["detail"]["count"] == 2
    assert finding["detail"]["symbols"] == ["AAA/USDC", "BBB/USDC"]
    assert "AAA/USDC" in finding["message"]


def test_classify_reports_dropped_columns_as_warning() -> None:
    """Rows carrying 021-dropped columns are named with era context."""
    trade_data = _empty_trade_data()
    trade_data["open_trades"] = [
        {
            "id": 1,
            "symbol": "AAA/USDC",
            "waiting_reference_price": "1.5",
            "last_transition_at": "2026-01-01T00:00:00+00:00",
        },
        {"id": 2, "symbol": "BBB/USDC", "waiting_reference_price": "2.5"},
    ]
    trade_data["trades"] = [
        {"id": 10, "symbol": "AAA/USDC", "campaign_id": 4},
    ]
    result = BackupService().classify_backup(
        _full_payload([], trade_data), restore_trade_data=True
    )

    finding = _finding_by_code(result, "dropped_trade_columns")
    assert finding is not None
    assert finding["severity"] == "warning"
    assert finding["detail"] == {
        "open_trades": {
            "waiting_reference_price": 2,
            "last_transition_at": 1,
        },
        "trades": {"campaign_id": 1},
    }
    assert "legacy sidestep-era" in finding["message"]
    assert "open_trades.waiting_reference_price (2)" in finding["message"]


def test_classify_reports_quarantined_intents_as_warning() -> None:
    """A valid sealed manifest surfaces the quarantine count pre-restore."""
    payload = _full_payload([])
    payload["sealed_recovery_manifest"] = _sealed_manifest(
        [
            {
                "id": 1,
                "operation_id": "op-1",
                "symbol": "AAA/USDC",
                "state": "persisted",
                "action": "limit_sell",
            },
            {
                "id": 2,
                "operation_id": "op-2",
                "symbol": "BBB/USDC",
                "state": "accepted",
                "action": "buy",
            },
        ]
    )
    result = BackupService().classify_backup(payload, restore_trade_data=True)

    finding = _finding_by_code(result, "quarantined_intents")
    assert finding is not None
    assert finding["severity"] == "warning"
    assert finding["detail"]["count"] == 2
    assert finding["next_action"]


def test_classify_reports_manifest_checksum_mismatch_as_blocking() -> None:
    """A corrupted manifest mirrors the restore refusal."""
    manifest = _sealed_manifest(
        [
            {
                "id": 1,
                "operation_id": "op-1",
                "symbol": "AAA/USDC",
                "state": "persisted",
                "action": "limit_sell",
            }
        ]
    )
    manifest = {**manifest, "sha256": "0" * 64}
    payload = _full_payload([])
    payload["sealed_recovery_manifest"] = manifest
    result = BackupService().classify_backup(payload, restore_trade_data=True)

    finding = _finding_by_code(result, "manifest_invalid")
    assert finding is not None
    assert finding["severity"] == "blocking"
    assert "checksum" in finding["message"]
    assert _finding_by_code(result, "quarantined_intents") is None


def test_classify_reports_accumulation_without_ownership_tables_as_blocking() -> None:
    """Accumulation rows without the full ownership set are blocking."""
    trade_data = _empty_trade_data()
    for name in (
        "accumulation_strategy_states",
        "accumulation_opportunities",
        "accumulation_attempts",
        "accumulation_lifecycle_operations",
        "accumulation_fill_checkpoints",
    ):
        del trade_data[name]
    trade_data["accumulation_activations"] = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "symbol": "AAA/USDC",
        }
    ]
    result = BackupService().classify_backup(
        _full_payload([], trade_data), restore_trade_data=True
    )

    finding = _finding_by_code(result, "accumulation_incomplete")
    assert finding is not None
    assert finding["severity"] == "blocking"
    assert "missing ownership tables" in finding["message"]


def test_classify_reports_nonterminal_portable_intents_as_blocking() -> None:
    """Nonterminal rows in the portable table mirror the restore refusal."""
    trade_data = _empty_trade_data()
    trade_data["placement_intents"] = [
        {"id": 1, "symbol": "AAA/USDC", "state": "accepted"},
    ]
    result = BackupService().classify_backup(
        _full_payload([], trade_data), restore_trade_data=True
    )

    finding = _finding_by_code(result, "invalid_placement_intents")
    assert finding is not None
    assert finding["severity"] == "blocking"


def test_classify_reports_full_restore_without_trade_data_as_blocking() -> None:
    result = BackupService().classify_backup(
        _config_payload([]), restore_trade_data=True
    )

    finding = _finding_by_code(result, "invalid_trade_data")
    assert finding is not None
    assert finding["severity"] == "blocking"


def test_classify_reports_config_only_version_id_drop_as_warning() -> None:
    """Config-only restore drops the local pin; full restore keeps it."""
    rows = [
        {
            "key": "accumulation_strategy_version_id",
            "value": "42",
            "value_type": "int",
        }
    ]

    config_only = BackupService().classify_backup(
        _config_payload(rows), restore_trade_data=False
    )
    finding = _finding_by_code(config_only, "accumulation_version_id_dropped")
    assert finding is not None
    assert finding["severity"] == "warning"

    full = BackupService().classify_backup(_full_payload(rows), restore_trade_data=True)
    assert _finding_by_code(full, "accumulation_version_id_dropped") is None


def test_classify_trade_mode_era_variants() -> None:
    """The era replaces the obsolete three-way trade-mode bucket."""
    service = BackupService()

    dynamic = service.classify_backup(
        _config_payload(
            [{"key": "trade_mode", "value": "dynamic_dca", "value_type": "str"}]
        ),
        restore_trade_data=False,
    )
    assert dynamic["classification"]["trade_mode_era"] == "dynamic_dca"

    accumulation = service.classify_backup(
        _config_payload(
            [{"key": "trade_mode", "value": "accumulation", "value_type": "str"}]
        ),
        restore_trade_data=False,
    )
    assert accumulation["classification"]["trade_mode_era"] == "accumulation"

    legacy = service.classify_backup(
        _config_payload([{"key": "timezone", "value": "UTC", "value_type": "str"}]),
        restore_trade_data=False,
    )
    assert legacy["classification"]["trade_mode_era"] == "legacy_unspecified"

    accumulation_by_rows = service.classify_backup(
        _full_payload([]), restore_trade_data=True
    )
    trade_data = _empty_trade_data()
    trade_data["open_trades"] = [
        {"id": 1, "symbol": "AAA/USDC", "lifecycle_mode": "accumulation"}
    ]
    accumulation_by_holdings = service.classify_backup(
        _full_payload([], trade_data), restore_trade_data=True
    )
    assert (
        accumulation_by_holdings["classification"]["trade_mode_era"] == "accumulation"
    )
    assert accumulation_by_holdings["classification"]["includes_accumulation"] is True
    assert accumulation_by_rows["classification"]["includes_accumulation"] is False


def test_classify_reports_unsupported_schema_version_as_blocking() -> None:
    result = BackupService().classify_backup(
        {"schema_version": 99, "config": []}, restore_trade_data=False
    )

    finding = _finding_by_code(result, "unsupported_schema_version")
    assert finding is not None
    assert finding["severity"] == "blocking"
    assert result["classification"]["trade_mode_era"] is None
    assert _finding_by_code(result, "forced_dry_run_pause") is not None


def test_classify_orders_blocking_findings_first() -> None:
    trade_data = _empty_trade_data()
    trade_data["open_trades"] = [
        {"id": 1, "symbol": "AAA/USDC", "campaign_id": 1},
    ]
    payload = _full_payload(
        [
            {
                "key": "trade_lifecycle_mode",
                "value": "classic_dca",
                "value_type": "str",
            }
        ],
        trade_data,
    )
    result = BackupService().classify_backup(payload, restore_trade_data=True)

    severities = [f["severity"] for f in result["findings"]]
    assert severities == sorted(
        severities, key={"blocking": 0, "warning": 1, "info": 2}.get
    )


def test_classify_does_not_mutate_the_payload() -> None:
    """The preview is a read projection: the operator's file must stay intact."""
    payload = _full_payload(
        [
            {
                "key": "trade_lifecycle_mode",
                "value": "classic_dca",
                "value_type": "str",
            }
        ]
    )
    original = copy.deepcopy(payload)

    BackupService().classify_backup(payload, restore_trade_data=True)

    assert payload == original
    assert json.loads(json.dumps(payload)) == original
