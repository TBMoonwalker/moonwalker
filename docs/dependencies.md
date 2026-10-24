# Dependency management

Moonwalker uses reproducible dependency locks and fails closed when an
automated install encounters an unreviewed artifact or lifecycle hook.

For the task-by-task procedure, use
[How to update dependencies after supply-chain review](howto-update-dependencies.md).
Before any direct or transitive update, research web compromise reports and
version-specific advisories. An unresolved incident blocks installation; clean
audits, semver labels and registry signatures alone do not establish trust.
Record primary-source links and artifact/provenance evidence when applicable.
This manual pre-install review complements the automated gates below.

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

Ruff is pinned to `0.17.2`. Its lint configuration explicitly selects the
pre-0.16 rule families (`E4`, `E7`, `E9`, `F`), preserving the existing checks
through the tool upgrade. This follows the [upstream compatibility migration](https://astral.sh/blog/ruff-v0.16.0).
Adopting Ruff's expanded default rules is a separate lint-policy change; do not
silently disable existing rules or bundle broad code cleanup into lock updates.

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

CCXT `4.5.90` pins multidict `6.9.1`, which fixes the advisory affecting
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
| `ast_serialize` | 0.13.0 | 0.13.1 | Applied 0.13.1 (patch/minor); exact pin and generated lock updated. |
| `cachetools` | 7.2.1 | 7.2.4 | Applied 7.2.4 (patch/minor); exact pin and generated lock updated. |
| `ccxt` | 4.5.87 | 4.5.90 | Applied 4.5.90 (patch/minor); exact pin and generated lock updated. |
| `certifi` | 2026.7.22 | 2026.10.23 | Patch/minor security fix applied; calendar versioning. |
| `cffi` | 2.0.0 | 2.1.1 | Patch/minor candidate, blocked; do not force past CCXT 4.5.90’s exact pin; review with a CCXT update. |
| `charset-normalizer` | 3.4.7 | 3.5.2 | Patch/minor candidate, blocked; do not force past CCXT 4.5.90’s exact pin; review with a CCXT update. |
| `coverage` | 7.16.2 | 7.17.0 | Applied 7.17.0 (patch/minor); exact pin and generated lock updated. |
| `filelock` | 4.1.1 | 4.2.4 | Applied 4.2.4 (patch/minor); exact pin and generated lock updated. |
| `idna` | 3.18 | 3.20 | Patch/minor candidate, blocked; do not force past CCXT 4.5.90’s exact pin; review with a CCXT update. |
| `litestar` | 2.24.0 | 2.25.0 | Applied 2.25.0 (patch/minor); exact pin and generated lock updated. |
| `multidict` | 6.9.1 | 7.1.0 | Major; do not force past CCXT 4.5.90’s exact pin; review with a CCXT update. |
| `pandas` | 3.0.6 | 3.1.0 | Applied 3.1.0 (patch/minor); exact pin and generated lock updated. |
| `pip` | 26.2.1 | 26.2.2 | Applied 26.2.2 (patch/minor); exact pin and generated lock updated. |
| `platformdirs` | 4.13.0 | 4.13.5 | Applied 4.13.5 (patch/minor); exact pin and generated lock updated. |
| `pluggy` | 1.6.0 | 1.7.0 | Applied 1.7.0 (patch/minor); exact pin and generated lock updated. |
| `polyfactory` | 3.3.0 | 3.5.0 | Applied 3.5.0 (patch/minor); exact pin and generated lock updated. |
| `propcache` | 0.5.2 | 0.5.4 | Patch/minor candidate, blocked; do not force past CCXT 4.5.90’s exact pin; review with a CCXT update. |
| `pycparser` | 3.0 | 3.12 | Patch/minor candidate, blocked; do not force past CCXT 4.5.90’s exact pin; review with a CCXT update. |
| `python-dateutil` | 2.9.0.post0 | 3.0.0 | Applied 3.0.0 with hashed tzdata 2026.5 and timezone regressions. |
| `ruff` | 0.15.22 | 0.17.2 | Applied 0.17.2; preserve existing lint rule families explicitly. |
| `setuptools` | 84.0.0 | 84.2.1 | Applied 84.2.1 (patch/minor); exact pin and generated lock updated. |
| `tortoise-orm` | 1.1.8 | 1.1.9 | Applied 1.1.9 (patch/minor); exact pin and generated lock updated. |
| `uvloop` | 0.22.1 | 0.23.0 | Patch/minor candidate, blocked; do not force past CCXT 4.5.90’s exact pin; review with a CCXT update. |
| `websockets` | 17.2 | 17.3 | Applied 17.3 (patch/minor); exact pin and generated lock updated. |

#### Frontend

| Package | At review | Latest | Classification / action |
| --- | --- | --- | --- |
| `@playwright/test` | 1.64.0 | 1.64.1 | Applied 1.64.1 (patch/minor); exact pin and generated lock updated. |
| `@types/node` | 24.13.3 | 26.6.5 (24.x: 24.19.2) | Applied 24.19.2 (patch/minor); exact pin and generated lock updated. |
| `@vitest/coverage-v8` | 5.0.4 | 5.0.5 | Applied 5.0.5 (patch/minor); exact pin and generated lock updated. |
| `jsdom` | 30.1.2 | 30.1.3 | Applied with reviewed selector-engine major 10.0.5. |
| `knip` | 6.41.0 | 6.42.1 | Applied with reviewed shell-parser major unbash 6.0.1. |
| `pinia` | 4.0.3 | 4.1.0 | Applied 4.1.0 (patch/minor); exact pin and generated lock updated. |
| `typescript` | 6.0.3 | 7.0.2 | Major; do not adopt while Vue tooling requires the TypeScript 6 API. |
| `vite` | 8.3.4 | 8.3.5 | Applied 8.3.5 (patch/minor); exact pin and generated lock updated. |
| `vitest` | 5.0.4 | 5.0.5 | Applied 5.0.5 (patch/minor); exact pin and generated lock updated. |

### Patch/minor follow-up

The follow-up applies 14 Python package updates and six frontend direct-package
updates listed above. It keeps all existing major versions, including Node types
on 24.x, and upgrades Vitest with its matching coverage provider. Both Python
locks were regenerated with selected upgrade targets; npm resolution introduced
no major version changes. Security pins for certifi and follow-redirects remain.

CCXT 4.5.90 retains the exact pins blocking cffi, charset-normalizer, idna,
multidict, propcache, pycparser and uvloop updates. The minor-only changeset
held Ruff and dateutil for the major/breaking review below. TypeScript 7 and
Node 26 types remain outside the supported toolchain.

The [jsdom 30.1.3 metadata](https://registry.npmjs.org/jsdom/30.1.3) requires
`@asamuzakjp/dom-selector ^10.0.3` rather than the existing 9.x line. The
[Knip 6.42.1 metadata](https://registry.npmjs.org/knip/6.42.1) requires `unbash ^6.0.0`
rather than 5.x; Knip 6.42.0 has the same requirement. These candidates had no
known OSV advisory, and were held during the minor-only update pending the
major review below. Do not override their requirements to force older engines.

Release review included [CCXT 4.5.90](https://github.com/ccxt/ccxt/releases/tag/v4.5.90),
[Litestar 2.25.0](https://docs.litestar.dev/2/release-notes/changelog.html#2.25.0),
[pandas 3.1.0](https://pandas.pydata.org/docs/whatsnew/v3.1.0.html),
[Tortoise 1.1.9](https://github.com/tortoise/tortoise-orm/releases/tag/1.1.9) and
[websockets 17.3](https://websockets.readthedocs.io/en/stable/project/changelog.html#id1).
Pandas changes datetime resolution inference for numeric input; candle
serialization uses timestamp conversion rather than assuming a fixed integer
resolution. The backend timestamp/resampling, indicator, replay and statistics
tests pass with the updated versions. CI also reports future-major deprecations for
Litestar request-body markers and pandas `inplace=True` operations; the separate
migration work is tracked in TODOS.md.

Validation on 2026-10-23: full CI passes, including 1,855 backend tests, 266
frontend unit tests, the legacy frontend suite, coverage gates, lint/type/build
checks, both vulnerability audits and npm registry signatures. The complete
browser suite passes 72 checks with 12 intentional viewport skips across desktop,
mobile and tablet. Existing frontend project-type-check debt remains tracked in
TODOS.md. The post-install registry check for that changeset matched its
documented holds; the subsequent major review below updates those decisions.

### Major and breaking-version follow-up

Security screening preceded installation: registry metadata and relevant upstream
release guidance were reviewed for dateutil 3, multidict 7, TypeScript 7, Node 26 types,
Ruff 0.17, jsdom 30.1.3 and Knip 6.42.1, including the new selector/parser major
versions. OSV returned no known advisories for the nine reviewed candidates,
and again for every changed resolved version (29 package/version pairs,
including optional platform bindings and the new tzdata dependency). Advisory
screening is not a guarantee against an undisclosed compromise; installation
still requires hash/integrity checks and the CI audits.

Applied migrations:

- `python-dateutil 3.0.0`, explicitly pinned in production inputs, with generated
  locks for `tzdata 2026.5`. The [release rewrites timezone-file handling](https://github.com/dateutil/dateutil/releases/tag/3.0.0)
  and uses system/IANA timezone data instead of a bundled database. Candle
  serialization regression tests cover the two distinct instants in Vienna's
  repeated autumn hour and a summer date after 2038. No direct use of removed
  `dateutil.zoneinfo` rebuilding or mutable `TZPATHS` APIs was found in Moonwalker.
- `jsdom 30.1.3`, including `@asamuzakjp/dom-selector 10.0.5`. Its [release notes](https://github.com/jsdom/jsdom/releases/tag/v30.1.3)
  include CSS/selector behavior fixes and cross-origin XHR credential handling.
  The rendered component suite passes against this engine.
- `knip 6.42.1`, including `unbash 6.0.1`. The existing TypeScript-based legacy
  loader compiler remains unchanged. Knip executes and emits its normal JSON
  report; three unused exported types are reported, with no compiler/tool error.
  Knip remains an on-demand report, not a newly enforced CI gate.
- `ruff 0.17.2` using the documented compatibility rule selection above. The
  formatter and existing lint checks remain enforced; expanding default lint
  coverage requires a separate review rather than hundreds of incidental edits.

Incompatible targets retained after review:

- `multidict 7.1.0`: CCXT 4.5.90 requires exactly `multidict==6.9.1`. A forced
  override would violate its declared dependency contract. Revisit when a
  reviewed CCXT release permits multidict 7; no repackaged exchange library or
  resolver bypass is introduced.
- `typescript 7.0.2`: [Microsoft's Vue guidance](https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/#typescript-and-embedded-languages)
  still requires TypeScript 6's programmatic API. In addition to Vue tooling,
  `frontend/knip.ts` and the legacy test loader use that API directly. Retain 6.0.3;
  do not use a prerelease compiler or silently remove Vue/type-analysis checks.
- `@types/node 26.6.5`: the application supports Node 24, as declared by its npm
  engines, `.nvmrc` and `@tsconfig/node24`. Retain the updated 24.19.2 types until
  a separately reviewed Node runtime migration, so type checking cannot accept
  Node 26 APIs that are absent in the supported runtime.

Validation on 2026-10-23: full CI passes with 1,857 backend tests (including the
two timezone regression cases), 266 frontend unit tests, the legacy frontend
suite, coverage gates, lint/type/build checks, both vulnerability audits and npm
registry signatures. The browser suite passes 72 checks with 12 intentional
viewport skips across desktop, mobile and tablet. Existing frontend project
checking debt and future-major deprecations remain documented in TODOS.md.
Post-install outdated checks leave only CCXT-pinned Python dependencies,
TypeScript 7 and Node 26 types; no other reviewed update is pending.

## Zod security follow-up (2026-10-24)

Zod is now exactly pinned to `4.6.7` via an npm override, replacing the
`4.6.5` transitive dependency of Knip. The generated lock retains the verified
registry SHA-512 integrity. This fixes
[GHSA-mrhx-c7xc-m3w5](https://github.com/advisories/GHSA-mrhx-c7xc-m3w5),
which affects versions before `4.6.6`.

The [npm incident report and maintainer clarification](https://github.com/orgs/community/discussions/208477)
state that the malicious Zod repository changes never reached npm publishing.
The maintainer reports that history cleanup invalidated 4.6.6 provenance and
published 4.6.7 afterward. Moonwalker avoids 4.6.6; it was not installed during
this update. Vulnerability-advisory screening alone is not sufficient evidence
of release provenance.

Before installation, the 4.6.7 npm tarball was read as inert archive data. Its
840 files had no install lifecycle hooks, symlinks or known incident indicators.
The changes from the installed 4.6.5 artifact were inspected statically. Using
npm's bundled Sigstore verifier, its SLSA provenance signature was verified
against the GitHub Actions issuer and expected
`colinhacks/zod/.github/workflows/release.yml@refs/heads/main` identity. The
signed subject's SHA-512 digest matches the downloaded artifact and the lock;
the source commit is `b500a2ee95134f81d74da7911d7378dd2853d042`, matching the
[4.6.7 release](https://github.com/colinhacks/zod/releases/tag/v4.6.7).
The attested trigger is `workflow_dispatch`. These checks establish the
artifact's origin and exclude the known indicators; they are not a guarantee
against unknown malicious code. Installs continue to disable lifecycle scripts.

Validation: full CI passes with 1,860 backend tests, 266 frontend unit tests,
the legacy frontend suite, coverage gates, builds, both vulnerability audits and
npm registry-signature/attestation verification. The Knip JSON report is identical
to the pre-update report (three unused exported types, no tool error). Browser
E2E was not repeated for this dependency-only Knip transitive patch.

## Rollback

Revert the dependency-only changeset and rerun `./run.sh start`. Startup builds
and validates the inactive environment slot before changing the `.venv`
symlink. The predecessor remains at `.venv.previous`, and a failed dependency
install or import check never changes the active environment.
