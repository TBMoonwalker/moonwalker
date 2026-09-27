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

Follow [AGENTS.md](../AGENTS.md) and [dependency policy](dependencies.md).
After code changes, run `./ci.sh` from `scripts/`; on macOS, put Homebrew
`node@24` on PATH as documented in AGENTS.md. Documentation-only changes should
verify relative links, source-backed claims, and `git diff --check`.
