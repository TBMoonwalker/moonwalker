# Dependency management

Moonwalker uses reproducible dependency locks and fails closed when an
automated install encounters an unreviewed artifact or lifecycle hook.

## Runtime baseline

- Python `3.14.x`; `.python-version` records the verified patch release.
- Node.js `24.x` LTS; `.nvmrc` records the verified patch release and npm
  enforces the supported range from `frontend/package.json`.
- npm `11.x`.
- TA-Lib's Python wheel is pinned in the backend lock. The system TA-Lib
  installation remains an operating-system prerequisite where a compatible
  wheel is unavailable.

`./run.sh start` checks this runtime before creating the service lock. If a
newer Node.js release is active, select the repository version with nvm on
macOS or Linux:

```bash
nvm install
nvm use
./run.sh start
```

On macOS, Homebrew can provide the same isolated Node.js 24 runtime:

```bash
brew install node@24
export PATH="$(brew --prefix node@24)/bin:$PATH"
./run.sh start
```

The Python locks are compiled for Python 3.14. Regenerate them with the target
runtime whenever the supported Python minor version changes.

## Updating Python packages

Edit the direct inputs, then compile both hash-locked dependency graphs:

```bash
./scripts/compile_requirements.sh
```

- `backend/requirements.in` contains production inputs.
- `backend/requirements-dev.in` adds development and audit tools.
- `backend/requirements.txt` and `backend/requirements-dev.txt` are generated;
  do not edit them manually.

The compiler version is pinned inside the script. Runtime and CI installs use
`--require-hashes` and `--only-binary=:all:`. This verifies every downloaded
artifact and prevents arbitrary source-distribution build hooks from running.

Telethon's `pyaes 1.6.1` dependency is the sole upstream package without a
published wheel. Its locked source archive and inert `distutils.setup()` file
were reviewed, then built twice with `SOURCE_DATE_EPOCH=1505942274`; both builds
produced the committed pure-Python wheel with SHA-256
`97e69519924dde9254b26b20fe37eebb4a6b811d6bda4945a53fba04a4188a83`.
The installer verifies that hash and installs the wheel with `--no-index` and
`--no-deps` before processing the main wheel-only lock. CI and startup therefore
never execute the upstream source build.

## Updating frontend packages

Keep every direct version exact in `frontend/package.json`, then regenerate the
lock without executing dependency scripts:

```bash
cd frontend
npm install --package-lock-only --ignore-scripts
npm ci --ignore-scripts
```

`frontend/.npmrc` makes exact saves, engine checks, and disabled lifecycle
scripts the defaults. The lock policy accepts only the public npm registry,
requires SHA-512 integrity metadata, and allows install-script metadata only
for the reviewed `rete@2.0.6` banner and optional `fsevents@2.3.3` native hook.
Neither hook executes in Moonwalker automation.

Moonwalker intentionally remains on TypeScript 6 while Vue's embedded
type-checking tools depend on the TypeScript programmatic API. TypeScript 7.0
does not expose that stable API yet, and the TypeScript team recommends that
Vue projects keep using TypeScript 6 during this transition. The Node type
package also stays on the Node 24 line to match Moonwalker's supported runtime.

The reviewed `@vue/test-utils` 2.5 line replaces the older dependency tree
that introduced vulnerable `js-beautify` and `glob` dependencies. Recheck the
resolved tree with npm audit when updating it.

Ruff remains on `0.15.22`. Ruff `0.16.0` enables additional rules that surface
287 findings in the current backend and test suite; adopting that version
requires a dedicated lint-cleanup change instead of a dependency-only rewrite.

## Security verification

Run the focused audit or the full CI suite:

```bash
./scripts/audit_dependencies.sh
cd scripts && ./ci.sh
```

The checks include Python and npm vulnerability databases, npm registry
signatures, exact root pins, registry origin, artifact integrity, the lifecycle
hook allowlist, tests, type checks, linting, and production builds. Review all
major updates and newly introduced packages before changing a lock file.

### CCXT/setuptools advisory resolution

CCXT `4.5.68` pins `setuptools 83.0.0`, which resolves the previously
allowlisted `PYSEC-2026-3447` finding in setuptools 82.0.1. Moonwalker's Python
audit no longer ignores that advisory or any other vulnerability.

CCXT `4.5.87` pins multidict `6.9.1`, which fixes the advisory affecting
`6.7.1`. It permits compatible aiohttp, certifi, and yarl updates, while
retaining exact pins for cffi `2.0.0`, charset-normalizer `3.4.7`, idna `3.18`,
propcache `0.5.2`, pycparser `3.0`, and uvloop `0.22.1`. Respect those pins
instead of forcing newer transitive versions. Multidict 7 remains blocked by
CCXT's dependency contract. The development lock pins the reviewed filelock 4
version used by CacheControl.

VueUse 15 uses a scheduler callback for timers. Recovery status uses
`useIntervalFn` with a five-second cadence so freshness checks do not run on
every animation frame. Vitest and its V8 coverage provider are upgraded
together to version 5; tests run with the new default mock-history clearing.

## Dependency review: 2026-10-23

This is a dated baseline for the next dependency update. Recheck registries and
advisories before adoption; the tables do not claim that uninstalled versions
have passed Moonwalker tests.

### Security fixes applied

- `certifi` changed from `2026.7.22` to `2026.10.23` in both generated Python
  locks, with an explicit production input pin. This supersedes the patched
  versions for [the compromised emSign root advisory](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2).
  The [PyPI release](https://pypi.org/project/certifi/2026.10.23/) publishes
  artifact hashes and provenance metadata.
- `follow-redirects` changed from `1.16.0` to `1.16.1`, enforced by an exact npm
  override. It fixes [array-form credential-header disclosure](https://github.com/advisories/GHSA-q3jh-wrc6-jgq8)
  and [sensitive-header matching](https://github.com/advisories/GHSA-8r9p-f939-6h3c).
  Retain the override when updating Axios unless the resolved graph guarantees
  a reviewed fixed version.

No other dependency versions changed in this security changeset. Full CI passed
on 2026-10-23: 1,855 backend tests, 266 frontend unit tests, the legacy frontend
suite, coverage gates, lint/type/build checks, both vulnerability audits and npm
registry signatures. Browser E2E is optional and was not run for this lock-only
change. The separate frontend project-type-check debt remains tracked in TODOS.md.

### Available updates and adoption decisions

Sources: `python -m pip list --outdated --format=json` for the installed Python
runtime/development environment, and `npm outdated --json` for frontend direct
packages. Frontend transitive update availability is outside this table; its
complete locked graph is still covered by npm audit and registry-signature checks.
All 33 proposed latest versions, plus the compatible `@types/node 24.19.2`
release, were queried against the
[OSV version-specific vulnerability service](https://google.github.io/osv.dev/api/).
It returned no known advisories for these targets. That result is advisory
screening, not proof of absence of compromise or of application compatibility.
The vulnerable old certifi and follow-redirects versions are unsafe to retain.

"Patch/minor safe candidate" means eligible for a separate dependency update
with resolver, provenance and CI verification. Exact upstream pins are binding;
blocked candidates must not be forced through overrides. Major versions need a
compatibility review. TypeScript 7 is currently unsuitable for this Vue toolchain,
per [Microsoft's embedded-language guidance](https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/#typescript-and-embedded-languages).

#### Python

| Package | At review | Latest | Classification / action |
| --- | --- | --- | --- |
| `ast_serialize` | 0.13.0 | 0.13.1 | Patch/minor safe candidate for a separate tested update. |
| `cachetools` | 7.2.1 | 7.2.4 | Patch/minor safe candidate for a separate tested update. |
| `ccxt` | 4.5.87 | 4.5.90 | Patch/minor candidate; review exchange behavior and its exact transitive pins together. |
| `certifi` | 2026.7.22 | 2026.10.23 | Patch/minor security fix applied; calendar versioning. |
| `cffi` | 2.0.0 | 2.1.1 | Patch/minor candidate, blocked; do not force past CCXT 4.5.87’s exact pin; review with a CCXT update. |
| `charset-normalizer` | 3.4.7 | 3.5.2 | Patch/minor candidate, blocked; do not force past CCXT 4.5.87’s exact pin; review with a CCXT update. |
| `coverage` | 7.16.2 | 7.17.0 | Patch/minor safe candidate for a separate tested update. |
| `filelock` | 4.1.1 | 4.2.4 | Patch/minor safe candidate for a separate tested update. |
| `idna` | 3.18 | 3.20 | Patch/minor candidate, blocked; do not force past CCXT 4.5.87’s exact pin; review with a CCXT update. |
| `litestar` | 2.24.0 | 2.25.0 | Patch/minor safe candidate; verify startup, dependency injection and WebSockets. |
| `multidict` | 6.9.1 | 7.1.0 | Major; do not force past CCXT 4.5.87’s exact pin; review with a CCXT update. |
| `pandas` | 3.0.6 | 3.1.0 | Patch/minor safe candidate; verify indicator calculations and replay results. |
| `pip` | 26.2.1 | 26.2.2 | Patch/minor safe candidate for a separate tested update. |
| `platformdirs` | 4.13.0 | 4.13.5 | Patch/minor safe candidate for a separate tested update. |
| `pluggy` | 1.6.0 | 1.7.0 | Patch/minor safe candidate for a separate tested update. |
| `polyfactory` | 3.3.0 | 3.5.0 | Patch/minor safe candidate for a separate tested update. |
| `propcache` | 0.5.2 | 0.5.4 | Patch/minor candidate, blocked; do not force past CCXT 4.5.87’s exact pin; review with a CCXT update. |
| `pycparser` | 3.0 | 3.12 | Patch/minor candidate, blocked; do not force past CCXT 4.5.87’s exact pin; review with a CCXT update. |
| `python-dateutil` | 2.9.0.post0 | 3.0.0 | Major; review datetime parsing and timezone behavior before adoption. |
| `ruff` | 0.15.22 | 0.17.2 | Pre-1.0 breaking/tooling review; retain 0.15.22 until the dedicated lint cleanup. |
| `setuptools` | 84.0.0 | 84.2.1 | Patch/minor candidate; coordinate with the reviewed CCXT/build-tool inputs. |
| `tortoise-orm` | 1.1.8 | 1.1.9 | Patch/minor safe candidate; verify ORM context and background tasks. |
| `uvloop` | 0.22.1 | 0.23.0 | Patch/minor candidate, blocked; do not force past CCXT 4.5.87’s exact pin; review with a CCXT update. |
| `websockets` | 17.2 | 17.3 | Patch/minor safe candidate for a separate tested update. |

#### Frontend

| Package | At review | Latest | Classification / action |
| --- | --- | --- | --- |
| `@playwright/test` | 1.64.0 | 1.64.1 | Patch/minor safe candidate for a separate tested update. |
| `@types/node` | 24.13.3 | 26.6.5 (24.x: 24.19.2) | 26.x is a major; retain the Node 24 line. 24.19.2 is a patch/minor safe candidate. |
| `@vitest/coverage-v8` | 5.0.4 | 5.0.5 | Patch/minor safe candidate; upgrade together with vitest. |
| `jsdom` | 30.1.2 | 30.1.3 | Patch/minor safe candidate for a separate tested update. |
| `knip` | 6.41.0 | 6.42.1 | Patch/minor safe candidate for a separate tested update. |
| `pinia` | 4.0.3 | 4.1.0 | Patch/minor safe candidate for a separate tested update. |
| `typescript` | 6.0.3 | 7.0.2 | Major; do not adopt while Vue tooling requires the TypeScript 6 API. |
| `vite` | 8.3.4 | 8.3.5 | Patch/minor safe candidate for a separate tested update. |
| `vitest` | 5.0.4 | 5.0.5 | Patch/minor safe candidate; upgrade together with @vitest/coverage-v8. |

## Rollback

Revert the dependency-only changeset and rerun `./run.sh start`. Startup builds
and validates the inactive environment slot before changing the `.venv`
symlink. The predecessor remains at `.venv.previous`, and a failed dependency
install or import check never changes the active environment.
