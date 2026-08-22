"""Shared pytest fixtures and test-data factories."""

from collections.abc import Callable

import pytest

from fantasy_football_agent.draft.models import (
    DraftPick,
    DraftState,
    LeagueConfig,
    Player,
)


@pytest.fixture
def make_league_config() -> Callable[..., LeagueConfig]:
    """Provide a factory for league configurations that need custom values."""

    def make(
        *,
        teams: int = 10,
        draft_type: str = "snake",
    ) -> LeagueConfig:
        return LeagueConfig(
            league_name="Test League",
            teams=teams,
            draft={"type": draft_type},
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
            scoring={},
        )

    return make


@pytest.fixture
def make_draft_state() -> Callable[..., DraftState]:
    """Provide a factory for draft states that need custom values."""

    def make(
        *,
        session_type: str = "mock",
        my_draft_slot: int = 4,
        current_overall_pick: int = 5,
        picks: list[DraftPick] | None = None,
    ) -> DraftState:
        return DraftState(
            draft_id="test-draft",
            session_type=session_type,
            my_draft_slot=my_draft_slot,
            current_overall_pick=current_overall_pick,
            picks=[] if picks is None else picks,
        )

    return make


@pytest.fixture
def make_draft_pick() -> Callable[..., DraftPick]:
    """Provide a factory for recorded draft picks."""

    def make(
        *,
        overall: int,
        team_id: int,
        position: str,
        player: str | None = None,
        teams: int = 10,
        yahoo_player_id: int | None = None,
    ) -> DraftPick:
        round_number = ((overall - 1) // teams) + 1
        pick_in_round = ((overall - 1) % teams) + 1

        return DraftPick(
            overall=overall,
            round=round_number,
            pick_in_round=pick_in_round,
            team_id=team_id,
            player=player or f"Player {overall}",
            position=position,
            yahoo_player_id=(10000 + overall if yahoo_player_id is None else yahoo_player_id),
        )

    return make


@pytest.fixture
def make_player() -> Callable[..., Player]:
    """Provide a factory for ranked players used by draft tests."""

    def make(
        *,
        rank: int = 1,
        adp: float | None = 1.0,
        name: str = "Test Player",
        position: str = "RB",
        team: str = "TST",
        bye: int = 10,
        drafted_percentage: float | None = 99.0,
        yahoo_player_id: int = 10001,
        manual_tier: int | None = 1,
    ) -> Player:
        return Player(
            rank=rank,
            adp=adp,
            name=name,
            position=position,
            team=team,
            bye=bye,
            drafted_percentage=drafted_percentage,
            yahoo_player_id=yahoo_player_id,
            manual_tier=manual_tier,
        )

    return make


@pytest.fixture
def league_config(
    make_league_config: Callable[..., LeagueConfig],
) -> LeagueConfig:
    """Provide the standard 10-team snake-draft league used by most tests."""
    return make_league_config()


@pytest.fixture
def draft_state(
    make_draft_state: Callable[..., DraftState],
) -> DraftState:
    """Provide an empty mock draft state at overall pick five."""
    return make_draft_state()
