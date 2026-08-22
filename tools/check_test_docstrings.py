"""Enforce GIVEN/WHEN/THEN docstrings on pytest test functions."""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

_REQUIRED_LABELS = ("GIVEN:", "WHEN:", "THEN:")


def _python_files(paths: Sequence[Path]) -> list[Path]:
    """Return Python files found beneath the requested paths."""
    files: set[Path] = set()

    for path in paths:
        if path.is_file():
            if path.suffix == ".py":
                files.add(path)
            continue

        if path.is_dir():
            files.update(candidate for candidate in path.rglob("*.py") if candidate.is_file())

    return sorted(files)


def _test_functions(
    tree: ast.AST,
) -> Iterable[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Yield every pytest-style test function found in an AST."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
            "test_"
        ):
            yield node


def _validate_docstring(docstring: str | None) -> str | None:
    """Return an error message when a test docstring violates the BDD format."""
    if docstring is None:
        return "missing docstring"

    lines = [line.strip() for line in docstring.splitlines() if line.strip()]
    label_indexes: list[int] = []

    for label in _REQUIRED_LABELS:
        matching_indexes = [index for index, line in enumerate(lines) if line.startswith(label)]

        if not matching_indexes:
            return f"missing {label}"

        index = matching_indexes[0]
        value = lines[index][len(label) :].strip()
        if not value:
            return f"{label} must include a description"

        label_indexes.append(index)

    if label_indexes != sorted(label_indexes):
        return "GIVEN:, WHEN:, and THEN: must appear in that order"

    return None


def _check_file(path: Path) -> list[str]:
    """Return GIVEN/WHEN/THEN violations found in one Python file."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{path}: unable to read file: {exc}"]

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        line = exc.lineno or 1
        return [f"{path}:{line}: unable to parse file: {exc.msg}"]

    errors: list[str] = []

    for function in _test_functions(tree):
        error = _validate_docstring(ast.get_docstring(function, clean=True))
        if error is not None:
            errors.append(f"{path}:{function.lineno}: {function.name}: {error}")

    return errors


def main(argv: Sequence[str] | None = None) -> int:
    """Check test functions and return a process exit code."""
    raw_paths = list(sys.argv[1:] if argv is None else argv)
    paths = [Path(value) for value in raw_paths] if raw_paths else [Path("tests")]

    missing_paths = [path for path in paths if not path.exists()]
    if missing_paths:
        for path in missing_paths:
            print(f"{path}: path does not exist", file=sys.stderr)
        return 2

    files = _python_files(paths)
    errors: list[str] = []

    for path in files:
        errors.extend(_check_file(path))

    if errors:
        print("Test docstring check failed:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        print(
            f"Found {len(errors)} test docstring violation(s).",
            file=sys.stderr,
        )
        return 1

    print(f"Test docstring check passed for {len(files)} Python file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
