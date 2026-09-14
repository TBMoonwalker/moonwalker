# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

**Primary: operators.** Owners of a single Moonwalker instance who set it up, run it, and recover it when something is wrong. They typically run one bot on one machine (frequently Linux) and open the dashboard from the same or several clients at once — desktop, phone, and browser tabs.

- Situation: configuring exchange access, choosing a signal source and DCA behavior, monitoring live campaigns, and responding to alarms safely.
- Job: stand up a bot safely (preferably in dry run first), keep it running and correct, and recover calmly from an incident without losing or corrupting state.

**No secondary audience is in scope for this record.** Moonwalker is an operator tool, not a marketing site or a public community product. Developers and contributors exist (MIT license, public docs), but the product record does not design for them as users.

## Product Purpose

Moonwalker is a self-hosted cryptocurrency trading bot that executes trades from signal plugins and managed dynamic DCA campaigns, with a web dashboard that configures exchange access, signal sources, DCA behavior, monitoring, and operational safety.

It exists so an operator can run an automated trading strategy on their own infrastructure and understand, at a glance, whether the instance is ready, what it is doing, and what to do next.

Success means: the operator can reach a safe, known-good configuration (ideally validated in dry run), see readiness and evidence instead of noise, and act on a single clear next step. Failure means the operator is dropped into a wall of fields and uncertain whether the bot is safe to run.

## Positioning

**Calm, intent-first operator console.**

The meaningfully different claim a neighboring product could not truthfully copy: Moonwalker asks the operator for intent *before* exposing breadth. First run does not begin with a mode strip or a dense settings grid; it begins with one intent question (restore an existing installation, or start a new setup) and then a setup-style choice (guided or full control). Each editable setting has exactly one canonical home, readiness gates stand between dry run and live trading, and the dashboard optimizes for calm control and recoverable outcomes rather than marketing or feature density.

## Operating Context

- **Single-node, single-instance.** One running instance owns its database, configuration, watcher/runtime state, and trading engine. The backend is intentionally single-process because the trading engine keeps shared in-memory runtime state. Separate installations are intentionally isolated; there is no clustering, leader election, or cross-instance coordination.
- **Multiple concurrent dashboard clients.** It is normal for several clients (desktop, phone, tabs) to connect to the same instance at once. The config layer supports this via DB persistence, per-client freshness polling, and browser-local invalidation with stale-draft warnings.
- **Entry path.** The supported dashboard configuration entry path is `/control-center`; the statistics dashboard lives at `/stats`. Default port is `8130` (a `8160` measurement also appears in the design baseline).
- **Config lifecycle.** Runtime configuration is DB-persisted (`AppConfig` table), served via `/config/all` with credential values replaced by redaction markers, hot-reloaded via Redis pub/sub, and edited through the UI or `PUT /config/single/{key}` / `POST /config/multiple`. Switching `dry_run` from true to false must go through `POST /config/live/activate`, which enforces readiness checks.
- **Run/operations.** `./run.sh start` builds the Vue frontend, stages assets into the backend, creates a Python venv, installs backend dependencies, and starts the Litestar app in the background (`./run.sh stop` halts it). Full verification runs via `cd scripts && ./ci.sh`.
- **Environment.** Linux is the most typical deployment target, but any environment supporting Python, Node.js, and TA-Lib works.

## Capabilities and Constraints

- Trade modes (canonical operator-facing control is `trade_mode`): `dynamic_dca` (standard DCA with dynamic safety orders) and `sidestep` (spot-only campaigns that can sell a bearish leg, hold the campaign in a waiting state, and re-enter it later).
- Signal plugins: `sym_signals`, `asap`, `csv_signal`, `websocket_signal`.
- Strategies included: EMA cross, Bollinger Bands cross, Ichimoku, and others; indicators are computed via TA-Lib.
- Autopilot / Autopilot Memory cockpit surfaces favored and cooling symbols, suggested base orders, and plain-language trust signals in the Control Center.
- Monitoring notifications via Telegram (Telethon) for buy/sell events; `trading_paused` blocks new exposure while still managing exits for existing positions.
- Backup/restore supports config-only and full backup, with canonicalization of legacy rows and backup payloads on load/restore.
- **Constraints:** TA-Lib must be installed per OS; the backend is single-process; credential values are redacted in served config; going live requires passing readiness gates; the app carries an educational-only, "use at your own risk" posture and offers no financial guarantee.

## Brand Commitments

The following are binding for all future work:

- **Name:** Moonwalker.
- **Logo:** `docs/assets/logo-moonwalker.png`.
- **Voice/disclaimer:** "Mean to be used for educational purposes only. Use with real funds at your own risk." This educational-only / own-risk framing is a permanent constraint, not a launch-time caveat.
- **Licensing:** MIT (copyright holder `TBMoonwalker`, 2024).

## Evidence on Hand

- Repository sources of truth: `DESIGN.md` (design system + verified live baseline measured 2026-06-05), `README.md`, `CHANGELOG.md`, and the `docs/` reference set (`configuration.md`, `api.md`, `monitoring.md`, `dynamic-so.md`, `signals.md`, `operations.md`, `dependencies.md`, `strategies.md`).
- Current tracked release: `VERSION` = 4.6.3.0.
- Logo asset: `docs/assets/logo-moonwalker.png`.
- **Absences to preserve:** there are **no** external testimonials, customer logos, published benchmarks, or case studies. Future work must not fabricate these.

## Product Principles

1. **Intent before breadth.** Ask for the operator's intent first; expose breadth only as far as that intent requires.
2. **One home per setting.** Every editable configuration field has exactly one canonical visible home; deeper tuning extends an area, it does not restate it.
3. **Calm under failure.** The dashboard must let an operator reach a safe state and recover one calmly; readiness gates and clear next actions outrank feature density.
4. **Operator-owned autonomy.** Single-instance isolation, DB-held state, and no telemetry: the operator owns the instance and its data.
5. **Safety before live.** A path to live trading is gated behind dry-run readiness; the bot does not silently go live.

## Accessibility & Inclusion

The first-run entry choice must be fully keyboard navigable and understandable without color. Guided task expansion must preserve a clear focus order; revealing expert controls inline must move focus predictably and announce the change. Restore outcomes and readiness-review states must use ARIA live regions. Primary actions must meet minimum touch-target sizes (44px, per the design baseline's pagination finding).
