# How to update dependencies after supply-chain review

Review proposed releases before installing them, regenerate reproducible locks,
and verify a focused dependency changeset.

## Prerequisites

- A clean feature branch for the dependency update.
- The repository's supported Python 3.14 and Node 24 runtimes; npm 11 and `uvx`
  for the documented lock compiler.
- An existing development environment with audit tools. Runtime startup switches
  `.venv` between release slots, so it can remove access to development tools.
  See [development environments](development.md#python-dead-code).
- Web access to registry metadata, security advisories and official maintainer
  incident/release reports.

Follow [AGENTS.md](../AGENTS.md#dependency-hygiene-mandatory) and the
[dependency reference](dependencies.md). Perform this review at least weekly
and before each release candidate.

## Step 1: Inventory candidates without installing them

From the repository root, run:

```bash
./.venv/bin/python -m pip list --outdated --format=json
npm --prefix frontend outdated --json
```

The Python result describes the installed environment, not every platform-specific
lock entry. The npm result describes direct outdated dependencies, not every
transitive update. `npm outdated` may exit nonzero when updates exist; inspect its
JSON rather than treating that alone as a network or resolver failure.

Record installed, locked and proposed versions separately where they differ.
Classify each proposal as **patch/minor candidate**, **major requiring compatibility
review**, or **unsafe/unresolved: hold**. Semantic versioning alone does not prove
that a release is safe or compatible. Inspect new transitive versions too.

## Step 2: Research compromise reports before changing packages

For each package and exact target version:

1. Search the web for the package name and version alongside terms such as
   `compromised`, `malware`, `maintainer account`, and `security advisory`.
   Check the project's official releases/security notices and registry notices.
2. Follow credible incident discussion to primary maintainer or registry reports.
   Establish whether the incident affected the repository, published artifacts,
   publisher credentials, build workflow, or several of those. A repository
   incident and a malicious registry release are different claims.
3. Check version-specific vulnerability advisories. A clean audit means only that
   the queried service has no matching known advisory; it is not compromise proof.
4. If a compromise is reported, inspect the proposed artifact as inert archive
   data before installation. Verify its digest, expected source commit and signed
   build provenance where available. Inspect lifecycle hooks and known malicious
   paths or network indicators. Verify the signature and expected identity, not
   merely the presence of an attestation link.
5. Hold the release if its involvement remains unresolved. Prefer a verified
   post-incident release when available. Record links, exact versions, artifact
   evidence and the update/hold decision in the task summary.

Do not run package code, install hooks or source-build hooks to inspect a suspect
release. A registry signature authenticates a registry statement; a matching hash
identifies bytes. Neither alone proves that those bytes are benign. The dated
[Zod review](dependencies.md#zod-security-follow-up-2026-10-24) illustrates the
additional origin checks, rather than providing permanent approval for future releases.

## Step 3: Review compatibility and transitive changes

Read release notes and constraints for direct and changed transitive packages.
Review major changes even if a direct package only has a patch/minor bump.
Respect exact upstream requirements; do not force a transitive major through an
override that violates its parent's contract.

Keep TypeScript and Node types aligned with the supported toolchain. Existing
version holds in the [dependency reference](dependencies.md) are dated decisions
that need fresh evidence before reversal. Document any required migration and
focused regression coverage before adopting the release.

## Step 4: Regenerate the relevant locks

For Python, edit exact inputs in `backend/requirements.in` and/or
`backend/requirements-dev.in`, then run:

```bash
./scripts/compile_requirements.sh
```

The script compiles both SHA-256 hash locks using its pinned pip-tools version
and checks lock policy. It preserves existing resolution where possible; inspect
that the intended target changed. For a transitive-only target, the resolver's
existing constraints may need a reviewed explicit input pin. Do not hand-edit
output locks or bypass parent requirements.

For frontend packages, edit exact versions or justified exact overrides in
`frontend/package.json`, then run:

```bash
npm --prefix frontend install --package-lock-only --ignore-scripts
```

Inspect the complete resolved lock diff, including optional and platform-specific
packages. Repeat the pre-install review for previously unreviewed releases
introduced by resolution. Then install the frontend graph without hooks:

```bash
npm --prefix frontend ci --ignore-scripts
```

Python installs must use the repository installer, hash locks and wheel-only
policy. With an existing development interpreter:

```bash
./scripts/install_python_dependencies.sh \
  "$PWD/.venvs/dev/bin/python" "$PWD/backend/requirements-dev.txt"
```

Substitute the actual development interpreter path if different. The reviewed
vendored pyaes wheel is handled by that installer; do not enable arbitrary source
builds to work around a missing wheel. Lifecycle scripts stay disabled during
inspection and initial installation.

## Step 5: Verify and record the result

Run full CI from the scripts directory:

```bash
cd scripts
PATH="/opt/homebrew/opt/node@24/bin:$PATH" ./ci.sh
```

The PATH prefix supplies Homebrew Node 24 on macOS; on other systems it leaves
their normal PATH available. Run migration-specific regressions and browser checks
when behavior changes justify them. Full CI includes vulnerability and registry
verification, but does not replace the pre-install web and artifact review.

For a focused dependency audit from the repository root:

```bash
./scripts/audit_dependencies.sh
```

This uses `.venv/bin/python` by default; select the environment that contains the
audit tools through `PYTHON_BIN` when necessary. Record audit results, tests,
research links, remaining version holds and any verification gaps. Keep the
changeset limited to dependency inputs, generated locks, required compatibility
changes and their documentation.

## Verification

Review `git diff --check` and the final diff. Confirm that only reviewed resolved
versions changed, both Python locks are consistent, npm scripts remain disabled,
and full CI passed against those final inputs. Recheck outdated packages after
installation; classify deliberate holds rather than blindly upgrading everything.

## Troubleshooting

| Failure | Action |
| --- | --- |
| New install hook or foreign registry rejected | Inspect origin and hook behavior. Do not expand the allowlist to make installation pass without review. |
| No compatible wheel | Check supported runtime and release artifacts. Retain the prior verified version rather than enabling an unreviewed source build. |
| Resolver rejects an update | Identify the parent constraint and hold the target or review a compatible parent update. |
| Provenance fails after an incident | Hold the artifact until its origin is resolved; a clean vulnerability scan is insufficient. |
| Audit tools missing from `.venv` | Use a stable development environment or reinstall the development lock with the repository installer. |
| CI fails | Distinguish compatibility/test failures, security findings and documented outdated-package holds; report each separately. |

Use [rollback instructions](dependencies.md#rollback) for a deployed dependency
changeset. Do not roll back to a known vulnerable release without explicitly
addressing that exposure.
