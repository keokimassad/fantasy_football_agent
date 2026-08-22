"""Unit tests for Yahoo OAuth configuration resolution."""

from pathlib import Path

import pytest

from fantasy_football_agent.application_paths import ApplicationPaths
from fantasy_football_agent.yahoo.yahoo_config import resolve_yahoo_oauth_file

pytestmark = pytest.mark.unit


def test_resolve_yahoo_oauth_file_prefers_explicit_path_over_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    GIVEN: both an explicit OAuth path and YAHOO_OAUTH_FILE are configured
    WHEN: the Yahoo OAuth file is resolved
    THEN: the explicit path wins and is returned as a concrete absolute path
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("YAHOO_OAUTH_FILE", "environment/oauth2.json")
    paths = ApplicationPaths(workspace=tmp_path)

    resolved = resolve_yahoo_oauth_file(
        paths,
        explicit_path=Path("explicit/oauth2.json"),
    )

    assert resolved == (tmp_path / "explicit" / "oauth2.json").resolve()


def test_resolve_yahoo_oauth_file_uses_environment_path_when_no_explicit_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    GIVEN: YAHOO_OAUTH_FILE is configured and no explicit path is supplied
    WHEN: the Yahoo OAuth file is resolved
    THEN: the environment path is expanded and returned as an absolute path
    """
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("YAHOO_OAUTH_FILE", "~/secrets/yahoo-oauth.json")
    paths = ApplicationPaths(workspace=tmp_path)

    resolved = resolve_yahoo_oauth_file(paths)

    assert resolved == (home / "secrets" / "yahoo-oauth.json").resolve()


def test_resolve_yahoo_oauth_file_falls_back_to_workspace_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    GIVEN: no explicit OAuth path and no YAHOO_OAUTH_FILE environment value
    WHEN: the Yahoo OAuth file is resolved
    THEN: the workspace oauth2.json path is returned
    """
    monkeypatch.delenv("YAHOO_OAUTH_FILE", raising=False)
    paths = ApplicationPaths(workspace=tmp_path)

    resolved = resolve_yahoo_oauth_file(paths)

    assert resolved == tmp_path / "oauth2.json"
