"""Fee-aware CSV declarations preserve exact inventory and legacy identities."""

import copy
import json
from decimal import Decimal

import pytest
from service.accumulation_contracts import AccumulationStateError
from service.accumulation_import import AccumulationImport, parse_accumulation_csv
from service.csv_signal_import import CSVSignalImportService

HEADER = "date;symbol;price;amount;fee;fee_currency;amount_type;fee_quote_value\n"


def parse(row):
    return parse_accumulation_csv(
        HEADER + "2026-01-01;BTC/USDC;100;" + row, "USDC", now_ms=1800000000000
    )[0]


@pytest.mark.parametrize(
    "row,quantity,cost,contributed,fees",
    [
        ("0.99;0.01;BTC;net;", "0.99", "100", "100", {"BTC": "0.01"}),
        ("1;0.01;BTC;gross;", "0.99", "100", "100", {"BTC": "0.01"}),
        ("1;1;USDC;net;", "1", "101", "100", {"USDC": "1"}),
        ("1;1;USDC;gross;1", "1", "101", "100", {"USDC": "1"}),
        ("1;0.02;BNB;net;2", "1", "102", "100", {"BNB": "0.02"}),
        ("1;0;;net;", "1", "100", "100", {"USDC": "0"}),
        ("1;0.0;;net;", "1", "100", "100", {"USDC": "0"}),
    ],
)
def test_declared_fees_are_applied_once(row, quantity, cost, contributed, fees):
    imported = parse(row)
    inventory = imported.inventory()
    assert Decimal(imported.quantity) == Decimal(quantity)
    assert Decimal(imported.cost) == Decimal(cost)
    assert Decimal(inventory.contributed_quote) == Decimal(contributed)
    assert inventory.fees == fees
    assert inventory.pending_fee_reports == 0
    assert inventory.basis_provenance == "csv_declared_fees"
    assert (
        AccumulationImport.from_dict(json.loads(json.dumps(imported.to_dict())))
        == imported
    )


@pytest.mark.parametrize(
    "row",
    [
        "1;-1;BTC;net;",
        "1;NaN;USDC;net;",
        "1;Infinity;USDC;net;",
        "1;1;;net;",
        "1;;BTC;net;",
        "1;;;gross;",
        "1;1;BTC;gross;",
        "1;0.1;BTC;wrong;",
        "1;1;USDC;net;2",
        "1;1;BTC;net;1",
        "1;1;BNB;net;-1",
        "1;1;BNB;net;0",
        "1;0;USDC;net;2",
    ],
)
def test_invalid_fee_declarations_fail_closed(row):
    with pytest.raises(AccumulationStateError):
        parse(row)


def test_omitted_fees_and_unvalued_external_fees_remain_unknown():
    unknown = parse("1;;;net;").inventory()
    assert unknown.pending_fee_reports == 1
    assert unknown.basis_provenance == "csv_declared_fees_unknown"
    external = parse("1;0.02;BNB;net;").inventory()
    assert external.pending_fee_reports == 0
    assert external.basis_provenance == "unvalued_external_fees"


def test_legacy_identity_and_precision_are_preserved():
    imported = parse_accumulation_csv(
        "date;symbol;price;amount\n2026-01-01;BTC/USDC;100.000000000000001;0.1234567890123456789",
        "USDC",
        now_ms=1800000000000,
    )[0]
    assert len(imported.entries[0]) == 3
    assert imported.quantity == "0.1234567890123456789"
    assert imported.cost == "12.3456789012345680134567890123456789"
    assert imported.inventory().pending_fee_reports == 1
    assert AccumulationImport.from_dict(imported.to_dict()) == imported


def test_tampered_fee_totals_and_duplicate_purchases_are_rejected():
    imported = parse("1;1;USDC;net;")
    raw = copy.deepcopy(imported.to_dict())
    raw["cost"] = "100"
    with pytest.raises(AccumulationStateError):
        AccumulationImport.from_dict(raw)
    row = "2026-01-01;BTC/USDC;100;1;1;USDC;net;\n"
    with pytest.raises(AccumulationStateError, match="Duplicate"):
        parse_accumulation_csv(HEADER + row + row, "USDC", now_ms=1800000000000)


def test_six_column_defaults_and_classic_csv_use_the_same_net_semantics():
    csv = "date;symbol;price;amount;fee;fee_currency\n2026-01-01;BTC/USDC;100;0.99;0.01;BTC"
    imported = parse_accumulation_csv(csv, "USDC", now_ms=1800000000000)[0]
    assert Decimal(imported.quantity) == Decimal("0.99")
    rows = CSVSignalImportService()._parse_csv_rows(csv, "USDC")["BTC/USDC"]
    assert rows[0]["amount"] == 0.99
    assert Decimal(rows[0]["cost"]) == 100
    assert Decimal(rows[0]["base_fee"]) == Decimal("0.01")
