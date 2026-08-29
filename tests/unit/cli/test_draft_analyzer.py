"""Unit tests for the draft-analysis command-line interface."""

import json
import sys
from pathlib import Path

import pytest

from fantasy_football_agent.cli.draft_analyzer import main

pytestmark = pytest.mark.unit


def _write_workspace(
    workspace: Path,
    *,
    state: dict[str, object],
    ranking_rows: list[str],
) -> None:
    """Write the minimum application workspace required by the analyzer CLI."""
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

    (workspace / "config" / "league.json").write_text(
        json.dumps(league),
        encoding="utf-8",
    )
    (workspace / "data" / "draft_state.json").write_text(
        json.dumps(state),
        encoding="utf-8",
    )

    header = "Rank,ADP,Player Name,Position,Team,Bye,% Drafted,Yahoo Player ID,Manual - Tier"
    rankings = "\n".join([header, *ranking_rows]) + "\n"
    (workspace / "data" / "yahoo_rankings_2026.csv").write_text(
        rankings,
        encoding="utf-8",
    )


def test_main_reports_waiting_draft_context_from_explicit_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    GIVEN: a workspace where draft slot four is waiting at overall pick five
    WHEN: the analyzer CLI runs with that workspace
    THEN: the report shows decision preparation, availability, and upcoming opponent context
    """
    _write_workspace(
        tmp_path,
        state={
            "draft_id": "mock-001",
            "session_type": "mock",
            "my_draft_slot": 4,
            "current_overall_pick": 5,
            "picks": [],
        },
        ranking_rows=[
            "1,1.5,Top Running Back,RB,RB1,5,99%,10001,1",
            "2,8.0,Later Running Back,RB,RB2,7,85%,10002,3",
            "3,12.0,Top Quarterback,QB,QB1,9,75%,10003,1",
        ],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["ff-draft", "--workspace", str(tmp_path)],
    )

    main()

    output = capsys.readouterr().out
    assert "=== Fantasy Draft Assistant ===" in output
    assert "League: Test League" in output
    assert "Current overall pick: 5" in output
    assert "Team currently drafting: 5" in output

    assert "Decision prep shortlist for pick #17:" in output
    assert "Availability risk" in output
    assert "VALUE_IF_AVAILABLE_AT_DECISION" in output
    assert "PRE_DECISION_POSITION_PRESSURE" in output
    assert "Deterministic shortlist:" not in output

    assert "My roster:" in output
    assert "No players drafted yet." in output

    assert "Top available players:" in output
    assert "Top Running Back" in output
    assert "Later Running Back" in output
    assert "Top Quarterback" in output

    assert "Tier scarcity summary:" in output
    assert "Tier coverage:" in output

    assert "Active lookahead:" in output
    assert "Current pick: #5" in output
    assert "My next pick: #17" in output
    assert "Selections before my pick: 12" in output

    assert "Opponent lookahead:" in output
    assert "Position exposure before my next pick:" in output


def test_main_reports_on_clock_turn_with_empty_lookahead_and_untiered_player(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    GIVEN: draft slot ten is on the clock at the first-round snake turn
    WHEN: the analyzer CLI runs with untiered optional ranking data
    THEN: the report shows an on-clock recommendation and no opponent picks
    before the following turn
    """
    _write_workspace(
        tmp_path,
        state={
            "draft_id": "mock-turn",
            "session_type": "mock",
            "my_draft_slot": 10,
            "current_overall_pick": 10,
            "picks": [
                {
                    "overall": 1,
                    "round": 1,
                    "pick_in_round": 1,
                    "team_id": 10,
                    "player": "My Wide Receiver",
                    "position": "WR",
                    "yahoo_player_id": 20001,
                }
            ],
        },
        ranking_rows=[
            "1,,Untiered Player,TE,TE1,8,,20002,",
        ],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["ff-draft", "--workspace", str(tmp_path)],
    )

    main()

    output = capsys.readouterr().out
    assert "=== Fantasy Draft Assistant ===" in output
    assert "League: Test League" in output
    assert "Current overall pick: 10" in output
    assert "Team currently drafting: 10" in output

    assert "Deterministic shortlist:" in output
    assert "Decision prep shortlist" not in output
    assert "Desirability" in output
    assert "Urgency" in output
    assert "Return risk" in output
    assert "1. Untiered Player | TE T-" in output
    assert "Return risk MEDIUM" in output

    assert "My roster:" in output
    assert "WR: My Wide Receiver (Pick 1)" in output

    assert "Top available players:" in output
    assert "Untiered Player" in output

    assert "Tier scarcity summary:" in output
    assert "No manual tiers assigned yet." in output
    assert "Tier coverage:" in output
    assert "TE: 0/1 players tiered" in output

    assert "Active lookahead:" in output
    assert "I am currently on the clock at #10." in output
    assert "My following pick: #11" in output
    assert "Opponent selections if I wait: 0" in output

    assert "Opponent lookahead:" in output
    assert "No opponent selections in the active lookahead window." in output

    assert "Position exposure if I wait until my following pick:" in output
    assert "Selection chances: 0" in output


def test_main_stops_after_final_overall_pick(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    GIVEN: a ten-team fifteen-round draft has advanced beyond pick one hundred fifty
    WHEN: the analyzer runs
    THEN: it reports draft completion without inventing another shortlist or future user pick
    """
    _write_workspace(
        tmp_path,
        state={
            "draft_id": "mock-complete",
            "session_type": "mock",
            "my_draft_slot": 8,
            "current_overall_pick": 151,
            "picks": [],
        },
        ranking_rows=[],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["ff-draft", "--workspace", str(tmp_path)],
    )

    main()

    output = capsys.readouterr().out
    assert "Current overall pick: 151" in output
    assert "Draft complete after #150." in output
    assert "Deterministic shortlist:" not in output
    assert "Decision prep shortlist" not in output
    assert "#153" not in output
