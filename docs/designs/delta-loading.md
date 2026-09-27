# Dashboard history loading

## Current behavior

The overall/uPNL chart and daily, monthly, and yearly profit charts keep their
last fetched data in browser storage. On reload, they can display that data
while requesting a fresh snapshot in the background. Failed refreshes retain
the cached view. Cached data is a last-known view, not evidence that the
connection is healthy.

The profit tab panes stay mounted when switching tabs, avoiding chart
re-creation. The overall timeline query is already bounded to approximately
12 months and uses adaptive buckets; unlimited database retention does not
mean that this endpoint returns the entire database.

Open and unsellable trades use full-state WebSocket updates. Closed-trade
history is already paginated, with a separate recent-trades live feed.

## P0: browser cache

[upnl.ts](../../frontend/src/stores/upnl.ts) stores the overall timeline under
`mw_upnl_overall_timeline`.
[profit.ts](../../frontend/src/stores/profit.ts) stores per-period histories
under `mw_profit_history`.
[safeStorage.ts](../../frontend/src/helpers/safeStorage.ts) tolerates missing,
corrupt, blocked, or full browser storage.

The stores seed display data but not their in-memory freshness timestamps.
Consequently, loading after a page reload still refreshes from the server.
Successful fetches persist authoritative snapshots. The live overall chart
tail remains separate from those stored snapshots.

## Design boundaries

- Keep full snapshots for the bounded, mutable open-trade set.
- Keep pagination for the closed-trade archive.
- Preserve the live chart's time-bucket deduplication when changing history loads.
- Treat browser storage as optional; a storage failure must not break fetching.
- Optimize for multiple clients of one instance, not a distributed deployment.

## Proposed follow-up work

These items remain proposals, not supported API behavior:

1. **P1: server-side timeline cache.** Measure and reduce repeated resampling
   across clients with a short-lived cache and invalidation after a stored
   snapshot. Verify concurrent reads, invalidation, and bounded staleness.
2. **P2: incremental timeline fetch.** If costs still justify it, design an
   additive cursor response while preserving the existing no-argument endpoint.
   The earlier proposal used a monotonic row ID, with full refresh on an
   unresolved cursor after retention cleanup. Verify resampled bucket updates,
   reconnect recovery, and compatibility before choosing the final contract.
3. **P3: configurable snapshot cadence.** Consider exposing the currently
   fixed snapshot interval alongside history retention.

The current timeline endpoint does not implement these proposed cursor
semantics. See [the project backlog](../../TODOS.md) for tracking.
