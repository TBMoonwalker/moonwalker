# Developer documentation and ownership

Moonwalker runs as one application instance with multiple dashboard clients.
Durable architecture explanations belong in this repository so contributors can
understand and maintain the system without access to an individual machine.

## Runtime and data boundaries

| Concern | Owner and responsibility |
|---|---|
| Application lifecycle | [app.py](../backend/app.py) and [runtime_services.py](../backend/service/runtime_services.py) own startup, supervised tasks, and shutdown. |
| Configuration | [config.py](../backend/service/config.py) persists settings; [config_contract.py](../backend/service/config_contract.py) defines the shared high-risk configuration contract; [config_migrations.py](../backend/service/config_migrations.py) handles versioned legacy normalization. |
| Signal entry | [signal_runtime.py](../backend/service/signal_runtime.py) coordinates admission; the order service remains the central execution boundary. |
| Trading data | [trading_contracts.py](../backend/service/trading_contracts.py), [exchange_types.py](../backend/service/exchange_types.py), and [persistence_records.py](../backend/service/persistence_records.py) define intent, execution, and persistence contracts. |
| AI work | [ai_work_queue.py](../backend/service/ai_work_queue.py) bounds background work; provider transport, analytics, and calibration have separate modules behind the AI Trust facade. |
| Recovery sizing | [dca_recovery_sizing.py](../backend/service/dca_recovery_sizing.py) contains pure calculations; [dca.py](../backend/service/dca.py) integrates strategy signals, balances, diagnostics, and order execution. |
| Browser access policy | [origin_policy.py](../backend/service/origin_policy.py) owns origin checks. Origin checks are not an authentication system. |

For the operator-facing behavior, see [safety-order sizing](dynamic-so.md),
[AI Trust calibration](ai-trust.md), [configuration](configuration.md), and
[operations](operations.md).

## Maintained design notes

- [Dashboard history loading](designs/delta-loading.md): browser caching,
  full-state versus paginated streams, and proposed server optimizations.
- [Denying future entries](designs/denylist-symbol-from-open-trade.md):
  entry-only semantics, server-side append, and full-form replacement limits.
- [Product record](../PRODUCT.md) and [design system](../DESIGN.md):
  durable product and visual constraints.
- [Project backlog](../TODOS.md): unfinished work and completed-item history.

Dynamic DCA is the only supported trade mode. Legacy configuration and backup
mode values are normalized to it. Historical Sidestep plans do not describe a
supported runtime capability.

The old Control Center audit's proposed theme unification has since been
implemented: [themeStore.ts](../frontend/src/theme/themeStore.ts) owns the
resolved scheme used by CSS and Naive UI. Historical audit scores are not
current verification results.

Browser preference access is guarded by
[safeStorage.ts](../frontend/src/helpers/safeStorage.ts). Use its text helpers
for literal preference values and its JSON helpers for structured caches.
Storage is resolved inside the exception boundary, including when callers
provide an injected window. Missing or blocked storage returns no saved value
and leaves the current in-memory preference usable.

Historical profit and uPNL chart frame styles share the `.performance-chart`
rules in [main.css](../frontend/src/assets/main.css). Each component retains its
own placeholder background; `.chart-wrap` remains available to dashboard layout
overrides.

Frontend builds use Vite's automatic chunk splitting to preserve the router's
lazy view boundaries. Package-wide manual groups can pull chart and form code
into startup through shared dependencies. The production-build regression test
checks that startup contains no chart modules and stays below 250 KB gzip.

## Where documentation belongs

- Keep user instructions, configuration reference, API contracts, operations,
  and maintained architecture/design explanations in the repository.
- Keep reusable project requirements and unresolved work in maintained design
  notes or `TODOS.md`, with proposed behavior clearly labeled.
- Keep agent session transcripts, review scorecards, local database observations,
  screenshots, temporary implementation plans, and handoff notes in local
  project storage under `~/.gstack/projects/<project-slug>/`.
- Before removing an agent artifact, preserve its original and extract any
  still-relevant decisions or unfinished work into repository documentation.
- Do not link user documentation to machine-specific archive paths or require
  local agent state to understand the project.

For this repository, the gstack project slug is `TBMoonwalker-moonwalker`.
The 2026-09-26 cleanup preserved original plans and audit reports in the local
`docs-archive/2026-09-26/` directory under that project home, with a SHA-256
manifest. The archive is historical context; it is not part of the application
or required for builds.

## Verification

### Python dead code

Vulture is pinned in `backend/requirements-dev.in` and its generated hash lock.
Install development tools into the dedicated development environment:

```bash
./scripts/install_python_dependencies.sh \
  "$PWD/.venvs/dev/bin/python" "$PWD/backend/requirements-dev.txt"
```

From the repository root, run either scan:

```bash
# Conservative scan: settings come from pyproject.toml.
./.venvs/dev/bin/python -m vulture

# Broader review, ordered by the size of each candidate.
./.venvs/dev/bin/python -m vulture --min-confidence 60 --sort-by-size
```

Both scans include `backend/` (including its tests) and `scripts/`. Vulture
parses source without importing or running the application. It exits with code
3 when it finds candidates; configuration or parsing errors are separate
failures. The default confidence threshold is 100; the broader scan also
reports unused function, class, attribute, and variable candidates.

Confidence values are tool heuristics, not proof that an API can be removed.
Unused callback parameters can be required by a protocol, and pytest fixture
arguments can perform setup without being referenced in a test body. Dynamic
controller discovery, signal plugin methods, indicator lookup, and Tortoise ORM
fields can also produce false positives. Review call sites, framework contracts,
and tests before changing code. Keep any future allowlist limited to confirmed
framework uses and document the owning contract; do not generate and accept an
allowlist from every reported candidate.

Both scans remain on-demand checks rather than CI gates while existing
candidates are reviewed. `./run.sh start` switches `.venv` between release slots
and installs runtime dependencies only; use `.venvs/dev` for a stable development
tool environment, or reinstall the development lock into the current `.venv`.

### Frontend dead code

Run `npm --prefix frontend run knip` from the repository root to report unused
files, exports, types, and dependencies. Knip is pinned in the frontend lockfile;
`npm ci --ignore-scripts` installs it alongside the other development tools.
[knip.ts](../frontend/knip.ts) includes the legacy Node tests and source
files. Knip's Vue, Vite, Vitest, and Playwright plugins discover the application
and configured test entrypoints.

The command returns a nonzero exit code when it finds issues. The Knip-only
compiler turns literal `loadFrontendModule()` calls in legacy tests into ordinary
module references, including namespace property access. It parses test source
without executing the loader or changing how tests run. Dynamic path expressions
still require manual review. No blanket exclusions suppress candidates. Knip
remains an on-demand check rather than a CI gate.

Follow [AGENTS.md](../AGENTS.md) and [dependency policy](dependencies.md).
After code changes, run `./ci.sh` from `scripts/`; on macOS, put Homebrew
`node@24` on PATH as documented in AGENTS.md. Documentation-only changes should
verify relative links, source-backed claims, and `git diff --check`.
