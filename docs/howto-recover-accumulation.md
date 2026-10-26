# How to recover an accumulation holding

Resolve an entry, order or inventory blocker while retaining its recorded
quantity, cost, fees and exchange identity.

## Prerequisites

- Access to the affected installation's **Open trades** and exchange records.
- A full backup before inventory or account repair. Follow
  [backup and restore](accumulation.md#backup-and-restore).
- The intended demo or live credentials. These environments have separate
  ownership and cannot be rebound into each other.

## Identify the current blocker

1. Expand the affected symbol in **Open trades** and read the status and available
   recovery controls. Confirm that you are viewing the correct installation,
   port and symbol. Separate installations have separate databases and workers.
2. If status is stale, reconnect its stream or choose **Refresh status**. Do not
   submit an action based on an old revision.
3. Follow the matching path below. Use only the actions offered for that state;
   resolving one blocker can reveal another.

| State or symptom | Next step |
| --- | --- |
| Entry check incomplete | Correct credentials, market settings or CSV inventory, then retry the entry check. Pending eligible ASAP entries can continue automatically with their existing request. CSV failures require an explicit retry. |
| Waiting for a fresh candle | Wait for the next completed strategy candle. This is normal after initialization, restart, resume or switching. |
| Initializing accumulation strategy | Check continuous completed history and exchange access. Persistent initialization is not proof of normal strategy evaluation. |
| Unconfirmed request | Retry the same request using the retained operation ID and full payload. Do not create a replacement order to bypass uncertainty. |
| Closing | Resolve outstanding order/fee evidence first, then handle the remainder below. |
| Account ownership needs review | Use the account path below; wallet balance alone does not prove order ownership. |
| Inventory needs repair | Restore the recorded inventory link from server-held evidence, or restore a complete consistent backup. |
| Net return unavailable | Check ownership, acquisition basis, fees, fresh bid and quote coverage. Unknown evidence is not zero profit. |

## Resolve an uncertain or restored order

1. Locate the existing exchange order or deterministic client order identity.
   Inspect its filled quantity, cost and fees in the exchange account.
2. For a quarantined restored order, select it in the trade's recovery controls
   and choose **Reconcile restored order**. Review and confirm. The server looks
   up the existing order; it does not submit a replacement.
3. If evidence is incomplete, keep the order unresolved. A repair response with
   status `quarantined` still needs evidence. Retry the same repair request when
   that evidence is available; `applied` confirms repair completion.
4. If an interrupted command has no attached exchange placement, use
   **Retire interrupted command** when offered. If its sale is already completely
   accounted, use **Acknowledge recorded sale settlement** instead. Neither is
   permission to infer a missing fill. Retirement leaves a close in Closing.

Missing fees are not assumed zero. The server can retrieve bounded authenticated
executions for the exact order, but IDs and filled-quantity coverage must agree.
The [repair API reference](api.md#accumulation) describes request fields and limits.

## Finish a full close

1. Wait for all prior buys and sales to settle with complete fees. A late buy fill
   still belongs to the managed holding and must be accounted before closing it.
2. If the remaining amount is sellable, review **Retry remaining sale**. This is
   a new explicit sale authorization linked to the settled preceding close.
   Another partial execution may require another explicit retry.
3. If the remainder is below precision or exchange sale minimums, allow automatic
   archival. Fresh wallet, market and order-book evidence must prove it is
   unsellable. Use **Archive remaining dust** as the explicit fallback if offered.
4. Verify **Stopped** and the exact archive in **Unsellable trades**. No sale,
   proceeds or realized loss is invented for the archived coins. They leave
   managed inventory at recorded basis and remain unmanaged wallet surplus.

Do not buy coins to reach a sale minimum or delete the remainder. Partial sales
never trigger automatic dust archival. Changed credentials, unresolved orders,
incomplete fees or stale evidence keep a full close blocked.

## Repair account or inventory evidence

1. For a rotated API key on the same settled native holding, use
   **Revalidate rotated API key**. The server checks native order anchors,
   complete accounting and fresh wallet coverage, and leaves buying paused.
2. For CSV or otherwise unverifiable settled inventory, an explicit ownership
   declaration is available when its prerequisites pass. Type the full symbol
   and reason, review, and confirm. It records your declaration, not proof of
   original-account identity; return history becomes unverified.
3. For a broken inventory link, choose **Restore recorded inventory link**.
   Quantity and cost come from server-held checkpoints or validated declarations,
   not user-supplied replacement numbers. Conflicting or missing evidence needs
   a consistent full backup.
4. Use **Inventory correction** only for a deliberate addition or partial removal
   while paused and settled. State the reason and exact amount; additions can
   declare unknown acquisition cost. Corrections cannot clear a holding or
   Closing dust, do not trade, and make historical returns unverified.

## Recover after restore or upgrade

Full restore forces paused dry-run configuration and quarantines unresolved work.
It retains immutable strategy documents and audit links. Validate the intended
account and settle recorded obligations before resuming. Config-only restore
clears the initial strategy pin; choose an exact compatible version again.

A recovery-only startup serves selected reads and explicit repairs while trading
workers and ordinary WebSockets remain stopped. Use HTTP refresh, complete the
repair, and restart the application before resuming normal operation.

Older accumulation cycles could remain in `WAIT_REBASE` after their first base
order because an uninitialized observation baseline was null. Current code
rebuilds that explicitly uninitialized state from fresh validated inputs. Deploy
the fixed code to the installation that owns the holding and restart it; do not
clear its guard or fabricate a baseline. Corrupt already-initialized state still
blocks trading. See [state boundaries](explanation-accumulation-lifecycle.md).

## Verification

Reopen the affected symbol with fresh status. Confirm the operation's recorded
outcome, inventory and pause state. A recovered order must not create a second
exchange placement. A closed registration must be Stopped before reactivation.
A resumed strategy must initialize observations before waiting for a new candle;
it must not replay missed buys.

## Troubleshooting

- **Repair still pending:** compare the exact order, account, terminal state and
  fees. An exchange response with missing evidence cannot release the commitment.
- **Revisions changed:** cancel the stale review and inspect fresh state before
  preparing another action. Keep uncertain submitted requests under their old ID.
- **Profit remains unavailable:** missing CSV fees or unvalued third-currency
  fees, declared ownership, unknown basis, incomplete native history, mixed quotes
  or unavailable marks can prevent a complete return. Fee-complete CSV imports
  support declared returns; they do not become exchange-verified historical fills.
  Do not substitute zeros. See the [CSV fee format](signals.md#csv-signal-setup).
- **New cycle shows old fills:** confirm that reactivation created a new deal and
  that the running installation has the current frontend and backend. The ledger
  retains old fills; the new deal's order timeline excludes them.

Related: [operating guide](howto-operate-accumulation.md),
[recovery reference](accumulation.md#recovery-and-inventory-repair), and
[API reference](api.md#accumulation).
