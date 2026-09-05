"""Unit tests for workspace-relative application paths."""

from pathlib import Path

import pytest

from fantasy_football_agent.application_paths import ApplicationPaths

pytestmark = pytest.mark.unit


def test_application_paths_resolve_expected_files_from_workspace(
    tmp_path: Path,
) -> None:
    """
    GIVEN: an application workspace directory
    WHEN: the application's configured file paths are requested
    THEN: each path is derived from that workspace without repository assumptions
    """
    paths = ApplicationPaths(workspace=tmp_path)

    assert paths.league_config == tmp_path / "config" / "league.json"
    assert paths.draft_strategy == tmp_path / "config" / "draft_strategy.json"
    assert paths.draft_state == tmp_path / "data" / "draft_state.json"
    assert paths.draft_sync_status == tmp_path / "data" / "draft_sync_status.json"
    assert paths.draft_logs == tmp_path / "data" / "draft_logs"
    assert paths.rankings == tmp_path / "data" / "yahoo_rankings_2026.csv"
    assert paths.player_overrides == tmp_path / "data" / "player_overrides_2026.json"
    assert paths.custom_gpt_instructions == (tmp_path / "docs" / "custom_gpt" / "instructions.md")
    assert paths.custom_gpt_knowledge == (
        tmp_path / "docs" / "custom_gpt" / "yahoo_auto_draft_2026.md"
    )
    assert paths.yahoo_oauth == tmp_path / "oauth2.json"
