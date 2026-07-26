"""Tests for the versioned frontend-safe configuration contract."""

from __future__ import annotations

from controller.config import get_config_schema
from litestar import Litestar
from litestar.testing import TestClient
from service.config import DEFAULT_CONFIG_VALUES
from service.config_contract import CONFIG_FIELDS, public_config_contract


def test_config_contract_defaults_drive_runtime_defaults() -> None:
    """Migrated config slices should have one backend default source."""
    for key, field in CONFIG_FIELDS.items():
        public_field = field.to_public_dict()
        if "default" in public_field:
            assert DEFAULT_CONFIG_VALUES[key] == public_field["default"]


def test_config_contract_never_exposes_secret_defaults() -> None:
    """Credential fields must remain write-only without serialized values."""
    contract = public_config_contract()
    for key in (
        "delisting_schedule_api_key",
        "delisting_schedule_api_secret",
    ):
        field = contract["fields"][key]
        assert field["sensitive"] is True
        assert field["write_only"] is True
        assert "default" not in field


def test_config_schema_endpoint_returns_versioned_contract() -> None:
    """Dashboard clients should be able to fetch the canonical contract."""
    app = Litestar(route_handlers=[get_config_schema])
    with TestClient(app=app) as client:
        response = client.get("/config/schema")

    assert response.status_code == 200
    assert response.json() == public_config_contract()
