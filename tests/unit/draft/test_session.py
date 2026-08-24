"""Unit tests for draft-session state changes and persistence."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from fantasy_football_agent.draft.models import (
    DraftPick,
    DraftState,
    LeagueConfig,
    Player,
)
from fantasy_football_agent.draft.session import (
    record_current_pick,
    record_resolved_current_pick,
    resolve_player,
    save_draft_state,
    undo_last_pick,
)

pytestmark = pytest.mark.unit


def test_resolve_player_matches_yahoo_player_id(
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: rankings containing a player with a known Yahoo Player ID
    WHEN: that Yahoo Player ID is used as the player reference
    THEN: the matching ranked player is returned
    """
    player = make_player(name="Bijan Robinson", yahoo_player_id=40055)

    resolved = resolve_player([player], "40055")

    assert resolved is player


def test_resolve_player_strips_whitespace_and_matches_name_case_insensitively(
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: rankings containing Puka Nacua
    WHEN: his name is supplied with extra whitespace and different capitalization
    THEN: the matching ranked player is returned
    """
    player = make_player(name="Puka Nacua", position="WR", yahoo_player_id=33393)

    resolved = resolve_player([player], "  pUkA nAcUa  ")

    assert resolved is player


def test_resolve_player_rejects_blank_reference(
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: loaded player rankings
    WHEN: a blank player reference is supplied
    THEN: resolution rejects the reference
    """
    rankings = [make_player()]

    with pytest.raises(ValueError, match="Player reference cannot be blank"):
        resolve_player(rankings, "   ")


def test_resolve_player_rejects_unknown_yahoo_player_id(
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: rankings that do not contain Yahoo Player ID 99999
    WHEN: that Yahoo Player ID is used as the player reference
    THEN: resolution reports that the ranked player was not found
    """
    rankings = [make_player(yahoo_player_id=40055)]

    with pytest.raises(
        ValueError,
        match="No ranked player found with Yahoo Player ID 99999",
    ):
        resolve_player(rankings, "99999")


def test_resolve_player_suggests_close_name_matches(
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: rankings containing Bijan Robinson
    WHEN: a similar but misspelled player name is supplied
    THEN: the error suggests the close matching player name
    """
    rankings = [
        make_player(name="Bijan Robinson", yahoo_player_id=40055),
        make_player(
            rank=2,
            name="Jahmyr Gibbs",
            yahoo_player_id=40059,
        ),
    ]

    with pytest.raises(ValueError) as exc_info:
        resolve_player(rankings, "Bijon Robinson")

    message = str(exc_info.value)
    assert 'No ranked player found matching "Bijon Robinson"' in message
    assert "Did you mean: Bijan Robinson?" in message


def test_resolve_player_omits_suggestions_when_no_name_is_close(
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: rankings with no player name resembling the supplied reference
    WHEN: an unrelated player name is resolved
    THEN: the error does not include a suggestion
    """
    rankings = [
        make_player(name="Bijan Robinson", yahoo_player_id=40055),
        make_player(
            rank=2,
            name="Puka Nacua",
            position="WR",
            yahoo_player_id=33393,
        ),
    ]

    with pytest.raises(ValueError) as exc_info:
        resolve_player(rankings, "Completely Unknown")

    message = str(exc_info.value)
    assert message == 'No ranked player found matching "Completely Unknown".'
    assert "Did you mean:" not in message


def test_record_current_pick_records_snake_draft_metadata_and_advances_state(
    league_config: LeagueConfig,
    make_draft_state: Callable[..., DraftState],
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: a 10-team snake draft at overall pick 11 and an undrafted player
    WHEN: the current pick is recorded
    THEN: round, slot ownership, player data, and the next overall pick are updated
    """
    state = make_draft_state(current_overall_pick=11)
    player = make_player(
        name="Jahmyr Gibbs",
        position="RB",
        yahoo_player_id=40059,
    )

    recorded = record_current_pick(
        state,
        league_config,
        [player],
        "Jahmyr Gibbs",
    )

    assert recorded == DraftPick(
        overall=11,
        round=2,
        pick_in_round=1,
        team_id=10,
        player="Jahmyr Gibbs",
        position="RB",
        yahoo_player_id=40059,
    )
    assert state.picks == [recorded]
    assert state.current_overall_pick == 12


def test_record_current_pick_accepts_yahoo_player_id_reference(
    league_config: LeagueConfig,
    draft_state: DraftState,
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: an undrafted ranked player with a Yahoo Player ID
    WHEN: the player is recorded using that ID instead of a name
    THEN: the player's ranked identity is stored in the draft pick
    """
    player = make_player(
        name="Puka Nacua",
        position="WR",
        yahoo_player_id=33393,
    )

    recorded = record_current_pick(
        draft_state,
        league_config,
        [player],
        "33393",
    )

    assert recorded.player == "Puka Nacua"
    assert recorded.position == "WR"
    assert recorded.yahoo_player_id == 33393


def test_record_current_pick_rejects_player_already_drafted(
    league_config: LeagueConfig,
    make_draft_pick: Callable[..., DraftPick],
    make_draft_state: Callable[..., DraftState],
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: draft state already containing a player's Yahoo Player ID
    WHEN: the same player is recorded again
    THEN: the duplicate selection is rejected without advancing the draft
    """
    existing_pick = make_draft_pick(
        overall=1,
        team_id=1,
        position="RB",
        player="Bijan Robinson",
        yahoo_player_id=40055,
    )
    state = make_draft_state(
        current_overall_pick=2,
        picks=[existing_pick],
    )
    player = make_player(
        name="Bijan Robinson",
        yahoo_player_id=40055,
    )

    with pytest.raises(ValueError, match="Bijan Robinson has already been drafted"):
        record_current_pick(
            state,
            league_config,
            [player],
            "Bijan Robinson",
        )

    assert state.picks == [existing_pick]
    assert state.current_overall_pick == 2


def test_save_draft_state_writes_complete_human_readable_json(
    tmp_path: Path,
    make_draft_pick: Callable[..., DraftPick],
    make_draft_state: Callable[..., DraftState],
) -> None:
    """
    GIVEN: draft state containing a recorded selection
    WHEN: the state is saved to disk
    THEN: the complete state is written as indented JSON with a trailing newline
    """
    pick = make_draft_pick(
        overall=1,
        team_id=1,
        position="RB",
        player="Bijan Robinson",
        yahoo_player_id=40055,
    )
    state = make_draft_state(
        current_overall_pick=2,
        picks=[pick],
    )
    path = tmp_path / "draft_state.json"

    save_draft_state(path, state)

    text = path.read_text(encoding="utf-8")
    persisted = json.loads(text)

    assert persisted == {
        "draft_id": "test-draft",
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
    assert '\n  "picks": [' in text
    assert text.endswith("\n")


def test_undo_last_pick_removes_pick_and_restores_draft_pointer(
    make_draft_pick: Callable[..., DraftPick],
    make_draft_state: Callable[..., DraftState],
) -> None:
    """
    GIVEN: draft state containing two recorded selections
    WHEN: the most recent selection is undone
    THEN: that pick is returned, removed, and becomes the current overall pick
    """
    first_pick = make_draft_pick(
        overall=1,
        team_id=1,
        position="RB",
        player="First Player",
    )
    second_pick = make_draft_pick(
        overall=2,
        team_id=2,
        position="WR",
        player="Second Player",
    )
    state = make_draft_state(
        current_overall_pick=3,
        picks=[first_pick, second_pick],
    )

    undone = undo_last_pick(state)

    assert undone is second_pick
    assert state.picks == [first_pick]
    assert state.current_overall_pick == 2


def test_undo_last_pick_rejects_empty_draft_state(
    draft_state: DraftState,
) -> None:
    """
    GIVEN: draft state with no recorded selections
    WHEN: an undo is requested
    THEN: the operation is rejected and the draft pointer is unchanged
    """
    original_pick = draft_state.current_overall_pick

    with pytest.raises(ValueError, match="There are no draft picks to undo"):
        undo_last_pick(draft_state)

    assert draft_state.picks == []
    assert draft_state.current_overall_pick == original_pick


def test_record_resolved_current_pick_records_without_name_resolution(
    league_config: LeagueConfig,
    make_draft_state: Callable[..., DraftState],
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: a player whose identity has already been resolved by an external adapter
    WHEN: the resolved player is recorded at the current selection
    THEN: deterministic draft metadata is derived and state advances
    """
    state = make_draft_state(current_overall_pick=11)
    player = make_player(
        name="Jahmyr Gibbs",
        position="RB",
        yahoo_player_id=40059,
    )

    recorded = record_resolved_current_pick(
        state,
        league_config,
        player,
    )

    assert recorded == DraftPick(
        overall=11,
        round=2,
        pick_in_round=1,
        team_id=10,
        player="Jahmyr Gibbs",
        position="RB",
        yahoo_player_id=40059,
    )
    assert state.current_overall_pick == 12
