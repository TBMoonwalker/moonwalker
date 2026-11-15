# Deny a symbol from future entries

In an open trade's **more** menu, choose **Deny from new entries** and confirm.
The symbol is added to `pair_denylist`. Its existing deal continues normal
DCA, safety-order, take-profit, and exit handling. Denying does not sell or stop it.

The row shows a denylisted badge. Repeating the action does not add duplicate
entries. To allow the symbol again, remove its base token from the denylist in
configuration; there is no symmetric re-enable row action.

## API and concurrency

The frontend sends the symbol to `POST /config/denylist/deny`. The backend
normalizes it to a base token, reads the current list, de-duplicates, and writes
under the shared configuration write lock. This prevents concurrent append
requests from different dashboard clients from overwriting each other.

Full configuration saves remain whole-list replacements. Generic configuration
writes require the revision from the loaded snapshot. A denylist append advances
that revision, so a stale form save is rejected with HTTP 409 instead of
overwriting the new entry; the editor shows a stale-configuration banner and the
operator reloads the form and re-applies their edits. Intentional removals are
unaffected: a form loaded after the append can still remove any token from the
denylist.

The authoritative implementation is
[Config](../../backend/service/config.py), with the request handler in
[controller/config.py](../../backend/controller/config.py). The
[API reference](../api.md) documents the request and response.

## Design decisions

- Keep the action in the overflow menu rather than beside frequent actions.
- Block future signal entries without changing existing positions.
- Keep undo in configuration.
- Perform append normalization and de-duplication on the server.
- Reflect persisted denylist state in the row badge.
- Leave the configured symbol list intact; the denylist remains the entry gate.

A symmetric re-enable action and badge design review remain in
[the project backlog](../../TODOS.md).
