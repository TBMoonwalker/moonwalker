"""Exact, coverage-aware returns from cumulative checkpoints and fresh bid marks."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from typing import Any

import ccxt.async_support as ccxt
import model
from service.accumulation_accounting import _inventory as holding_inventory
from service.accumulation_contracts import canonical_decimal
from service.accumulation_csv_accounting import csv_inventory_origins
from service.accumulation_import import CSV_RETURN_BASIS, RETURN_BASES
from service.accumulation_reporting import _amount, _inventory
from service.trading_maintenance import trading_maintenance_barrier
from tortoise.transactions import in_transaction


def _money(value: Decimal) -> str:
    """Use stable exact decimal output, without quantization or exponent spelling."""
    if not value:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _same_inventory(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    """Compare exact values while allowing equivalent decimal spellings."""
    if left is None or right is None:
        return False
    try:
        return (
            all(
                Decimal(left[key]) == Decimal(right[key])
                for key in (
                    "net_quantity",
                    "remaining_cost",
                    "contributed_quote",
                    "disposal_proceeds",
                )
            )
            and {key: Decimal(value) for key, value in left["fees"].items()}
            == {key: Decimal(value) for key, value in right["fees"].items()}
            and left["pending_fee_reports"] == right["pending_fee_reports"] == 0
            and left["basis_provenance"] == right["basis_provenance"]
            and left["basis_provenance"] in RETURN_BASES
        )
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


async def _archived_transfers(
    conn: Any,
) -> tuple[dict[tuple[str, str], dict[str, Any]], set[str]]:
    """Verify unsold transfers at basis, without valuing unmanaged wallet coins."""
    records = (
        await model.UnsellableTrades.filter(accumulation_inventory_json__isnull=False)
        .using_db(conn)
        .values(
            "deal_id",
            "symbol",
            "execution_history_complete",
            "accumulation_inventory_json",
        )
    )
    by_deal: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_deal.setdefault(record["deal_id"], []).append(record)
    transfers: dict[tuple[str, str], dict[str, Any]] = {}
    invalid: set[str] = set()
    for operation in (
        await model.AccumulationLifecycleOperation.filter(
            action="archive_dust", status="applied"
        )
        .using_db(conn)
        .select_related("activation")
    ):
        owner = str(operation.activation_id)
        try:
            evidence = json.loads(operation.request_json)["_archive"]
            deal_id = evidence["deal_id"]
            candidates = by_deal.get(deal_id, [])
            if len(candidates) != 1:
                raise ValueError("Archived inventory is missing or ambiguous")
            record = candidates[0]
            inventory = _inventory(json.dumps(evidence["inventory"]))
            latest = (
                await model.AccumulationFillCheckpoint.filter(
                    activation_id=operation.activation_id, deal_id=deal_id
                )
                .using_db(conn)
                .order_by("-updated_at", "-id")
                .first()
            )
            origins = await csv_inventory_origins(
                conn, activation_id=operation.activation_id, deal_id=deal_id
            )
            declared = origins.get((operation.activation.symbol, deal_id))
            declared_complete = (
                declared is not None
                and declared.inventory.basis_provenance == CSV_RETURN_BASIS
            )
            if (
                evidence["schema_version"] != 1
                or evidence["activation_id"] != owner
                or evidence["account_scope"] != operation.activation.account_scope
                or evidence["symbol"] != operation.activation.symbol
                or evidence["symbol"] != record["symbol"]
                or evidence["operation_id"] != operation.operation_id
                or evidence != json.loads(record["accumulation_inventory_json"])
                or not (record["execution_history_complete"] or declared_complete)
                or inventory is None
                or latest is None
                or not latest.terminal
                or not latest.fees_complete
                or not _same_inventory(_inventory(latest.inventory_json), inventory)
                or Decimal(inventory["net_quantity"]) <= 0
                or (owner, deal_id) in transfers
            ):
                raise ValueError("Unverified archived inventory")
            transfers[(owner, deal_id)] = inventory
        except (ValueError, TypeError, KeyError, AttributeError):
            invalid.add(owner)
    return transfers, invalid


async def _token(conn: Any) -> str:
    holdings = (
        await model.OpenTrades.filter(lifecycle_mode="accumulation")
        .using_db(conn)
        .order_by("id")
        .values()
    )
    owners = (
        await model.AccumulationActivation.all()
        .using_db(conn)
        .order_by("id")
        .values("id", "holding_id", "revision", "account_scope", "state")
    )
    archives = (
        await model.UnsellableTrades.filter(accumulation_inventory_json__isnull=False)
        .using_db(conn)
        .order_by("id")
        .values("id", "accumulation_inventory_json")
    )
    return hashlib.sha256(
        json.dumps([holdings, owners, archives], sort_keys=True, default=str).encode()
    ).hexdigest()


async def _historical_state(conn: Any) -> tuple[list[dict[str, Any]], str]:
    owners = {
        row.symbol: row
        for row in await model.AccumulationActivation.all().using_db(conn)
    }
    holdings = {
        row.symbol: row
        for row in await model.OpenTrades.filter(
            lifecycle_mode="accumulation"
        ).using_db(conn)
    }
    transfers, invalid_transfers = await _archived_transfers(conn)
    origins = await csv_inventory_origins(conn)
    deals: dict[tuple[str, str], dict[str, Any]] = {
        key: {
            "acquired": Decimal(origin.inventory.remaining_cost),
            "principal": Decimal(origin.inventory.contributed_quote),
            "complete": origin.inventory.basis_provenance == CSV_RETURN_BASIS,
            "latest": None,
            "inventory": _inventory(origin.inventory.serialize()),
        }
        for key, origin in origins.items()
    }
    cursor = 0
    with localcontext() as context:
        context.prec = 512
        while True:
            batch = (
                await model.AccumulationFillCheckpoint.filter(id__gt=cursor)
                .using_db(conn)
                .select_related("placement")
                .order_by("id")
                .limit(1000)
            )
            if not batch:
                break
            for row in batch:
                cursor = row.id
                try:
                    if (
                        row.terminal
                        and row.fees_complete
                        and canonical_decimal(row.filled) == "0"
                        and canonical_decimal(row.quote_cost) == "0"
                        and all(
                            Decimal(canonical_decimal(value)) == 0
                            for value in json.loads(row.fees_json).values()
                        )
                    ):
                        continue
                except (ValueError, TypeError, AttributeError):
                    pass  # Corrupt zero-fill evidence is not silently discarded.
                symbol = row.placement.symbol
                deal = deals.setdefault(
                    (symbol, row.deal_id or f"missing-{row.id}"),
                    {
                        "acquired": Decimal(0),
                        "principal": Decimal(0),
                        "complete": bool(row.deal_id),
                        "latest": None,
                        "inventory": None,
                    },
                )
                try:
                    fees = json.loads(row.fees_json)
                    if not isinstance(fees, dict):
                        raise ValueError("Invalid fees")
                    amounts = {
                        key: Decimal(canonical_decimal(value))
                        for key, value in fees.items()
                    }
                    quote = symbol.split("/")[1]
                    if row.placement.side == "buy":
                        principal = Decimal(canonical_decimal(row.quote_cost))
                        deal["principal"] += principal
                        deal["acquired"] += principal + amounts.get(quote, Decimal(0))
                    deal["complete"] &= (
                        row.terminal
                        and row.fees_complete
                        and all(
                            value == 0 or key in symbol.split("/")
                            for key, value in amounts.items()
                        )
                    )
                except (ValueError, TypeError, KeyError):
                    deal["complete"] = False
                order = (row.updated_at, row.id)
                if deal["latest"] is None or order > deal["latest"]:
                    deal["latest"] = order
                    deal["inventory"] = _inventory(row.inventory_json)
        for symbol, holding in holdings.items():
            key = (symbol, holding.deal_id or "missing-holding")
            deal = deals.setdefault(
                key,
                {
                    "acquired": Decimal(0),
                    "principal": Decimal(0),
                    "complete": False,
                    "inventory": None,
                },
            )
            deal["holding"] = holding
        result = []
        for (symbol, deal_id), deal in deals.items():
            holding = deal.get("holding")
            inv = deal["inventory"]
            complete = bool(
                deal["complete"]
                and inv is not None
                and inv["pending_fee_reports"] == 0
                and inv["basis_provenance"] in RETURN_BASES
            )
            owner = owners.get(symbol)
            transferred_cost = Decimal(0)
            transfer = transfers.get((str(owner.id), deal_id)) if owner else None
            complete &= owner is None or str(owner.id) not in invalid_transfers
            if holding is not None:
                owner = owners.get(symbol)
                owned = owner is not None and owner.holding_id == holding.id
                quantity, cost = (
                    holding.accumulation_net_quantity,
                    holding.accumulation_remaining_cost,
                )
                complete &= (
                    (holding.execution_history_complete or (symbol, deal_id) in origins)
                    and holding.accumulation_basis_provenance in RETURN_BASES
                    and owned
                )
                complete &= (
                    inv is not None
                    and inv["net_quantity"] == quantity
                    and inv["remaining_cost"] == cost
                )
                scope = owner.account_scope if owned else None
            elif transfer is not None and _same_inventory(inv, transfer):
                # A transfer removes managed basis, not sale proceeds or a loss.
                quantity, cost, scope, owned = "0", "0", None, True
                transferred_cost = Decimal(transfer["remaining_cost"])
            else:
                quantity, cost, scope = "0", "0", None
                complete &= (
                    inv is not None
                    and inv["net_quantity"] == "0"
                    and inv["remaining_cost"] is not None
                    and Decimal(inv["remaining_cost"]) == 0
                )
                owned = True
                if (
                    inv is None
                    or inv["net_quantity"] is None
                    or Decimal(inv["net_quantity"]) != 0
                ):
                    quantity, cost, owned = None, None, False
            try:
                quantity = canonical_decimal(quantity)
                cost = canonical_decimal(cost) if cost is not None else None
                complete &= (
                    inv is not None
                    and inv["contributed_quote"] is not None
                    and Decimal(inv["contributed_quote"]) == deal["principal"]
                )
                realized = (
                    Decimal(inv["disposal_proceeds"])
                    + Decimal(cost or "0")
                    + transferred_cost
                    - deal["acquired"]
                    if complete
                    else None
                )
            except (ValueError, TypeError):
                quantity, cost, realized, complete = None, None, None, False
            result.append(
                {
                    "symbol": symbol,
                    "deal_id": deal_id,
                    "quantity": quantity,
                    "cost": cost,
                    "realized": realized,
                    "complete": bool(complete),
                    "owned": owned,
                    "scope": scope,
                    "live": holding is not None or not owned,
                }
            )
        # An orphan registry binding is incomplete even when no holding survived.
        for owner in owners.values():
            missing_declared = False
            if (
                owner.holding_id is None
                and owner.symbol not in holdings
                and owner.observations_initialized
                and owner.state != "stopped"
            ):
                entry = (
                    await model.AccumulationLifecycleOperation.filter(
                        activation=owner,
                        action__in=[
                            "activate",
                            "correct_import",
                            "retry_entry",
                            "reactivate",
                        ],
                    )
                    .using_db(conn)
                    .order_by("-id")
                    .first()
                )
                if entry is not None and entry.action != "reactivate":
                    try:
                        missing_declared = (
                            json.loads(entry.request_json).get("source") == "csv"
                        )
                    except (ValueError, TypeError):
                        missing_declared = True
            if (
                owner.holding_id is not None or missing_declared
            ) and owner.symbol not in holdings:
                result.append(
                    {
                        "symbol": owner.symbol,
                        "quantity": None,
                        "cost": None,
                        "realized": None,
                        "complete": False,
                        "owned": False,
                        "scope": None,
                        "live": True,
                    }
                )
        return result, await _token(conn)


async def _historical_realized_history(
    rows: list[dict[str, Any]], conn: Any
) -> tuple[list[dict[str, str]], bool]:
    """Verify dated execution deltas against cumulative checkpoint return totals."""
    if not all(row["complete"] for row in rows):
        return [], False
    valid = {row.get("deal_id") for row in rows}
    expected: dict[str, Decimal] = {}
    with localcontext() as context:
        context.prec = 512
        for row in rows:
            quote = row["symbol"].split("/")[1]
            expected[quote] = expected.get(quote, Decimal(0)) + row["realized"]
    daily: dict[tuple[str, str, str], Decimal] = {}
    actual: dict[str, Decimal] = {}
    cursor = 0
    with localcontext() as context:
        context.prec = 512
        while True:
            batch = (
                await model.TradeExecutions.filter(
                    id__gt=cursor, role="accumulation_sell"
                )
                .using_db(conn)
                .order_by("id")
                .limit(1000)
            )
            if not batch:
                break
            for row in batch:
                cursor = row.id
                try:
                    if row.deal_id not in valid:
                        raise ValueError("Missing checkpoint identity")
                    delta = json.loads(row.metadata_json)["accumulation"]["delta"]
                    quote = row.symbol.split("/")[1]
                    value = (
                        Decimal(canonical_decimal(delta["quote_cost"]))
                        - Decimal(canonical_decimal(delta["fees"].get(quote, "0")))
                        - Decimal(canonical_decimal(delta["allocated_basis"]))
                    )
                    date = (
                        datetime.fromtimestamp(int(row.timestamp) / 1000, timezone.utc)
                        .date()
                        .isoformat()
                    )
                    daily[(row.symbol, quote, date)] = (
                        daily.get((row.symbol, quote, date), Decimal(0)) + value
                    )
                    actual[quote] = actual.get(quote, Decimal(0)) + value
                except (ValueError, TypeError, KeyError, OverflowError, OSError):
                    return [], False
        if any(
            actual.get(quote, Decimal(0)) != value for quote, value in expected.items()
        ) or any(quote not in expected for quote in actual):
            return [], False
    return [
        {"symbol": symbol, "quote": quote, "date": date, "profit": format(value, "f")}
        for (symbol, quote, date), value in sorted(daily.items())
    ], True


_REBUILD_LOCK = asyncio.Lock()


async def ensure_return_totals() -> None:
    """Rebuild missing caches or the legacy dust invalidation once in maintenance."""
    owners = await model.AccumulationActivation.all().values_list("id", flat=True)
    cached_rows = await model.AccumulationReturnTotals.all()
    cached = {row.activation_id for row in cached_rows}
    transfers, invalid = await _archived_transfers(None)
    repair = {
        row.activation_id
        for row in cached_rows
        if not row.provenance_complete
        and row.history_complete
        and str(row.activation_id) not in invalid
        and any(owner == str(row.activation_id) for owner, _ in transfers)
    }
    if set(owners) <= cached and not repair:
        return
    async with _REBUILD_LOCK:
        async with trading_maintenance_barrier.maintenance(), in_transaction() as conn:
            owners = await model.AccumulationActivation.all().using_db(conn)
            cached_rows = await model.AccumulationReturnTotals.all().using_db(conn)
            cached = {row.activation_id for row in cached_rows}
            transfers, invalid = await _archived_transfers(conn)
            repair = {
                row.activation_id
                for row in cached_rows
                if not row.provenance_complete
                and row.history_complete
                and str(row.activation_id) not in invalid
                and any(owner == str(row.activation_id) for owner, _ in transfers)
            }
            missing = [
                row for row in owners if row.id not in cached or row.id in repair
            ]
            if not missing:
                return
            rows, _ = await _historical_state(conn)
            daily, history_complete = await _historical_realized_history(rows, conn)
            with localcontext() as context:
                context.prec = 512
                for owner in missing:
                    await (
                        model.AccumulationReturnDay.filter(activation=owner)
                        .using_db(conn)
                        .delete()
                    )
                    selected = [row for row in rows if row["symbol"] == owner.symbol]
                    complete = all(row["complete"] for row in selected)
                    realized = sum(
                        (
                            row["realized"]
                            for row in selected
                            if row["realized"] is not None
                        ),
                        Decimal(0),
                    )
                    live = [row for row in selected if row["live"]]
                    last_quantity = (
                        live[0]["quantity"]
                        if len(live) == 1
                        else "0"
                        if not live
                        else None
                    )
                    last_cost = (
                        live[0]["cost"] if len(live) == 1 else "0" if not live else None
                    )
                    await model.AccumulationReturnTotals.update_or_create(
                        activation=owner,
                        defaults={
                            "realized_quote": format(realized, "f"),
                            "provenance_complete": complete,
                            "history_complete": history_complete,
                            "last_quantity": last_quantity,
                            "last_cost": last_cost,
                        },
                        using_db=conn,
                    )
                    for day in daily:
                        if day["symbol"] == owner.symbol:
                            await model.AccumulationReturnDay.update_or_create(
                                activation=owner,
                                date=day["date"],
                                defaults={"profit": day["profit"]},
                                using_db=conn,
                            )


async def _state(conn: Any) -> tuple[list[dict[str, Any]], str]:
    """Routine work returns O(registrations) rows, never lifetime fills."""
    owners = await model.AccumulationActivation.all().using_db(conn)
    holdings = {
        row.symbol: row
        for row in await model.OpenTrades.filter(
            lifecycle_mode="accumulation"
        ).using_db(conn)
    }
    totals = {
        row.activation_id: row
        for row in await model.AccumulationReturnTotals.all().using_db(conn)
    }
    transfers, invalid_transfers = await _archived_transfers(conn)
    result = []
    for owner in owners:
        holding = holdings.pop(owner.symbol, None)
        cached = totals.get(owner.id)
        complete = cached is not None and cached.provenance_complete
        complete &= str(owner.id) not in invalid_transfers
        complete &= (
            not await model.AccumulationFillCheckpoint.filter(
                activation=owner, fees_complete=False
            )
            .using_db(conn)
            .exists()
        )
        complete &= (
            not await model.AccumulationFillCheckpoint.filter(
                activation=owner, terminal=False
            )
            .using_db(conn)
            .exists()
        )
        latest = (
            await model.AccumulationFillCheckpoint.filter(activation=owner)
            .using_db(conn)
            .order_by("-updated_at", "-id")
            .first()
        )
        inv = _inventory(latest.inventory_json) if latest else None
        origin = None
        declared_basis = (
            holding.accumulation_basis_provenance
            if holding
            else inv.get("basis_provenance")
            if inv
            else None
        ) == CSV_RETURN_BASIS
        if declared_basis:
            deal_id = holding.deal_id if holding else latest.deal_id
            origin = (
                await csv_inventory_origins(
                    conn, activation_id=owner.id, deal_id=deal_id
                )
            ).get((owner.symbol, deal_id))
            complete &= (
                origin is not None
                and origin.inventory.basis_provenance == CSV_RETURN_BASIS
            )
        if inv is None and origin is not None:
            inv = _inventory(origin.inventory.serialize())
        owned = holding is not None and owner.holding_id == holding.id
        quantity, cost = "0", "0"
        live = holding is not None or owner.holding_id is not None
        if holding is not None:
            try:
                current = holding_inventory(holding)
                quantity, cost = current.quantity, current.remaining_cost
                complete &= (
                    owned
                    and (holding.execution_history_complete or origin is not None)
                    and current.basis_provenance in RETURN_BASES
                    and current.pending_fee_reports == 0
                )
                complete &= (
                    inv is not None
                    and inv["net_quantity"] == quantity
                    and inv["remaining_cost"] == cost
                )
            except (ValueError, TypeError):
                quantity, cost, complete, owned = None, None, False, False
        elif (
            owner.holding_id is None
            and latest is not None
            and _same_inventory(inv, transfers.get((str(owner.id), latest.deal_id), {}))
        ):
            pass  # Settled unsold transfer: managed inventory is empty at basis.
        elif (
            owner.holding_id is not None
            or cached is not None
            and _amount(cached.last_quantity) != "0"
            or inv is not None
            and inv["net_quantity"] not in {None, "0"}
        ):
            quantity, cost, complete, live = None, None, False, True
        result.append(
            {
                "symbol": owner.symbol,
                "quantity": quantity,
                "cost": cost,
                "realized": Decimal(cached.realized_quote)
                if cached is not None and complete
                else None,
                "complete": bool(complete),
                "owned": owned if live else True,
                "scope": owner.account_scope,
                "live": live,
                "history_complete": bool(cached and cached.history_complete),
            }
        )
    for holding in holdings.values():
        result.append(
            {
                "symbol": holding.symbol,
                "quantity": None,
                "cost": None,
                "realized": None,
                "complete": False,
                "owned": False,
                "scope": None,
                "live": True,
                "history_complete": False,
            }
        )
    return result, await _token(conn)


async def accumulated_daily_history(
    since: str | None = None, *, connection: Any = None
) -> list[dict[str, str]]:
    """Read derived calendar aggregates, bounded by the requested chart range."""
    query = model.AccumulationReturnDay.all()
    if since is not None:
        query = query.filter(date__gte=since)
    if connection is not None:
        query = query.using_db(connection)
    rows = await query.select_related("activation").order_by("date")
    daily: dict[tuple[str, str], Decimal] = {}
    with localcontext() as context:
        context.prec = 512
        for row in rows:
            key = (row.activation.symbol.split("/")[1], row.date)
            daily[key] = daily.get(key, Decimal(0)) + Decimal(row.profit)
    return [
        {"quote": quote, "date": date, "profit": _money(value)}
        for (quote, date), value in sorted(daily.items())
    ]


async def accumulation_performance(adapter: Any) -> dict[str, Any]:
    """Never hold a database transaction across market I/O; reject changing ledgers."""
    await ensure_return_totals()
    async with in_transaction() as conn:
        rows, token = await _state(conn)
        includes_csv = (
            await model.AccumulationLifecycleOperation.filter(
                status="applied", request_json__contains='"_csv_deal_id"'
            )
            .using_db(conn)
            .exists()
        )
        history_complete = all(
            row["complete"] and row["history_complete"] for row in rows
        )
        since = (
            datetime.fromtimestamp(adapter.clock_ms() / 1000, timezone.utc).date()
            - timedelta(days=7)
        ).isoformat()
        history = (
            await accumulated_daily_history(since, connection=conn)
            if history_complete
            else []
        )
    try:
        config = adapter.config()
        scope = await adapter.account_scope(config)
    except (ValueError, OSError, TimeoutError, ccxt.BaseError):
        config, scope = None, None
    symbols = sorted(
        {
            row["symbol"]
            for row in rows
            if row["live"] and row["quantity"] not in {None, "0"}
        }
    )
    try:
        marks = (
            await adapter.mark_quotes(symbols, config)
            if symbols and config is not None
            else {}
        )
    except (ValueError, OSError, TimeoutError, ccxt.BaseError):
        marks = {}
    async with in_transaction() as conn:
        current = await _token(conn)
    try:
        stable = current == token and (config is None or adapter.config() == config)
    except ValueError:
        stable = False
    now = adapter.clock_ms()
    valid_until = now + 2000
    groups: dict[str, Any] = {}
    with localcontext() as context:
        context.prec = 512
        for row in rows:
            group = groups.setdefault(
                row["symbol"].split("/")[1],
                {
                    "market_value": Decimal(0),
                    "unrealized": Decimal(0),
                    "realized": Decimal(0),
                    "complete": stable,
                    "realized_complete": stable,
                    "valuation_complete": stable,
                    "unknown_deal_count": 0,
                    "live_holding_count": 0,
                },
            )
            complete = stable and row["complete"]
            if not complete:
                group["realized_complete"] = False
            if row["realized"] is not None:
                group["realized"] += row["realized"]
            if row["live"]:
                group["live_holding_count"] += 1
                mark = marks.get(row["symbol"])
                try:
                    if (
                        not stable
                        or not row["owned"]
                        or row["scope"] != scope
                        or row["quantity"] is None
                        or not isinstance(mark, dict)
                        or type(mark.get("observed_at_ms")) is not int
                        or not 0 <= now - mark["observed_at_ms"] <= 10000
                    ):
                        raise ValueError("Unverified or stale mark")
                    value = Decimal(canonical_decimal(row["quantity"])) * Decimal(
                        canonical_decimal(mark["bid"], positive=True)
                    )
                    group["market_value"] += value
                    valid_until = min(valid_until, mark["observed_at_ms"] + 10000)
                    if complete and row["cost"] is not None:
                        group["unrealized"] += value - Decimal(row["cost"])
                except (ValueError, TypeError, KeyError):
                    group["valuation_complete"] = False
                    complete = False
            if not complete:
                group["unknown_deal_count"] += 1
                group["complete"] = False
        output = []
        for quote, group in sorted(groups.items()):
            output.append(
                {
                    "quote": quote,
                    "complete": group["complete"],
                    "unknown_deal_count": group["unknown_deal_count"],
                    "live_holding_count": group["live_holding_count"],
                    "market_value": _money(group["market_value"])
                    if group["valuation_complete"]
                    else None,
                    "realized": _money(group["realized"])
                    if group["realized_complete"]
                    else None,
                    "unrealized": _money(group["unrealized"])
                    if group["complete"]
                    else None,
                    "total_return": _money(group["realized"] + group["unrealized"])
                    if group["complete"]
                    else None,
                }
            )
    return {
        "complete": stable and all(group["complete"] for group in output),
        "observed_at_ms": now,
        "valid_until_ms": valid_until,
        "basis": "fresh_bid_before_future_sale_fees",
        "includes_csv_declarations": includes_csv,
        "by_quote": output,
        "history_complete": stable and history_complete,
        "realized_by_date": history if stable and history_complete else [],
        "reason": None if stable else "ledger_changed_during_valuation",
    }
