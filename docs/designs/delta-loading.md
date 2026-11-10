# Dashboard history loading

## Current behavior

The overall/uPNL chart and the daily, monthly, and yearly profit charts keep
their last fetched data in browser storage. Period charts can display cached
data while refreshing. The overall timeline is withheld until a successful
server refresh verifies it; a failed refresh makes that timeline unavailable
even if cached data remains stored. Cached data is a last-known view, not
evidence that the connection is healthy.

The profit tab panes stay mounted when switching tabs, avoiding chart
re-creation. The overall timeline query is bounded to approximately 12 months
and uses adaptive buckets; unlimited database retention does not mean that
this endpoint returns the entire database. The server caches the resampled
timeline for one snapshot interval (see P1), so multiple dashboard clients
share one rebuild per window.

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

Revisiting a cached view (for example a menu round trip back to Overview)
goes through the same TTL: while the 5-minute window is fresh, the chart
repaints from the stored timeline; a longer absence past the TTL, or a
15-minute data bucket boundary crossed since the timeline was last
server-verified, triggers a fresh fetch. The router guard follows the
same idea for the shared config snapshot: it fetches the full config
once, then revalidates each navigation with the lightweight freshness
check.

## P1: server-side timeline cache (implemented)

`GET /statistic/profit-overall/timeline` resamples the full 12-month window
of stored snapshots (adaptive 1W/1D/4h/15min buckets) on every fetch. With
the 60-second snapshot cadence, steady-state retention is ~525,000 rows per
year, and the measurement in [Evaluation](#evaluation) shows each uncached
fetch costs ~4.4 s (p50) at that size, growing with retention and with the
number of concurrent clients.

The response is therefore cached in the `Statistic` service
(`backend/service/statistic.py`, `TIMELINE_CACHE_TTL_SECONDS = 60`):

- **Single-flight rebuild.** A lock plus a double-checked expiry makes any
  number of concurrent clients share one rebuild per window. The rebuild is
  an indexed bucket walk (see [P1.5](#p15-cheap-rebuild--pre-bucketing-in-sql-implemented))
  that runs natively on the event loop, so a cold rebuild no longer holds
  the GIL in a worker thread and no longer stalls unrelated requests.
- **Invalidation on every stored snapshot.** Snapshot writes happen in
  `Statistic._get_profit_base`, which is reached from the controller graph,
  the DCA engine, and the signal plugins — each with its own `Statistic`
  instance. Every successful `UpnlHistory` write advances a process-wide
  data generation; a cache entry is only valid for its own generation, so a
  write from any instance forces the next fetch to re-resample and the
  freshly stored point is visible immediately (bucket update).
- **Invalidation on retention cleanup.** The housekeeper fires
  `on_upnl_history_changed` after pruning expired rows; the application
  wires that hook to `statistic.invalidate_timeline_cache` on the controller
  instance, so pruned points do not outlive the prune.
- **Bounded staleness.** With no new write, the cache is at most one
  snapshot interval old: the response window slides with the server clock,
  so a cached response can lag the current resample by up to the 60-second
  TTL — at most one 15-minute bucket of boundary drift, always from the same
  underlying snapshot values. The live WebSocket tail carries the current
  state in the meantime. Query errors are not cached, so a healthy
  follow-up fetch re-queries.
- **Immutable value, unchanged contract.** The cached point list is treated
  as immutable and each fetch returns a copy of the list. The endpoint's
  path, arguments, and response shape are unchanged, and the 409
  unverified-valuation guard stays per-request in the controller, so a new
  unverified row 409s immediately regardless of the cache. Disconnect
  recovery is unchanged: the endpoint is stateless, and the client store
  already treats a failed refresh as unverified and retries.

## P1.5: cheap rebuild — pre-bucketing in SQL (implemented)

The P1 cache removed repeated resampling, but a single dashboard client
that reloads (or switches from standby to active) always hits the expired
TTL and triggers one full rebuild. On the live instance (~370k snapshots,
~8.5 months of history) that cold rebuild took ~6.4 s, and — because the
pandas resample ran in a worker thread holding the GIL — the event loop
starved for the same duration, stalling every concurrent boot request
(`/config/all` and `/accumulation/strategies` measured ~6.2 s on the
reloaded page). The fix makes the rebuild itself cheap instead of
refreshing it in the background.

The resample is deterministic: each adaptive bucket emits the last row in
the bucket, nothing else. So the rebuild no longer loads the whole 12-month
window and resamples it in pandas. It computes the bucket grid in Python
and resolves every bucket with one indexed `LIMIT 1` seek:

```sql
SELECT profit_overall, funds_locked FROM upnl_history
WHERE performance_verified = 1
  AND timestamp >= ? AND timestamp < ?
ORDER BY timestamp DESC, id DESC LIMIT 1
```

`backend/service/statistic.py` (`_fetch_profit_overall_timeline`):

- **Grid.** day: 15 min, week: 4 h, month: 1 d, year: Monday-anchored
  weeks — the same bins as before. The year slice labels each bucket with
  the Sunday midnight inside it (pandas `resample("1W")` semantics,
  verified empirically: Monday-start bin, Sunday label).
- **Winner.** `ORDER BY timestamp DESC, id DESC LIMIT 1` returns the last
  row of the bucket, exactly the value `resample(...).last()` after
  exact-timestamp dedup produced.
- **Merge.** A bucket label that appears in two slices (for example a
  Sunday-midnight week label and a day label on the same instant) keeps the
  newer slice's value, mirroring the original
  `concat`/`sort_index`/`dedup(keep="last")` order.
- **Boundaries.** Query bounds are formatted exactly like the stored
  strings — space-separated, ``+00:00`` suffix, fractional seconds
  omitted only when the microsecond is zero, the form Tortoise persists
  — which makes lexicographic string comparison chronologically exact
  against every stored row.
- **Cost.** A MIN/MAX preflight skips buckets outside the data range; a
  full-year rebuild issues ~220 tiny index seeks and reads ~220 rows
  instead of ~370k, natively on the event loop (no `asyncio.to_thread`, no
  GIL starvation of concurrent requests).

The pandas reference pipeline was differential-tested, not merely
migrated: `backend/tests/test_statistic_timeline_prewin.py` seeds
adversarial fixtures (exact bucket and slice boundaries, sub-second and
identical-timestamp duplicates, week-straddle label collisions, unverified
rows, sparse history, empty history) plus a full year of 60-second
snapshots at the production cadence — every bucket of every resolution
filled — and asserts the bucket walk's output is point-for-point
identical to the original full-history resample for both aligned and
sub-second-offset rebuild times. The endpoint's path, arguments, and
response shape are unchanged, the 409 unverified-valuation guard stays
per-request, and the cache/invalidation behavior of P1 is unchanged.

## Evaluation

`scripts/benchmark_timeline.py` seeds throwaway databases at the real
snapshot density (60 s cadence) — 16 days (~23k rows, the shape of the
current live instance), 1 year (~525k rows, steady state), and 2 years
(~1.05M rows, retention beyond the 12-month window) — plus a `sqlite3`
backup copy of the live database, and runs: six sequential fetches, 4/8/16
simultaneous cold fetches, and a burst of 16 clients staggered over ~40 s
with two fetches each. The seeds use the production storage format
(space-separated, `+00:00`), because the P1.5 bucket walk compares bounds
lexicographically against the stored strings. Full reports:
`~/.gstack/projects/TBMoonwalker-moonwalker/benchmark-reports/`
(`*timeline-server*.json`, before = commit 9a005fa, after = the cache
changes, `*T141830Z*` and later = the pre-bucketed rebuild; the
`*T131614Z*`/`*T132605Z*` reports were seeded with `T`-separated
timestamp strings that never occur in production storage and are
superseded).

Uncached (before), steady-state 1-year database (525,600 rows):

| Scenario | Fetches | Resamples | p50 | p95 |
|---|---:|---:|---:|---:|
| Sequential (6) | 6 | 6 | 4.4 s | 5.4 s |
| Concurrent 4 | 4 | 4 | 10.4 s | 17.0 s |
| Concurrent 16 | 16 | 16 | 32.1 s | 64.8 s |
| Burst (16 clients, 32 fetches) | 32 | 32 | 35.5 s | 65.5 s |

The payload is not the cost: the steady-state response is 206 points /
~17.7 KB of JSON. The cost is per-fetch server CPU and SQLite I/O,
multiplied by every concurrent client.

With the cache (after), the same scenarios on the same databases:

| Scenario | Fetches | Resamples | p50 | p95 |
|---|---:|---:|---:|---:|
| Sequential (6) | 6 | 1 | <1 ms (warm) | 2.9 s (cold first fetch) |
| Concurrent 4 | 4 | 1 | 2.9 s | 2.9 s |
| Concurrent 16 | 16 | 1 | 5.9 s | 5.9 s |
| Burst (16 clients, 32 fetches) | 32 | 1 | <1 ms (warm) | 2.8 s (first cold client) |

Every scenario now resamples exactly once per 60-second window, whatever
the client count (16→1 and 32→1 resamples), warm fetches are
sub-millisecond cache hits, and the worst concurrent wait drops from
64.8 s to 5.9 s — the shared single-flight rebuild itself. The steady
state with an active bot is one rebuild per snapshot interval, served to
all clients that fetch in that window.

With the pre-bucketed rebuild (P1.5), the same scenarios:

| Scenario | Database | Fetches | Rebuilds | p50 | p95 |
|---|---|---:|---:|---:|---:|
| Sequential (6) | 1y (525,600 rows) | 6 | 1 | <1 ms (warm) | 36 ms (cold first fetch) |
| Concurrent 4 | 1y | 4 | 1 | 36 ms | 36 ms |
| Concurrent 16 | 1y | 16 | 1 | 38 ms | 38 ms |
| Burst (16 clients, 32 fetches) | 2y (1,051,200 rows) | 32 | 1 | <1 ms (warm) | 62 ms (first cold client) |
| Sequential (6) | live copy (12,507 rows) | 6 | 1 | <1 ms (warm) | 7.8 ms (cold first fetch) |
| Concurrent 16 | live copy | 16 | 1 | 11.2 ms | 11.4 ms |

The cold rebuild — the path a single client's reload or standby→active
switch always hits — drops from 2.9–5.9 s to ≤38 ms at steady-state size
and ≤70 ms on the 2-year database (twice the live row count), roughly
100×. Because the rebuild now runs natively on the event loop, the
concurrent boot requests that previously queued behind the worker-thread
resample are no longer stalled by it.

## P2: incremental timeline fetch (decision: not justified)

The earlier proposal was an additive delta cursor (monotonic row ID) with a
full refresh on an unresolved cursor after retention cleanup. It is not
justified by the measurements:

- The wire cost is already bounded: ~17.7 KB per fetch in steady state, and
  the client only fetches on the 5-minute TTL or a bucket-boundary crossing.
  A delta cursor would save a small fraction of that ~17 KB per fetch.
- The measured cost is server-side CPU/SQLite (4.4 s per resample at
  steady state, ~32–65 s of queueing under concurrent clients), which the
  P1 cache removes: one rebuild per window for all clients, invalidated by
  every stored snapshot.
- The cursor would add server-side cursor state, a second response shape,
  and a retention-cleanup recovery path (stale cursor → full refresh) for a
  bandwidth saving the data does not support.

The no-argument endpoint remains the sole contract. Revisit only if a
future change makes the payload grow (more series, finer buckets) or the
client fetch cadence drop far below the snapshot interval.

## P3: configurable snapshot cadence (proposal)

Consider exposing the currently fixed 60-second snapshot interval alongside
history retention in configuration. It remains a proposal; nothing in the
P1 cache depends on a specific cadence (the TTL matches it today by
construction, and the snapshot-write invalidation is cadence-independent).
