"""Unit tests for the draft-update command-line interface."""

import io
import json
import sys
from pathlib import Path
from typing import cast
from unittest.mock import mock_open

import pytest

from fantasy_football_agent.cli.draft_updater import (
    _read_terminal_input,
    main,
)

pytestmark = pytest.mark.unit


class _InteractiveInput(io.StringIO):
    """String input that reports itself as an attached terminal."""

    def isatty(self) -> bool:
        return True


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


def _add_ambiguous_robinsons(workspace: Path) -> None:
    """Add two players that intentionally collide under Yahoo abbreviation rules."""
    rankings_path = workspace / "data" / "yahoo_rankings_2026.csv"

    with rankings_path.open("a", encoding="utf-8") as rankings:
        rankings.write(
            "4,1.9,Bijan Robinson,RB,ATL,11,100%,40055,1\n"
            "155,123.1,Brian Robinson,RB,ATL,11,50%,34054,9\n"
        )


class TestManualDraftUpdates:
    """Manual draft-update CLI workflows."""

    def test_records_positional_players_in_order(
        self,
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

    def test_prompts_when_player_arguments_missing(
        self,
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

    def test_blank_prompt_leaves_state_unchanged(
        self,
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

    def test_undo_overrides_player_argument(
        self,
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

    def test_undo_without_picks_reports_error(
        self,
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

    def test_prior_pick_persists_before_later_reference_failure(
        self,
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


class TestYahooChatUpdates:
    """Yahoo copied-chat synchronization workflows."""

    def test_synchronizes_chat_from_stdin(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """
        GIVEN: an empty draft and two Yahoo selections supplied through standard input
        WHEN: the updater runs in Yahoo-chat mode
        THEN: both selections are resolved, persisted, and draft state advances
        """
        _write_workspace(tmp_path)

        monkeypatch.setattr(
            sys,
            "stdin",
            io.StringIO(
                """
                1
                Chris
                P. One
                RB
                TST
                Bye 5

                2
                Wes
                P. Two
                WR
                TST
                Bye 7
                """
            ),
        )

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "ff-draft-update",
                "--yahoo-chat",
                "--workspace",
                str(tmp_path),
            ],
        )

        main()

        output = capsys.readouterr().out
        state = _load_saved_state(tmp_path)
        picks = state["picks"]

        assert isinstance(picks, list)
        assert [pick["player"] for pick in picks] == [
            "Player One",
            "Player Two",
        ]
        assert state["current_overall_pick"] == 3
        assert "RECORDED #1 T1 Player One (RB)" in output
        assert "RECORDED #2 T2 Player Two (WR)" in output

    def test_overlap_verified_before_new_pick(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """
        GIVEN: local state containing pick one and Yahoo text containing picks one and two
        WHEN: the Yahoo history is synchronized
        THEN: pick one is verified and only pick two is newly recorded
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
            "stdin",
            io.StringIO(
                """
                1
                Chris
                P. One
                RB
                TST
                Bye 5

                2
                Wes
                P. Two
                WR
                TST
                Bye 7
                """
            ),
        )

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "ff-draft-update",
                "--yahoo-chat",
                "--workspace",
                str(tmp_path),
            ],
        )

        main()

        output = capsys.readouterr().out
        state = _load_saved_state(tmp_path)

        assert state["current_overall_pick"] == 3
        assert "VERIFIED #1 T1 Player One (RB)" in output
        assert "RECORDED #2 T2 Player Two (WR)" in output

    def test_ambiguous_player_selection_continues_sync(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """
        GIVEN: Yahoo chat containing an ambiguous player followed by another valid pick
        WHEN: the user selects the intended candidate at the terminal prompt
        THEN: the selected player is recorded and synchronization continues
        """
        _write_workspace(tmp_path)
        _add_ambiguous_robinsons(tmp_path)

        monkeypatch.setattr(
            sys,
            "stdin",
            io.StringIO(
                """
                1
                Chris
                P. One
                RB
                TST
                Bye 5

                2
                Wes
                B. Robinson
                RB
                ATL
                Bye 11

                3
                Jace
                P. Three
                QB
                TST
                Bye 9
                """
            ),
        )
        monkeypatch.setattr(
            "fantasy_football_agent.cli.draft_updater._read_terminal_input",
            lambda _prompt: "1",
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "ff-draft-update",
                "--yahoo-chat",
                "--workspace",
                str(tmp_path),
            ],
        )

        main()

        output = capsys.readouterr().out
        state = _load_saved_state(tmp_path)
        picks = state["picks"]

        assert isinstance(picks, list)
        assert [pick["player"] for pick in picks] == [
            "Player One",
            "Bijan Robinson",
            "Player Three",
        ]
        assert state["current_overall_pick"] == 4
        assert 'Ambiguous Yahoo player at pick #2: "B. Robinson"' in output
        assert "RECORDED #2 T2 Bijan Robinson (RB)" in output
        assert "RECORDED #3 T3 Player Three (QB)" in output

    def test_cancelled_ambiguity_preserves_prior_picks(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """
        GIVEN: a successful Yahoo pick followed by an ambiguous player and another pick
        WHEN: the user cancels the ambiguity prompt
        THEN: the earlier pick remains saved and later selections are not recorded
        """
        _write_workspace(tmp_path)
        _add_ambiguous_robinsons(tmp_path)

        monkeypatch.setattr(
            sys,
            "stdin",
            io.StringIO(
                """
                1
                Chris
                P. One
                RB
                TST
                Bye 5

                2
                Wes
                B. Robinson
                RB
                ATL
                Bye 11

                3
                Jace
                P. Three
                QB
                TST
                Bye 9
                """
            ),
        )
        monkeypatch.setattr(
            "fantasy_football_agent.cli.draft_updater._read_terminal_input",
            lambda _prompt: "q",
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "ff-draft-update",
                "--yahoo-chat",
                "--workspace",
                str(tmp_path),
            ],
        )

        with pytest.raises(SystemExit) as exit_info:
            main()

        output = capsys.readouterr().out
        state = _load_saved_state(tmp_path)
        picks = state["picks"]

        assert exit_info.value.code == 1
        assert isinstance(picks, list)
        assert [pick["player"] for pick in picks] == ["Player One"]
        assert state["current_overall_pick"] == 2
        sync_status = json.loads(
            (tmp_path / "data" / "draft_sync_status.json").read_text(encoding="utf-8")
        )
        assert sync_status["draft_id"] == "test-draft"
        assert sync_status["observed_yahoo_pick"] == 2
        assert "Synchronization cancelled." in output
        assert "DRAFT STATE MARKED STALE — RECOMMENDATIONS DISABLED" in output
        assert "Remaining picks were not recorded." in output
        assert "Player Three" not in output

    def test_invalid_ambiguity_choice_reprompts(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """
        GIVEN: an ambiguous Yahoo player and an invalid initial candidate selection
        WHEN: the user then enters a valid candidate number
        THEN: the prompt retries and records the selected player
        """
        _write_workspace(tmp_path)
        _add_ambiguous_robinsons(tmp_path)

        responses = iter(["9", "1"])

        monkeypatch.setattr(
            sys,
            "stdin",
            io.StringIO(
                """
                1
                Chris
                B. Robinson
                RB
                ATL
                Bye 11
                """
            ),
        )
        monkeypatch.setattr(
            "fantasy_football_agent.cli.draft_updater._read_terminal_input",
            lambda _prompt: next(responses),
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "ff-draft-update",
                "--yahoo-chat",
                "--workspace",
                str(tmp_path),
            ],
        )

        main()

        output = capsys.readouterr().out
        state = _load_saved_state(tmp_path)
        picks = state["picks"]

        assert isinstance(picks, list)
        assert [pick["player"] for pick in picks] == ["Bijan Robinson"]
        assert state["current_overall_pick"] == 2
        assert "Invalid selection." in output
        assert "RECORDED #1 T1 Bijan Robinson (RB)" in output

    def test_prior_yahoo_picks_persist_before_gap(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """
        GIVEN: Yahoo chat containing a valid current pick followed by a future pick with a gap
        WHEN: synchronization reaches the missing selection
        THEN: the valid earlier pick remains persisted and synchronization stops
        """
        _write_workspace(tmp_path)

        monkeypatch.setattr(
            sys,
            "stdin",
            io.StringIO(
                """
                1
                Chris
                P. One
                RB
                TST
                Bye 5

                3
                Jace
                P. Three
                QB
                TST
                Bye 9
                """
            ),
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "ff-draft-update",
                "--yahoo-chat",
                "--workspace",
                str(tmp_path),
            ],
        )

        with pytest.raises(SystemExit) as exit_info:
            main()

        output = capsys.readouterr().out
        state = _load_saved_state(tmp_path)
        picks = state["picks"]

        assert exit_info.value.code == 1
        assert isinstance(picks, list)
        assert [pick["player"] for pick in picks] == ["Player One"]
        assert state["current_overall_pick"] == 2
        sync_status = json.loads(
            (tmp_path / "data" / "draft_sync_status.json").read_text(encoding="utf-8")
        )
        assert sync_status["local_current_overall_pick"] == 2
        assert sync_status["observed_yahoo_pick"] == 3
        assert "RECORDED #1 T1 Player One (RB)" in output
        assert "Draft gap detected" in output
        assert "Remaining picks were not recorded." in output
        assert "DRAFT STATE MARKED STALE — RECOMMENDATIONS DISABLED" in output
        assert "Player Three" not in output

    def test_no_selections_leaves_state_unchanged(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """
        GIVEN: standard input containing Yahoo chat but no valid draft selections
        WHEN: synchronization is requested
        THEN: the updater reports no selections and leaves draft state unchanged
        """
        _write_workspace(tmp_path)
        original_state = _load_saved_state(tmp_path)

        monkeypatch.setattr(
            sys,
            "stdin",
            io.StringIO(
                """
                CarlCarl joined
                hello everyone
                CarlCarl left
                """
            ),
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "ff-draft-update",
                "--yahoo-chat",
                "--workspace",
                str(tmp_path),
            ],
        )

        main()

        output = capsys.readouterr().out

        assert "No Yahoo draft selections found. Draft state unchanged." in output
        assert _load_saved_state(tmp_path) == original_state

    def test_no_selections_during_active_draft_fails_without_marking_state_stale(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """
        GIVEN: an active draft and copied input containing no parseable Yahoo selections
        WHEN: Yahoo synchronization is requested
        THEN: the updater exits nonzero so analysis cannot silently continue on old state
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
        original_state = _load_saved_state(tmp_path)
        monkeypatch.setattr(sys, "stdin", io.StringIO("hello everyone"))
        monkeypatch.setattr(
            sys,
            "argv",
            ["ff-draft-update", "--yahoo-chat", "--workspace", str(tmp_path)],
        )

        with pytest.raises(SystemExit) as exit_info:
            main()

        output = capsys.readouterr().out
        assert exit_info.value.code == 1
        assert "No Yahoo draft selections were parsed for an active draft" in output
        assert "Copy a recent Yahoo draft-chat range" in output
        assert _load_saved_state(tmp_path) == original_state
        assert not (tmp_path / "data" / "draft_sync_status.json").exists()

    def test_successful_yahoo_sync_clears_stale_marker_after_catching_up(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """
        GIVEN: a prior failure observed Yahoo pick one while local state remained at pick one
        WHEN: a later successful Yahoo sync records that observed pick
        THEN: the stale marker clears because local state has advanced beyond known Yahoo evidence
        """
        _write_workspace(tmp_path)
        (tmp_path / "data" / "draft_sync_status.json").write_text(
            json.dumps(
                {
                    "draft_id": "test-draft",
                    "message": "Earlier synchronization failed.",
                    "local_current_overall_pick": 1,
                    "observed_yahoo_pick": 1,
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            sys,
            "stdin",
            io.StringIO(
                """
                1
                Chris
                P. One
                RB
                TST
                Bye 5
                """
            ),
        )
        monkeypatch.setattr(
            sys,
            "argv",
            ["ff-draft-update", "--yahoo-chat", "--workspace", str(tmp_path)],
        )

        main()

        capsys.readouterr()
        assert _load_saved_state(tmp_path)["current_overall_pick"] == 2
        assert not (tmp_path / "data" / "draft_sync_status.json").exists()

    def test_successful_but_old_overlap_does_not_clear_stale_marker(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """
        GIVEN: a prior failure observed Yahoo pick three while local state is already at pick two
        WHEN: a successful sync only verifies older pick one
        THEN: the updater remains nonzero and preserves the stale marker
        """
        _write_workspace(tmp_path)
        state = json.loads((tmp_path / "data" / "draft_state.json").read_text(encoding="utf-8"))
        state["current_overall_pick"] = 2
        state["picks"] = [
            {
                "overall": 1,
                "round": 1,
                "pick_in_round": 1,
                "team_id": 1,
                "player": "Player One",
                "position": "RB",
                "yahoo_player_id": 10001,
            }
        ]
        (tmp_path / "data" / "draft_state.json").write_text(json.dumps(state), encoding="utf-8")
        (tmp_path / "data" / "draft_sync_status.json").write_text(
            json.dumps(
                {
                    "draft_id": "test-draft",
                    "message": "Draft gap detected.",
                    "local_current_overall_pick": 2,
                    "observed_yahoo_pick": 3,
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            sys,
            "stdin",
            io.StringIO(
                """
                1
                Chris
                P. One
                RB
                TST
                Bye 5
                """
            ),
        )
        monkeypatch.setattr(
            sys,
            "argv",
            ["ff-draft-update", "--yahoo-chat", "--workspace", str(tmp_path)],
        )

        with pytest.raises(SystemExit) as exit_info:
            main()

        output = capsys.readouterr().out
        assert exit_info.value.code == 1
        assert (tmp_path / "data" / "draft_sync_status.json").exists()
        assert "DRAFT STATE STILL STALE — MORE YAHOO HISTORY IS REQUIRED" in output

    @pytest.mark.parametrize(
        "extra_args",
        [
            ["Player One"],
            ["--undo"],
        ],
    )
    def test_rejects_combined_update_modes(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        extra_args: list[str],
    ) -> None:
        """
        GIVEN: Yahoo-chat mode combined with another draft-update mode
        WHEN: the updater CLI validates the requested operation
        THEN: it rejects the incompatible arguments without modifying draft state
        """
        _write_workspace(tmp_path)
        original_state = _load_saved_state(tmp_path)

        monkeypatch.setattr(
            sys,
            "stdin",
            io.StringIO(""),
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "ff-draft-update",
                *extra_args,
                "--yahoo-chat",
                "--workspace",
                str(tmp_path),
            ],
        )

        main()

        output = capsys.readouterr().out

        assert (
            "ERROR: --yahoo-chat cannot be combined with --undo or positional player references."
        ) in output
        assert _load_saved_state(tmp_path) == original_state


class TestTerminalInput:
    """Interactive terminal input while standard input may be piped."""

    def test_piped_stdin_uses_tty(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        GIVEN: standard input is occupied by piped Yahoo draft-chat data
        WHEN: interactive player selection is requested
        THEN: the response is read from the attached terminal instead of standard input
        """
        monkeypatch.setattr(
            sys,
            "stdin",
            io.StringIO("Yahoo draft chat already consumed from stdin"),
        )

        terminal = mock_open(read_data="1\n")
        monkeypatch.setattr("builtins.open", terminal)

        response = _read_terminal_input("Select player: ")

        assert response == "1"
        terminal.assert_called_once_with(
            "/dev/tty",
            encoding="utf-8",
        )

    def test_interactive_stdin_used_directly(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        GIVEN: standard input is already attached to an interactive terminal
        WHEN: terminal input is requested
        THEN: normal interactive input is used instead of opening /dev/tty
        """
        monkeypatch.setattr(
            sys,
            "stdin",
            _InteractiveInput(),
        )
        monkeypatch.setattr(
            "builtins.input",
            lambda _prompt: "1",
        )

        response = _read_terminal_input("Select player: ")

        assert response == "1"

    def test_missing_terminal_reported(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        GIVEN: standard input is piped and no controlling terminal can be opened
        WHEN: interactive input is required
        THEN: a clear runtime error is raised
        """
        monkeypatch.setattr(
            sys,
            "stdin",
            io.StringIO("piped data"),
        )

        def fail_open(*_args: object, **_kwargs: object) -> None:
            raise OSError("No terminal")

        monkeypatch.setattr(
            "builtins.open",
            fail_open,
        )

        with pytest.raises(
            RuntimeError,
            match="Interactive player selection requires an attached terminal",
        ):
            _read_terminal_input("Select player: ")

    def test_terminal_eof_reported(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        GIVEN: piped standard input and a terminal that immediately returns EOF
        WHEN: interactive input is requested
        THEN: a clear runtime error is raised instead of returning an empty choice
        """
        monkeypatch.setattr(
            sys,
            "stdin",
            io.StringIO("piped data"),
        )

        terminal = mock_open(read_data="")
        monkeypatch.setattr(
            "builtins.open",
            terminal,
        )

        with pytest.raises(
            RuntimeError,
            match="Interactive player selection requires an attached terminal",
        ):
            _read_terminal_input("Select player: ")
