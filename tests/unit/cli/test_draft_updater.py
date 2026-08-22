"""Unit tests for the draft-update command-line interface."""

import json
import sys
from pathlib import Path
from typing import cast

import pytest

from fantasy_football_agent.cli.draft_updater import main

pytestmark = pytest.mark.unit


def _write_workspace(
    workspace: Path,
    *,
    current_overall_pick: int = 1,
    picks: list[dict[str, object]] | None = None,
) -> None:
    """Write the minimum application workspace required by the updater CLI."""
    (workspace / "config").mkdir()
    (workspace / "data").mkdir()

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
    }
    state = {
        "draft_id": "test-draft",
        "session_type": "mock",
        "my_draft_slot": 4,
        "current_overall_pick": current_overall_pick,
        "picks": [] if picks is None else picks,
    }

    (workspace / "config" / "league.json").write_text(
        json.dumps(league),
        encoding="utf-8",
    )
    (workspace / "data" / "draft_state.json").write_text(
        json.dumps(state),
        encoding="utf-8",
    )
    (workspace / "data" / "yahoo_rankings_2026.csv").write_text(
        (
            "Rank,ADP,Player Name,Position,Team,Bye,% Drafted,"
            "Yahoo Player ID,Manual - Tier\n"
            "1,1.5,Player One,RB,TST,5,99%,10001,1\n"
            "2,2.5,Player Two,WR,TST,7,95%,10002,1\n"
            "3,3.5,Player Three,QB,TST,9,90%,10003,1\n"
        ),
        encoding="utf-8",
    )


def _load_saved_state(workspace: Path) -> dict[str, object]:
    """Load persisted draft state written by the updater CLI."""
    data = json.loads((workspace / "data" / "draft_state.json").read_text(encoding="utf-8"))
    return cast(dict[str, object], data)


def test_main_records_positional_players_in_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    GIVEN: an empty draft and two player references supplied on the command line
    WHEN: the updater CLI records those players
    THEN: both picks are persisted in order and the draft advances twice
    """
    _write_workspace(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ff-draft-update",
            "Player One",
            "10002",
            "--workspace",
            str(tmp_path),
        ],
    )

    main()

    output = capsys.readouterr().out
    state = _load_saved_state(tmp_path)
    picks = state["picks"]

    assert isinstance(picks, list)
    assert [pick["player"] for pick in picks] == ["Player One", "Player Two"]
    assert [pick["overall"] for pick in picks] == [1, 2]
    assert state["current_overall_pick"] == 3
    assert "Recording picks:" in output
    assert "#1 T1 Player One (RB)" in output
    assert "#2 T2 Player Two (WR)" in output
    assert "Current overall pick is now #3." in output


def test_main_prompts_for_players_when_no_positional_arguments_are_supplied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    GIVEN: no player references on the command line and two interactive entries
    WHEN: the updater CLI prompts until a blank line is entered
    THEN: both entered players are recorded and persisted in order
    """
    _write_workspace(tmp_path)
    responses = iter(["Player One", "Player Two", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))
    monkeypatch.setattr(
        sys,
        "argv",
        ["ff-draft-update", "--workspace", str(tmp_path)],
    )

    main()

    output = capsys.readouterr().out
    state = _load_saved_state(tmp_path)
    picks = state["picks"]

    assert isinstance(picks, list)
    assert [pick["player"] for pick in picks] == ["Player One", "Player Two"]
    assert state["current_overall_pick"] == 3
    assert "Enter drafted players in order, one per line." in output
    assert "Press Enter on a blank line when finished." in output


def test_main_leaves_state_unchanged_when_prompt_receives_no_players(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    GIVEN: no positional player references and an immediate blank interactive entry
    WHEN: the updater CLI receives no drafted players
    THEN: it reports no change and leaves the persisted draft state untouched
    """
    _write_workspace(tmp_path)
    original_state = _load_saved_state(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    monkeypatch.setattr(
        sys,
        "argv",
        ["ff-draft-update", "--workspace", str(tmp_path)],
    )

    main()

    output = capsys.readouterr().out

    assert "No picks entered. Draft state unchanged." in output
    assert _load_saved_state(tmp_path) == original_state


def test_main_undo_removes_last_pick_even_when_player_argument_is_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    GIVEN: one recorded pick plus both --undo and a player reference
    WHEN: the updater CLI runs
    THEN: undo takes precedence and no new player is recorded
    """
    _write_workspace(
        tmp_path,
        current_overall_pick=2,
        picks=[
            {
                "overall": 1,
                "round": 1,
                "pick_in_round": 1,
                "team_id": 1,
                "player": "Player One",
                "position": "RB",
                "yahoo_player_id": 10001,
            }
        ],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ff-draft-update",
            "Player Two",
            "--undo",
            "--workspace",
            str(tmp_path),
        ],
    )

    main()

    output = capsys.readouterr().out
    state = _load_saved_state(tmp_path)

    assert state["picks"] == []
    assert state["current_overall_pick"] == 1
    assert "Undid pick #1: Player One (RB)" in output
    assert "Current overall pick is now #1." in output
    assert "Recording picks:" not in output


def test_main_reports_error_when_undo_is_requested_without_recorded_picks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    GIVEN: draft state with no recorded selections
    WHEN: the updater CLI is asked to undo the last pick
    THEN: it reports the error and leaves the persisted state unchanged
    """
    _write_workspace(tmp_path)
    original_state = _load_saved_state(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["ff-draft-update", "--undo", "--workspace", str(tmp_path)],
    )

    main()

    output = capsys.readouterr().out

    assert "ERROR: There are no draft picks to undo." in output
    assert _load_saved_state(tmp_path) == original_state


def test_main_persists_successful_picks_before_later_reference_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    GIVEN: a valid player followed by an unknown player and another valid player
    WHEN: the updater CLI records the sequence
    THEN: the first pick stays saved while the failed and remaining picks are skipped
    """
    _write_workspace(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ff-draft-update",
            "Player One",
            "Unknown Player",
            "Player Three",
            "--workspace",
            str(tmp_path),
        ],
    )

    main()

    output = capsys.readouterr().out
    state = _load_saved_state(tmp_path)
    picks = state["picks"]

    assert isinstance(picks, list)
    assert [pick["player"] for pick in picks] == ["Player One"]
    assert state["current_overall_pick"] == 2
    assert "#1 T1 Player One (RB)" in output
    assert 'ERROR: No ranked player found matching "Unknown Player".' in output
    assert "Remaining picks were not recorded." in output
    assert "Player Three" not in output
    assert "Current overall pick is now #2." in output
