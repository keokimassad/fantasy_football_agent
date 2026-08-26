"""Unit tests for deterministic positional exposure analysis."""

import pytest

from fantasy_football_agent.draft.analysis import get_position_exposure
from fantasy_football_agent.draft.models import (
    LeagueConfig,
    PositionExposure,
    TeamLookaheadContext,
)

pytestmark = pytest.mark.unit


class TestPositionExposure:
    """Position-demand exposure across an opponent pick window."""

    def test_empty_window_returns_zeroed_positions(
        self,
        league_config: LeagueConfig,
    ) -> None:
        """
        GIVEN: an active lookahead window with no opponent selections
        WHEN: positional exposure is calculated
        THEN: every supported position has no teams and zero selection chances
        """
        exposure = get_position_exposure(league_config, {})

        assert exposure == {
            position: PositionExposure(
                direct_need_teams=[],
                flex_only_teams=[],
                selection_chances=0,
            )
            for position in ["QB", "RB", "WR", "TE", "K", "DEF"]
        }

    def test_direct_need_counts_all_team_selections(
        self,
        league_config: LeagueConfig,
    ) -> None:
        """
        GIVEN: an opponent with an open RB starter slot and two upcoming selections
        WHEN: running-back exposure is calculated
        THEN: the team is a direct need and both selections count as exposure
        """
        context = {
            5: TeamLookaheadContext(
                pick_count=2,
                overall_picks=[5, 16],
                open_starter_slots={"RB": 1, "FLEX": 1},
            )
        }

        exposure = get_position_exposure(league_config, context)

        assert exposure["RB"] == PositionExposure(
            direct_need_teams=[5],
            flex_only_teams=[],
            selection_chances=2,
        )

    def test_flex_eligible_position_can_be_flex_only(
        self,
        league_config: LeagueConfig,
    ) -> None:
        """
        GIVEN: an opponent with no open WR slot but an open FLEX slot
        WHEN: wide-receiver exposure is calculated
        THEN: the team is classified as FLEX-only demand and its pick counts
        """
        context = {
            6: TeamLookaheadContext(
                pick_count=1,
                overall_picks=[6],
                open_starter_slots={"WR": 0, "FLEX": 1},
            )
        }

        exposure = get_position_exposure(league_config, context)

        assert exposure["WR"] == PositionExposure(
            direct_need_teams=[],
            flex_only_teams=[6],
            selection_chances=1,
        )

    def test_direct_need_precedes_flex_eligibility(
        self,
        league_config: LeagueConfig,
    ) -> None:
        """
        GIVEN: an opponent with both an open TE slot and an open FLEX slot
        WHEN: tight-end exposure is calculated
        THEN: the team is counted once as direct need rather than FLEX-only need
        """
        context = {
            7: TeamLookaheadContext(
                pick_count=2,
                overall_picks=[7, 14],
                open_starter_slots={"TE": 1, "FLEX": 1},
            )
        }

        exposure = get_position_exposure(league_config, context)

        assert exposure["TE"] == PositionExposure(
            direct_need_teams=[7],
            flex_only_teams=[],
            selection_chances=2,
        )

    def test_ineligible_position_not_counted_as_flex(
        self,
        league_config: LeagueConfig,
    ) -> None:
        """
        GIVEN: an opponent with only an open FLEX slot
        WHEN: exposure is calculated for QB, K, and DEF
        THEN: FLEX does not create demand for positions that are not FLEX-eligible
        """
        context = {
            8: TeamLookaheadContext(
                pick_count=1,
                overall_picks=[8],
                open_starter_slots={"FLEX": 1},
            )
        }

        exposure = get_position_exposure(league_config, context)

        for position in ["QB", "K", "DEF"]:
            assert exposure[position] == PositionExposure(
                direct_need_teams=[],
                flex_only_teams=[],
                selection_chances=0,
            )

    def test_team_without_need_is_ignored(
        self,
        league_config: LeagueConfig,
    ) -> None:
        """
        GIVEN: an opponent with no open RB or FLEX starter slot
        WHEN: running-back exposure is calculated
        THEN: the team and its selections are excluded from RB exposure
        """
        context = {
            9: TeamLookaheadContext(
                pick_count=2,
                overall_picks=[9, 12],
                open_starter_slots={"RB": 0, "FLEX": 0},
            )
        }

        exposure = get_position_exposure(league_config, context)

        assert exposure["RB"] == PositionExposure(
            direct_need_teams=[],
            flex_only_teams=[],
            selection_chances=0,
        )

    def test_direct_and_flex_only_teams_are_aggregated(
        self,
        league_config: LeagueConfig,
    ) -> None:
        """
        GIVEN: one team with direct WR need and two teams with FLEX-only WR need
        WHEN: wide-receiver exposure is calculated
        THEN: team classifications and selection chances are aggregated correctly
        """
        context = {
            5: TeamLookaheadContext(
                pick_count=2,
                overall_picks=[5, 16],
                open_starter_slots={"WR": 1, "FLEX": 1},
            ),
            6: TeamLookaheadContext(
                pick_count=1,
                overall_picks=[6],
                open_starter_slots={"WR": 0, "FLEX": 1},
            ),
            7: TeamLookaheadContext(
                pick_count=2,
                overall_picks=[7, 14],
                open_starter_slots={"WR": 0, "FLEX": 1},
            ),
        }

        exposure = get_position_exposure(league_config, context)

        assert exposure["WR"] == PositionExposure(
            direct_need_teams=[5],
            flex_only_teams=[6, 7],
            selection_chances=5,
        )
