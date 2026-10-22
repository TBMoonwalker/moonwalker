"""Server-owned eligibility for a single ASAP base order before strategy warmup."""

import json

import model
from tortoise.backends.base.client import BaseDBAsyncClient


async def is_initial_asap_entry(
    activation: model.AccumulationActivation,
    connection: BaseDBAsyncClient | None = None,
) -> bool:
    """Require an unapurchased ASAP registration, never a CSV or closed holding."""
    if (
        activation.state != "enabled"
        or activation.explicitly_paused
        or activation.holding_id is not None
        or activation.consumption_revision != 0
    ):
        return False
    entry = await (
        model.AccumulationLifecycleOperation.filter(
            activation=activation, action="activate"
        )
        .using_db(connection)
        .order_by("id")
        .first()
    )
    if entry is None or json.loads(entry.request_json).get("source") != "asap":
        return False
    # Survive a deleted holding, strategy switch, restart and partial-fill recovery.
    return (
        not await model.AccumulationOpportunity.filter(
            activation=activation, consumed_at__isnull=False
        )
        .using_db(connection)
        .exists()
    )
