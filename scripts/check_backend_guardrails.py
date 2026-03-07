#!/usr/bin/env python3
"""Backend guardrails for strategy contracts and commented code blocks."""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path


MAX_COMMENT_BLOCK_LINES = int(os.getenv("MAX_COMMENT_BLOCK_LINES", "12"))


class IndicatorCallVisitor(ast.NodeVisitor):
    """Collect `self.indicators.<method>(...)` calls from strategy modules."""

    def __init__(self) -> None:
        self.methods: set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Attribute)
            and isinstance(func.value.value, ast.Name)
            and func.value.value.id == "self"
            and func.value.attr == "indicators"
        ):
            self.methods.add(func.attr)
        self.generic_visit(node)


def parse_strategy_indicator_calls(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    visitor = IndicatorCallVisitor()
    visitor.visit(tree)
    return visitor.methods


def find_large_commented_blocks(path: Path, threshold: int) -> list[tuple[int, int]]:
    blocks: list[tuple[int, int]] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    comment_re = re.compile(r"^\s*#")
    start: int | None = None
    length = 0

    for line_no, line in enumerate(lines, start=1):
        if comment_re.match(line):
            if start is None:
                start = line_no
            length += 1
            continue

        if start is not None and length >= threshold:
            blocks.append((start, length))
        start = None
        length = 0

    if start is not None and length >= threshold:
        blocks.append((start, length))

    return blocks


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    backend_dir = root / "backend"
    strategy_dir = backend_dir / "strategies"
    service_dir = backend_dir / "service"

    sys.path.insert(0, str(backend_dir))
    from service.strategy_capability import REQUIRED_INDICATOR_METHODS

    errors: list[str] = []

    strategy_files = sorted(
        p
        for p in strategy_dir.glob("*.py")
        if p.name != "__init__.py" and "__pycache__" not in p.parts
    )
    strategy_names = {p.stem for p in strategy_files}
    mapped_names = set(REQUIRED_INDICATOR_METHODS.keys())

    for strategy_name in sorted(strategy_names):
        if strategy_name not in REQUIRED_INDICATOR_METHODS:
            errors.append(
                "Missing REQUIRED_INDICATOR_METHODS entry for strategy "
                f"'{strategy_name}'."
            )

    for strategy_name in sorted(mapped_names - strategy_names):
        errors.append(
            f"REQUIRED_INDICATOR_METHODS references non-existing strategy "
            f"'{strategy_name}'."
        )

    for strategy_file in strategy_files:
        strategy_name = strategy_file.stem
        actual_methods = parse_strategy_indicator_calls(strategy_file)
        required_methods = set(REQUIRED_INDICATOR_METHODS.get(strategy_name, ()))

        if required_methods != actual_methods:
            missing_in_map = sorted(actual_methods - required_methods)
            stale_in_map = sorted(required_methods - actual_methods)
            errors.append(
                f"Strategy '{strategy_name}' mismatch: "
                f"missing_in_map={missing_in_map}, stale_in_map={stale_in_map}."
            )

    for service_file in sorted(service_dir.glob("*.py")):
        blocks = find_large_commented_blocks(
            service_file, threshold=MAX_COMMENT_BLOCK_LINES
        )
        for start, length in blocks:
            errors.append(
                f"Large commented block ({length} lines) in "
                f"{service_file.relative_to(root)}:{start}."
            )

    if errors:
        print("Guardrail check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Guardrail checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
