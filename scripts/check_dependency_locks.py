#!/usr/bin/env python3
"""Validate that committed dependency locks fail closed on unexpected input."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement

ROOT_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT_DIR / "frontend"
EXACT_VERSION = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
ALLOWED_INSTALL_SCRIPTS = {
    "node_modules/fsevents": "2.3.3",
    "node_modules/rete": "2.0.6",
}
PYAE_WHEEL = ROOT_DIR / "backend/vendor/pyaes-1.6.1-py3-none-any.whl"
PYAE_SHA256 = "97e69519924dde9254b26b20fe37eebb4a6b811d6bda4945a53fba04a4188a83"


def validate_python_lock(path: Path) -> list[str]:
    """Return errors for unhashed or URL-based Python requirements."""
    errors: list[str] = []
    block_lines: list[str] = []

    def validate_block(lines: list[str]) -> None:
        if not lines:
            return
        first_line = lines[0].removesuffix("\\").strip()
        block = "\n".join(lines)
        if first_line.startswith(("-", "http://", "https://", "git+", ".", "/")):
            errors.append(f"{path.name}: unsupported requirement source {first_line}")
            return
        try:
            requirement = Requirement(first_line)
        except InvalidRequirement:
            errors.append(f"{path.name}: invalid requirement {first_line}")
            return
        package = requirement.name
        if requirement.url:
            errors.append(f"{path.name}: {package} uses a direct URL")
            return
        for continuation in lines[1:]:
            stripped = continuation.strip().removesuffix("\\").strip()
            if stripped.startswith("--hash=sha256:"):
                continue
            errors.append(
                f"{path.name}: unsupported requirement continuation {stripped}"
            )
        if " --hash=sha256:" not in block:
            errors.append(f"{path.name}: {package} has no SHA-256 hash")

    for raw_line in path.read_text().splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if raw_line[:1].isspace():
            if not block_lines:
                errors.append(
                    f"{path.name}: unsupported indented requirement line {stripped}"
                )
            else:
                block_lines.append(raw_line)
            continue

        validate_block(block_lines)
        block_lines = [raw_line]

    validate_block(block_lines)
    return errors


def validate_npm_lock() -> list[str]:
    """Return errors for floating roots, foreign registries, or new hooks."""
    errors: list[str] = []
    manifest = json.loads((FRONTEND_DIR / "package.json").read_text())
    lock = json.loads((FRONTEND_DIR / "package-lock.json").read_text())

    for section in ("dependencies", "devDependencies", "overrides"):
        for package, version in manifest.get(section, {}).items():
            if not EXACT_VERSION.fullmatch(version):
                errors.append(f"package.json: {package} is not exactly pinned ({version})")

    install_scripts: dict[str, str] = {}
    for package_path, metadata in lock.get("packages", {}).items():
        resolved = metadata.get("resolved")
        integrity = metadata.get("integrity")
        if resolved and not resolved.startswith("https://registry.npmjs.org/"):
            errors.append(f"package-lock.json: foreign registry for {package_path}")
        if resolved and not str(integrity).startswith("sha512-"):
            errors.append(f"package-lock.json: missing SHA-512 integrity for {package_path}")
        if metadata.get("hasInstallScript"):
            install_scripts[package_path] = metadata.get("version", "")

    if install_scripts != ALLOWED_INSTALL_SCRIPTS:
        errors.append(
            "package-lock.json: install-script allowlist changed "
            f"(expected {ALLOWED_INSTALL_SCRIPTS}, got {install_scripts})"
        )
    return errors


def main() -> int:
    """Validate all committed lock files."""
    errors = validate_npm_lock()
    errors.extend(validate_python_lock(ROOT_DIR / "backend/requirements.txt"))
    errors.extend(validate_python_lock(ROOT_DIR / "backend/requirements-dev.txt"))
    wheel_hash = hashlib.sha256(PYAE_WHEEL.read_bytes()).hexdigest()
    if wheel_hash != PYAE_SHA256:
        errors.append("vendored pyaes wheel failed SHA-256 verification")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Dependency locks are exact, integrity-pinned, and policy-compliant.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
