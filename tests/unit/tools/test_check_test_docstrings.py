"""Unit tests for the GIVEN/WHEN/THEN test-docstring checker."""

from pathlib import Path

import pytest
from tools.check_test_docstrings import main

pytestmark = pytest.mark.unit


def _write_test_file(path: Path, source: str) -> None:
    """Write a temporary Python test module for checker validation."""
    path.write_text(source, encoding="utf-8")


def test_main_accepts_valid_given_when_then_docstring(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    GIVEN: a test function with populated GIVEN, WHEN, and THEN lines in order
    WHEN: the docstring checker scans the file
    THEN: the checker succeeds without reporting a violation
    """
    test_file = tmp_path / "test_valid.py"
    _write_test_file(
        test_file,
        "def test_valid() -> None:\n"
        '    """\n'
        "    GIVEN: valid state\n"
        "    WHEN: behavior is executed\n"
        "    THEN: the expected result occurs\n"
        '    """\n'
        "    pass\n",
    )

    exit_code = main([str(test_file)])

    output = capsys.readouterr()
    assert exit_code == 0
    assert "Test docstring check passed" in output.out
    assert output.err == ""


@pytest.mark.parametrize(
    ("docstring", "expected_error"),
    [
        (
            "GIVEN: valid state\nTHEN: the expected result occurs",
            "missing WHEN:",
        ),
        (
            "GIVEN:\nWHEN: behavior is executed\nTHEN: the expected result occurs",
            "GIVEN: must include a description",
        ),
        (
            "WHEN: behavior is executed\nGIVEN: valid state\nTHEN: the expected result occurs",
            "GIVEN:, WHEN:, and THEN: must appear in that order",
        ),
    ],
)
def test_main_rejects_invalid_bdd_docstring_structure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    docstring: str,
    expected_error: str,
) -> None:
    """
    GIVEN: a test function whose BDD docstring violates the required structure
    WHEN: the docstring checker scans the file
    THEN: the checker fails and reports the specific structural violation
    """
    indented_docstring = "\n".join(f"    {line}" for line in docstring.splitlines())
    test_file = tmp_path / "test_invalid.py"
    _write_test_file(
        test_file,
        (f'def test_invalid() -> None:\n    """\n{indented_docstring}\n    """\n    pass\n'),
    )

    exit_code = main([str(test_file)])

    output = capsys.readouterr()
    assert exit_code == 1
    assert expected_error in output.err


def test_main_rejects_test_function_without_docstring(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    GIVEN: a pytest-style test function without any docstring
    WHEN: the docstring checker scans the file
    THEN: the checker fails and reports the missing docstring
    """
    test_file = tmp_path / "test_missing_docstring.py"
    _write_test_file(
        test_file,
        "def test_missing_docstring() -> None:\n    pass\n",
    )

    exit_code = main([str(test_file)])

    output = capsys.readouterr()
    assert exit_code == 1
    assert "test_missing_docstring: missing docstring" in output.err


def test_main_scans_nested_files_and_async_tests(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    GIVEN: valid synchronous and asynchronous tests in nested directories
    WHEN: the checker scans their parent directory recursively
    THEN: both Python files are inspected successfully
    """
    nested = tmp_path / "nested"
    nested.mkdir()
    _write_test_file(
        tmp_path / "test_sync.py",
        "def test_sync() -> None:\n"
        '    """\n'
        "    GIVEN: synchronous test state\n"
        "    WHEN: the test runs\n"
        "    THEN: its behavior is checked\n"
        '    """\n'
        "    pass\n",
    )
    _write_test_file(
        nested / "test_async.py",
        "async def test_async() -> None:\n"
        '    """\n'
        "    GIVEN: asynchronous test state\n"
        "    WHEN: the test runs\n"
        "    THEN: its behavior is checked\n"
        '    """\n'
        "    pass\n",
    )

    exit_code = main([str(tmp_path)])

    output = capsys.readouterr()
    assert exit_code == 0
    assert "passed for 2 Python file(s)" in output.out


def test_main_reports_python_syntax_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    GIVEN: a Python test file that cannot be parsed
    WHEN: the docstring checker scans the file
    THEN: the checker fails and reports the syntax error location
    """
    test_file = tmp_path / "test_broken.py"
    _write_test_file(
        test_file,
        "def test_broken( -> None:\n    pass\n",
    )

    exit_code = main([str(test_file)])

    output = capsys.readouterr()
    assert exit_code == 1
    assert "unable to parse file" in output.err
    assert str(test_file) in output.err


def test_main_rejects_missing_requested_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    GIVEN: a requested scan path that does not exist
    WHEN: the docstring checker starts
    THEN: it returns a configuration error without attempting a scan
    """
    missing_path = tmp_path / "does-not-exist"

    exit_code = main([str(missing_path)])

    output = capsys.readouterr()
    assert exit_code == 2
    assert f"{missing_path}: path does not exist" in output.err
