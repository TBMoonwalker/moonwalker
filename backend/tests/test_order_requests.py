from service.order_requests import (
    ManualBuyAddRequest,
    normalize_order_symbol,
    parse_manual_buy_add_request,
    parse_positive_float,
)


def test_normalize_order_symbol_accepts_common_formats() -> None:
    assert normalize_order_symbol("btc/usdt") == "BTC/USDT"
    assert normalize_order_symbol("btc-usdt") == "BTC/USDT"
    assert normalize_order_symbol(" btc_usdt ") == "BTC/USDT"


def test_normalize_order_symbol_rejects_invalid_shapes() -> None:
    try:
        normalize_order_symbol("btcusdt")
    except ValueError as exc:
        assert str(exc) == "Invalid symbol. Use BASE/QUOTE format."
    else:
        raise AssertionError("Expected invalid symbol to raise ValueError")


def test_parse_positive_float_rejects_invalid_and_non_positive_values() -> None:
    assert parse_positive_float("1.25", "amount") == 1.25

    for raw_value, expected_message in (
        ("abc", "Invalid amount."),
        (0, "amount must be greater than 0."),
        (-1, "amount must be greater than 0."),
    ):
        try:
            parse_positive_float(raw_value, "amount")
        except ValueError as exc:
            assert str(exc) == expected_message
        else:
            raise AssertionError("Expected invalid amount to raise ValueError")


def test_parse_manual_buy_add_request_builds_typed_request() -> None:
    request = parse_manual_buy_add_request(
        symbol="btc-usdc",
        date_input="3000",
        price_raw="80.0",
        amount_raw="0.5000",
    )

    assert request == ManualBuyAddRequest(
        symbol="BTC/USDC",
        timestamp_ms=3_000_000,
        price=80.0,
        amount=0.5,
        amount_precision=1,
    )


def test_parse_manual_buy_add_request_rejects_invalid_input() -> None:
    for kwargs, expected_message in (
        (
            {
                "symbol": "btcusdc",
                "date_input": "3000",
                "price_raw": "80.0",
                "amount_raw": "0.5",
            },
            "Invalid symbol. Use BASE/QUOTE format.",
        ),
        (
            {
                "symbol": "btc-usdc",
                "date_input": "",
                "price_raw": "80.0",
                "amount_raw": "0.5",
            },
            "Invalid date.",
        ),
        (
            {
                "symbol": "btc-usdc",
                "date_input": "3000",
                "price_raw": "0",
                "amount_raw": "0.5",
            },
            "price must be greater than 0.",
        ),
    ):
        try:
            parse_manual_buy_add_request(**kwargs)
        except ValueError as exc:
            assert str(exc) == expected_message
        else:
            raise AssertionError("Expected invalid request to raise ValueError")
