from service.config_runtime_store import ConfigEntry, ConfigRuntimeStore


def test_runtime_store_merges_defaults_entries_and_metadata() -> None:
    store = ConfigRuntimeStore()
    store.replace_entries(
        [
            ConfigEntry(key="timezone", value_type="str", value="Europe/Vienna"),
            ConfigEntry(key="dry_run", value_type="bool", value=False),
        ]
    )
    store.set_metadata({"signal_plugins": ["asap", "csv_signal"]})

    snapshot = store.snapshot(defaults={"tp_spike_confirm_enabled": False})

    assert snapshot["timezone"] == "Europe/Vienna"
    assert snapshot["dry_run"] is False
    assert snapshot["tp_spike_confirm_enabled"] is False
    assert snapshot["signal_plugins"] == ["asap", "csv_signal"]


def test_runtime_store_returns_defensive_values() -> None:
    store = ConfigRuntimeStore()
    store.set_metadata({"signal_plugins": ["asap"]})

    signal_plugins = store.get("signal_plugins", defaults={})
    assert signal_plugins == ["asap"]
    signal_plugins.append("fake_plugin")

    assert store.get("signal_plugins", defaults={}) == ["asap"]
