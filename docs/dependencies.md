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

## Rollback

Revert the dependency-only changeset and rerun `./run.sh start`. Startup builds
and validates the inactive environment slot before changing the `.venv`
symlink. The predecessor remains at `.venv.previous`, and a failed dependency
install or import check never changes the active environment.
