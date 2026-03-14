from helper.utils import Utils


def test_split_symbol_handles_base_containing_quote_substring() -> None:
    utils = Utils()

    assert utils.split_symbol("MUSDCUSDC", "USDC") == "MUSDC/USDC"


def test_split_symbol_raises_when_unsuffixed_pair_does_not_match_quote() -> None:
    utils = Utils()

    try:
        utils.split_symbol("MUSDCBTC", "USDC")
    except ValueError as exc:
        assert "does not end with quote currency" in str(exc)
    else:
        raise AssertionError("Expected ValueError for mismatched quote currency")
