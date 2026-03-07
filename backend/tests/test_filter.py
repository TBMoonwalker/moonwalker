from service.filter import Filter


def test_has_enough_volume_accepts_higher_range() -> None:
    filt = Filter()
    volume = {"size": 5, "range": "M"}
    assert filt.has_enough_volume("B", 1, volume) is True


def test_has_enough_volume_rejects_lower_size_same_range() -> None:
    filt = Filter()
    volume = {"size": 10, "range": "M"}
    assert filt.has_enough_volume("M", 5, volume) is False


def test_allow_and_deny_lists() -> None:
    filt = Filter()
    assert filt.is_on_allowed_list("BTC", ["BTC", "ETH"]) is True
    assert filt.is_on_allowed_list("XRP", ["BTC", "ETH"]) is False
    assert filt.is_on_deny_list("SCAM", ["SCAM"]) is True
    assert filt.is_on_deny_list("BTC", ["SCAM"]) is False
