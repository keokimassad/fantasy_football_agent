"""Unit tests for reconstructing draft-domain models."""

import pytest

from fantasy_football_agent.draft.models import (
    DraftPick,
    DraftState,
    LeagueConfig,
)

pytestmark = pytest.mark.unit


def test_league_config_from_dict_reconstructs_league_settings() -> None:
    """
    GIVEN: a JSON-compatible dictionary containing league rules and scoring
    WHEN: a LeagueConfig is reconstructed from that dictionary
    THEN: every configured league setting is preserved
    """
    data = {
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

    league = LeagueConfig.from_dict(data)

    assert league == LeagueConfig(
        league_name="Test League",
        teams=10,
        draft={"type": "snake"},
        roster={
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
        flex_positions=["RB", "WR", "TE"],
        scoring={"receptions": 0.5},
    )


def test_draft_state_from_dict_reconstructs_recorded_picks() -> None:
    """
    GIVEN: serialized draft state containing a recorded Yahoo player selection
    WHEN: a DraftState is reconstructed from that dictionary
    THEN: the selection becomes a DraftPick with its persisted identity intact
    """
    data = {
        "draft_id": "mock-001",
        "session_type": "mock",
        "my_draft_slot": 4,
        "current_overall_pick": 2,
        "picks": [
            {
                "overall": 1,
                "round": 1,
                "pick_in_round": 1,
                "team_id": 1,
                "player": "Bijan Robinson",
                "position": "RB",
                "yahoo_player_id": 40055,
            }
        ],
    }

    state = DraftState.from_dict(data)

    assert state == DraftState(
        draft_id="mock-001",
        session_type="mock",
        my_draft_slot=4,
        current_overall_pick=2,
        picks=[
            DraftPick(
                overall=1,
                round=1,
                pick_in_round=1,
                team_id=1,
                player="Bijan Robinson",
                position="RB",
                yahoo_player_id=40055,
            )
        ],
    )


def test_draft_state_from_dict_defaults_missing_picks_to_empty_list() -> None:
    """
    GIVEN: serialized draft state created before any selections are recorded
    WHEN: the dictionary omits the optional picks collection
    THEN: the reconstructed draft state starts with an empty picks list
    """
    data = {
        "draft_id": "mock-001",
        "session_type": "mock",
        "my_draft_slot": 4,
        "current_overall_pick": 1,
    }

    state = DraftState.from_dict(data)

    assert state.picks == []


def test_draft_state_from_dict_accepts_legacy_pick_without_yahoo_player_id() -> None:
    """
    GIVEN: serialized draft state containing a legacy pick without a Yahoo Player ID
    WHEN: the DraftState is reconstructed
    THEN: the pick remains valid with Yahoo identity represented as None
    """
    data = {
        "draft_id": "legacy-draft",
        "session_type": "mock",
        "my_draft_slot": 4,
        "current_overall_pick": 2,
        "picks": [
            {
                "overall": 1,
                "round": 1,
                "pick_in_round": 1,
                "team_id": 1,
                "player": "Legacy Player",
                "position": "RB",
            }
        ],
    }

    state = DraftState.from_dict(data)

    assert state.picks == [
        DraftPick(
            overall=1,
            round=1,
            pick_in_round=1,
            team_id=1,
            player="Legacy Player",
            position="RB",
            yahoo_player_id=None,
        )
    ]
