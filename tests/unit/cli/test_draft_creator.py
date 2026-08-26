"""Unit tests for the draft-creation command-line interface."""

import json
import sys
from pathlib import Path
from typing import cast

import pytest

from fantasy_football_agent.cli.draft_creator import main

pytestmark = pytest.mark.unit


def _write_league_config(workspace: Path) -> None:
    """Write the minimum league configuration required to create a draft."""
    (workspace / "config").mkdir(parents=True)

    league = {
        "league_name": "Test League",
        "teams": 10,
        "draft": {"type": "snake"},
        "roster": {
            "QB": 1,
            "WR": 2,
            "RB": 2,
            "TE": 1,
            "FLEX": 1,
            "K": 1,
            "DEF": 1,
            "BENCH": 6,
            "IR": 2,
        },
        "flex_positions": ["RB", "WR", "TE"],
        "scoring": {"receptions": 0.5},
        "draft_strategy": {
            "position_roster_targets": {
                "QB": 1,
                "RB": 4,
                "WR": 4,
                "TE": 1,
                "K": 1,
                "DEF": 1,
            }
        },
    }

    (workspace / "config" / "league.json").write_text(
        json.dumps(league),
        encoding="utf-8",
    )


def _load_saved_state(workspace: Path) -> dict[str, object]:
    """Load draft state written by the draft-creation CLI."""
    data = json.loads((workspace / "data" / "draft_state.json").read_text(encoding="utf-8"))

    return cast(dict[str, object], data)


class TestDraftCreatorCli:
    """Draft-creation CLI behavior."""

    def test_creates_empty_session(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """
        GIVEN: a valid league and explicit mock-draft settings
        WHEN: a new draft session is created
        THEN: an empty draft state starting at overall pick one is persisted
        """
        _write_league_config(tmp_path)

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "ff-draft-new",
                "--type",
                "mock",
                "--slot",
                "4",
                "--draft-id",
                "mock-test-001",
                "--workspace",
                str(tmp_path),
            ],
        )

        main()

        state = _load_saved_state(tmp_path)
        output = capsys.readouterr().out

        assert state == {
            "draft_id": "mock-test-001",
            "session_type": "mock",
            "my_draft_slot": 4,
            "current_overall_pick": 1,
            "picks": [],
        }
        assert "Created draft session:" in output
        assert "Draft slot: 4" in output

    def test_generates_id_when_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        GIVEN: valid draft settings without an explicit draft ID
        WHEN: a new draft session is created
        THEN: a readable session-type-prefixed draft ID is generated
        """
        _write_league_config(tmp_path)

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "ff-draft-new",
                "--type",
                "mock",
                "--slot",
                "7",
                "--workspace",
                str(tmp_path),
            ],
        )

        main()

        state = _load_saved_state(tmp_path)
        draft_id = state["draft_id"]

        assert isinstance(draft_id, str)
        assert draft_id.startswith("mock-")

    def test_existing_draft_requires_replace(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """
        GIVEN: an active draft-state file already exists
        WHEN: a new draft is requested without --replace
        THEN: the existing draft remains unchanged
        """
        _write_league_config(tmp_path)
        (tmp_path / "data").mkdir()

        original = {
            "draft_id": "existing-draft",
            "session_type": "mock",
            "my_draft_slot": 2,
            "current_overall_pick": 15,
            "picks": [],
        }

        draft_state_path = tmp_path / "data" / "draft_state.json"
        draft_state_path.write_text(
            json.dumps(original),
            encoding="utf-8",
        )

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "ff-draft-new",
                "--type",
                "mock",
                "--slot",
                "5",
                "--workspace",
                str(tmp_path),
            ],
        )

        main()

        output = capsys.readouterr().out

        assert _load_saved_state(tmp_path) == original
        assert "An active draft state already exists" in output
        assert "Use --replace" in output

    def test_replace_overwrites_existing_draft(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        GIVEN: an existing active draft and an explicit replacement request
        WHEN: a new draft session is created with --replace
        THEN: the previous state is replaced by a fresh empty session
        """
        _write_league_config(tmp_path)
        (tmp_path / "data").mkdir()

        old_state = {
            "draft_id": "old-draft",
            "session_type": "mock",
            "my_draft_slot": 4,
            "current_overall_pick": 50,
            "picks": [
                {
                    "overall": 1,
                    "round": 1,
                    "pick_in_round": 1,
                    "team_id": 1,
                    "player": "Old Player",
                    "position": "RB",
                    "yahoo_player_id": 10001,
                }
            ],
        }

        (tmp_path / "data" / "draft_state.json").write_text(
            json.dumps(old_state),
            encoding="utf-8",
        )

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "ff-draft-new",
                "--type",
                "mock",
                "--slot",
                "8",
                "--draft-id",
                "new-draft",
                "--replace",
                "--workspace",
                str(tmp_path),
            ],
        )

        main()

        state = _load_saved_state(tmp_path)

        assert state["draft_id"] == "new-draft"
        assert state["my_draft_slot"] == 8
        assert state["current_overall_pick"] == 1
        assert state["picks"] == []

    def test_rejects_slot_outside_league(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """
        GIVEN: a ten-team league and an invalid draft slot
        WHEN: creation of the draft session is attempted
        THEN: validation rejects the session and no draft-state file is written
        """
        _write_league_config(tmp_path)

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "ff-draft-new",
                "--type",
                "mock",
                "--slot",
                "11",
                "--workspace",
                str(tmp_path),
            ],
        )

        main()

        output = capsys.readouterr().out

        assert "ERROR: Draft slot must be between 1 and 10." in output
        assert not (tmp_path / "data" / "draft_state.json").exists()
