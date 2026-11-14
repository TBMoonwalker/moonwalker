"""Regression coverage for malformed backup previews."""

import pytest
from service.backup_restore import ACCUMULATION_TABLE_MODELS, BackupService

# Regression: malformed backup values must yield blocking preview findings.
# Found by /qa on 2026-11-12 using synthetic service inputs.
# Value: protects=preview validation; fails_when=malformed values raise;
# why_new=existing tests use valid shapes; seam=none; no_claim=live restore behavior.


@pytest.mark.parametrize("schema_version", [[], {}])
def test_unhashable_schema_version_returns_blocking_finding(schema_version: object):
    """A malformed schema version must be reported instead of raising."""
    result = BackupService().classify_backup(
        {"schema_version": schema_version, "config": []}, restore_trade_data=False
    )
    assert any(
        finding["code"] == "unsupported_schema_version"
        and finding["severity"] == "blocking"
        for finding in result["findings"]
    )


def test_invalid_accumulation_table_returns_blocking_finding():
    """A malformed table must not hide its validation finding behind a KeyError."""
    table = next(iter(ACCUMULATION_TABLE_MODELS))
    result = BackupService().classify_backup(
        {"schema_version": 3, "config": [], "trade_data": {table: None}},
        restore_trade_data=True,
    )
    assert any(
        finding["code"] == "invalid_trade_data"
        and finding["severity"] == "blocking"
        and finding["detail"]["table_name"] == table
        for finding in result["findings"]
    )
