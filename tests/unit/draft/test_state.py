"""Unit tests for deterministic draft-state behavior."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from fantasy_football_agent.draft.models import DraftPick, DraftState, LeagueConfig
from fantasy_football_agent.draft.state import (
    get_active_lookahead_window,
    get_all_team_open_starter_slots,
    get_all_team_position_counts,
    get_draftable_roster_size,
    get_next_pick_for_team,
    get_team_context_for_picks,
    get_team_open_starter_slots,
    get_team_optional_draft_capacity,
    get_team_position_counts,
    get_team_roster,
    get_total_draft_picks,
    is_draft_complete,
    load_draft_state,
    load_league_config,
    team_for_overall_pick,
    validate_draft_state,
    validate_league_config,
)

pytestmark = pytest.mark.unit


class TestStateLoading:
    """Loading persisted league and draft state."""

    def test_reads_valid_league_json(self, tmp_path: Path) -> None:
        """
        GIVEN: a JSON file containing a supported league configuration
        WHEN: the league configuration is loaded
        THEN: the normalized league settings are returned
        """
        config_path = tmp_path / "league.json"
        config_path.write_text(
            json.dumps(
                {
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
                    "scoring": {},
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
            ),
            encoding="utf-8",
        )

        league = load_league_config(config_path)

        assert league.league_name == "Test League"
        assert league.teams == 10
        assert league.draft["type"] == "snake"
        assert league.roster["FLEX"] == 1

    def test_reconstructs_recorded_picks(self, tmp_path: Path) -> None:
        """
        GIVEN: persisted draft state containing a recorded player selection
        WHEN: the draft state is loaded
        THEN: the selection is reconstructed as a DraftPick
        """
        state_path = tmp_path / "draft_state.json"
        state_path.write_text(
            json.dumps(
                {
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
                            "player": "Test Runner",
                            "position": "RB",
                            "yahoo_player_id": 12345,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        state = load_draft_state(state_path)

        assert state.draft_id == "mock-001"
        assert state.current_overall_pick == 2
        assert len(state.picks) == 1
        assert isinstance(state.picks[0], DraftPick)
        assert state.picks[0].player == "Test Runner"
        assert state.picks[0].yahoo_player_id == 12345


class TestLeagueConfigValidation:
    """League configuration validation."""

    def test_accepts_supported_snake_draft(
        self,
        league_config: LeagueConfig,
    ) -> None:
        """
        GIVEN: a league with at least two teams and a snake draft
        WHEN: the league configuration is validated
        THEN: validation completes without an error
        """
        validate_league_config(league_config)

    def test_rejects_fewer_than_two_teams(
        self,
        make_league_config: Callable[..., LeagueConfig],
    ) -> None:
        """
        GIVEN: a league configured with only one team
        WHEN: the league configuration is validated
        THEN: validation rejects the unsupported team count
        """
        league = make_league_config(teams=1)

        with pytest.raises(ValueError, match="at least two teams"):
            validate_league_config(league)

    def test_rejects_non_snake_draft(
        self,
        make_league_config: Callable[..., LeagueConfig],
    ) -> None:
        """
        GIVEN: a league configured with an unsupported draft type
        WHEN: the league configuration is validated
        THEN: validation identifies the unsupported draft type
        """
        league = make_league_config(draft_type="auction")

        with pytest.raises(ValueError, match="Unsupported draft type: auction"):
            validate_league_config(league)


class TestDraftStateValidation:
    """Draft-state validation."""

    def test_accepts_valid_mock_session(
        self,
        league_config: LeagueConfig,
        draft_state: DraftState,
    ) -> None:
        """
        GIVEN: a valid mock session whose draft slot is inside the league
        WHEN: the draft state is validated
        THEN: validation completes without an error
        """
        validate_draft_state(draft_state, league_config)

    def test_rejects_unknown_session_type(
        self,
        league_config: LeagueConfig,
        make_draft_state: Callable[..., DraftState],
    ) -> None:
        """
        GIVEN: draft state with an unsupported session type
        WHEN: the draft state is validated
        THEN: validation rejects the session type
        """
        state = make_draft_state(session_type="practice")

        with pytest.raises(ValueError, match="Unsupported session type: practice"):
            validate_draft_state(state, league_config)

    @pytest.mark.parametrize("draft_slot", [0, 11])
    def test_rejects_slot_outside_league(
        self,
        draft_slot: int,
        league_config: LeagueConfig,
        make_draft_state: Callable[..., DraftState],
    ) -> None:
        """
        GIVEN: a 10-team league and a draft slot outside slots 1 through 10
        WHEN: the draft state is validated
        THEN: validation rejects the draft slot
        """
        state = make_draft_state(my_draft_slot=draft_slot)

        with pytest.raises(ValueError, match="Draft slot must be between 1 and 10"):
            validate_draft_state(state, league_config)

    def test_rejects_pick_before_draft_start(
        self,
        league_config: LeagueConfig,
        make_draft_state: Callable[..., DraftState],
    ) -> None:
        """
        GIVEN: draft state whose current overall pick is zero
        WHEN: the draft state is validated
        THEN: validation rejects the impossible overall pick
        """
        state = make_draft_state(current_overall_pick=0)

        with pytest.raises(ValueError, match="Current overall pick must be at least 1"):
            validate_draft_state(state, league_config)


class TestSnakeDraftOrder:
    """Snake-draft team order by overall pick."""

    def test_first_round_uses_forward_order(self) -> None:
        """
        GIVEN: a 10-team snake draft
        WHEN: overall picks 1 and 10 are resolved
        THEN: the picks belong to draft slots 1 and 10 respectively
        """
        assert team_for_overall_pick(1, 10) == 1
        assert team_for_overall_pick(10, 10) == 10

    def test_even_round_reverses_order(self) -> None:
        """
        GIVEN: a 10-team snake draft
        WHEN: overall pick 11 is resolved
        THEN: the pick belongs to draft slot 10
        """
        assert team_for_overall_pick(11, 10) == 10

    def test_third_round_returns_forward(self) -> None:
        """
        GIVEN: a 10-team snake draft after the second-round turn
        WHEN: overall pick 21 is resolved
        THEN: the pick belongs to draft slot 1
        """
        assert team_for_overall_pick(21, 10) == 1

    def test_rejects_pick_below_one(self) -> None:
        """
        GIVEN: an overall pick before the draft begins
        WHEN: the owning team is resolved
        THEN: the invalid pick is rejected
        """
        with pytest.raises(ValueError, match="Overall pick must be at least 1"):
            team_for_overall_pick(0, 10)


class TestRosterAccounting:
    """Roster and position-count accounting."""

    def test_team_roster_filters_and_preserves_order(
        self,
        make_draft_pick: Callable[..., DraftPick],
        make_draft_state: Callable[..., DraftState],
    ) -> None:
        """
        GIVEN: recorded selections belonging to several teams
        WHEN: one team's roster is requested
        THEN: only that team's selections are returned in recorded draft order
        """
        state = make_draft_state(
            picks=[
                make_draft_pick(overall=1, team_id=1, position="RB", player="First RB"),
                make_draft_pick(overall=2, team_id=2, position="WR", player="Other WR"),
                make_draft_pick(overall=20, team_id=1, position="WR", player="Second WR"),
            ]
        )

        roster = get_team_roster(state, team_id=1)

        assert [pick.player for pick in roster] == ["First RB", "Second WR"]

    def test_position_counts_drafted_positions(
        self,
        make_draft_pick: Callable[..., DraftPick],
        make_draft_state: Callable[..., DraftState],
    ) -> None:
        """
        GIVEN: a team with two running backs and one wide receiver
        WHEN: its drafted positions are counted
        THEN: the counts reflect each recorded position
        """
        state = make_draft_state(
            picks=[
                make_draft_pick(overall=1, team_id=1, position="RB"),
                make_draft_pick(overall=20, team_id=1, position="RB"),
                make_draft_pick(overall=21, team_id=1, position="WR"),
                make_draft_pick(overall=2, team_id=2, position="QB"),
            ]
        )

        counts = get_team_position_counts(state, team_id=1)

        assert counts == {"RB": 2, "WR": 1}

    def test_all_team_counts_include_empty_teams(
        self,
        league_config: LeagueConfig,
        make_draft_pick: Callable[..., DraftPick],
        make_draft_state: Callable[..., DraftState],
    ) -> None:
        """
        GIVEN: a 10-team league where only the first team has drafted
        WHEN: position counts are requested for every team
        THEN: all 10 teams are represented and undrafted teams have empty counts
        """
        state = make_draft_state(picks=[make_draft_pick(overall=1, team_id=1, position="RB")])

        counts = get_all_team_position_counts(state, league_config)

        assert len(counts) == 10
        assert counts[1] == {"RB": 1}
        assert counts[10] == {}


class TestDraftCapacity:
    """Draftable roster size and optional-selection capacity."""

    def test_draftable_roster_size_excludes_ir(
        self,
        league_config: LeagueConfig,
    ) -> None:
        """
        GIVEN: the league has fifteen normal draft slots and two IR slots
        WHEN: draft capacity is calculated
        THEN: IR is excluded and the ten-team draft ends at overall pick one hundred fifty
        """
        assert get_draftable_roster_size(league_config) == 15
        assert get_total_draft_picks(league_config) == 150

    def test_draft_complete_only_after_final_pick(
        self,
        league_config: LeagueConfig,
        make_draft_state: Callable[..., DraftState],
    ) -> None:
        """
        GIVEN: a ten-team draft whose final configured selection is overall pick one hundred fifty
        WHEN: completion is checked at the final pick and immediately after it
        THEN: the final pick is still active and pick one hundred fifty-one is complete
        """
        final_pick = make_draft_state(current_overall_pick=150)
        after_final_pick = make_draft_state(current_overall_pick=151)

        assert is_draft_complete(final_pick, league_config) is False
        assert is_draft_complete(after_final_pick, league_config) is True

    def test_one_optional_pick_remains_before_final_required_slots(
        self,
        league_config: LeagueConfig,
        make_draft_pick: Callable[..., DraftPick],
        make_draft_state: Callable[..., DraftState],
    ) -> None:
        """
        GIVEN: team eight has twelve players with only kicker and defense starters open
        WHEN: remaining optional draft capacity is calculated before pick one hundred twenty-eight
        THEN: one more depth selection is still feasible before kicker and defense become mandatory
        """
        overalls = [8, 13, 28, 33, 48, 53, 68, 73, 88, 93, 108, 113]
        positions = [
            "WR",
            "RB",
            "TE",
            "WR",
            "RB",
            "QB",
            "WR",
            "WR",
            "RB",
            "RB",
            "WR",
            "RB",
        ]
        state = make_draft_state(
            my_draft_slot=8,
            current_overall_pick=128,
            picks=[
                make_draft_pick(
                    overall=overall,
                    team_id=8,
                    position=position,
                )
                for overall, position in zip(overalls, positions, strict=True)
            ],
        )

        assert get_team_optional_draft_capacity(state, league_config, 8) == 1


class TestOpenStarterSlots:
    """Starter and FLEX slot accounting."""

    def test_empty_team_returns_full_lineup(
        self,
        league_config: LeagueConfig,
        draft_state: DraftState,
    ) -> None:
        """
        GIVEN: a team that has not drafted any players
        WHEN: its open starting slots are calculated
        THEN: every configured starter and FLEX slot remains open
        """
        slots = get_team_open_starter_slots(draft_state, league_config, team_id=1)

        assert slots == {
            "QB": 1,
            "WR": 2,
            "RB": 2,
            "TE": 1,
            "K": 1,
            "DEF": 1,
            "FLEX": 1,
        }
        assert "BENCH" not in slots
        assert "IR" not in slots

    def test_dedicated_slot_filled_before_flex(
        self,
        league_config: LeagueConfig,
        make_draft_pick: Callable[..., DraftPick],
        make_draft_state: Callable[..., DraftState],
    ) -> None:
        """
        GIVEN: a team with one running back and two required RB starter slots
        WHEN: its open starting slots are calculated
        THEN: one RB slot closes while FLEX remains open
        """
        state = make_draft_state(picks=[make_draft_pick(overall=1, team_id=1, position="RB")])

        slots = get_team_open_starter_slots(state, league_config, team_id=1)

        assert slots["RB"] == 1
        assert slots["FLEX"] == 1

    def test_eligible_overflow_fills_flex(
        self,
        league_config: LeagueConfig,
        make_draft_pick: Callable[..., DraftPick],
        make_draft_state: Callable[..., DraftState],
    ) -> None:
        """
        GIVEN: a team with three running backs, two dedicated RB slots, and one FLEX
        WHEN: its open starting slots are calculated
        THEN: the third running back fills FLEX after both RB slots are filled
        """
        state = make_draft_state(
            picks=[
                make_draft_pick(overall=1, team_id=1, position="RB"),
                make_draft_pick(overall=20, team_id=1, position="RB"),
                make_draft_pick(overall=21, team_id=1, position="RB"),
            ]
        )

        slots = get_team_open_starter_slots(state, league_config, team_id=1)

        assert slots["RB"] == 0
        assert slots["FLEX"] == 0

    def test_qb_overflow_cannot_fill_flex(
        self,
        league_config: LeagueConfig,
        make_draft_pick: Callable[..., DraftPick],
        make_draft_state: Callable[..., DraftState],
    ) -> None:
        """
        GIVEN: a team with two quarterbacks and a FLEX limited to RB, WR, and TE
        WHEN: its open starting slots are calculated
        THEN: the extra quarterback does not consume the FLEX slot
        """
        state = make_draft_state(
            picks=[
                make_draft_pick(overall=1, team_id=1, position="QB"),
                make_draft_pick(overall=20, team_id=1, position="QB"),
            ]
        )

        slots = get_team_open_starter_slots(state, league_config, team_id=1)

        assert slots["QB"] == 0
        assert slots["FLEX"] == 1

    def test_slots_never_negative(
        self,
        league_config: LeagueConfig,
        make_draft_pick: Callable[..., DraftPick],
        make_draft_state: Callable[..., DraftState],
    ) -> None:
        """
        GIVEN: a team with more FLEX-eligible players than its starter lineup can hold
        WHEN: its open starting slots are calculated
        THEN: dedicated and FLEX availability stop at zero
        """
        state = make_draft_state(
            picks=[
                make_draft_pick(overall=1, team_id=1, position="RB"),
                make_draft_pick(overall=20, team_id=1, position="RB"),
                make_draft_pick(overall=21, team_id=1, position="RB"),
                make_draft_pick(overall=40, team_id=1, position="RB"),
            ]
        )

        slots = get_team_open_starter_slots(state, league_config, team_id=1)

        assert slots["RB"] == 0
        assert slots["FLEX"] == 0

    def test_no_flex_league_omits_flex(
        self,
        league_config: LeagueConfig,
        draft_state: DraftState,
    ) -> None:
        """
        GIVEN: a league configured without a FLEX starter slot
        WHEN: a team's open starting slots are calculated
        THEN: FLEX is not included in the open starter slots
        """
        league_config.roster["FLEX"] = 0

        slots = get_team_open_starter_slots(
            draft_state,
            league_config,
            team_id=1,
        )

        assert "FLEX" not in slots

    def test_all_team_slots_include_every_team(
        self,
        league_config: LeagueConfig,
        make_draft_pick: Callable[..., DraftPick],
        make_draft_state: Callable[..., DraftState],
    ) -> None:
        """
        GIVEN: a 10-team league where team 1 has drafted a running back
        WHEN: open starting slots are calculated for the league
        THEN: all teams are included and only team 1 reflects that selection
        """
        state = make_draft_state(picks=[make_draft_pick(overall=1, team_id=1, position="RB")])

        slots = get_all_team_open_starter_slots(state, league_config)

        assert len(slots) == 10
        assert slots[1]["RB"] == 1
        assert slots[2]["RB"] == 2


class TestNextPickLookup:
    """Finding a team's next selection in snake order."""

    def test_can_include_current_pick(self) -> None:
        """
        GIVEN: draft slot 4 is currently on the clock at overall pick 17
        WHEN: its next pick is requested with the current pick included
        THEN: overall pick 17 is returned
        """
        assert get_next_pick_for_team(17, team_id=4, teams=10, include_current=True) == 17

    def test_can_skip_current_pick(self) -> None:
        """
        GIVEN: draft slot 4 is currently on the clock at overall pick 17
        WHEN: its next pick is requested without the current pick
        THEN: its following selection at overall pick 24 is returned
        """
        assert get_next_pick_for_team(17, team_id=4, teams=10, include_current=False) == 24

    def test_handles_consecutive_turn_picks(self) -> None:
        """
        GIVEN: draft slot 10 owns the final pick of round one at overall pick 10
        WHEN: its following pick is requested
        THEN: the snake turn returns its consecutive selection at overall pick 11
        """
        assert get_next_pick_for_team(10, team_id=10, teams=10, include_current=False) == 11

    def test_can_bound_search_at_draft_endpoint(self) -> None:
        """
        GIVEN: team one has completed its fifteenth selection in a 150-pick draft
        WHEN: its next snake turn is searched within the configured draft boundary
        THEN: no fictional pick one hundred sixty is returned
        """
        assert get_next_pick_for_team(142, team_id=1, teams=10, max_overall_pick=150) is None

    @pytest.mark.parametrize("team_id", [0, 11])
    def test_rejects_team_outside_league(self, team_id: int) -> None:
        """
        GIVEN: a 10-team draft and a team ID outside slots 1 through 10
        WHEN: the team's next pick is requested
        THEN: the invalid team ID is rejected
        """
        with pytest.raises(ValueError, match="Team ID must be between 1 and 10"):
            get_next_pick_for_team(5, team_id=team_id, teams=10)


class TestActiveLookaheadWindow:
    """Opponent selections before the user's next decision."""

    def test_waiting_includes_current_opponent_pick(
        self,
        league_config: LeagueConfig,
        make_draft_state: Callable[..., DraftState],
    ) -> None:
        """
        GIVEN: draft slot 4 is waiting while team 5 is on the clock at overall pick 5
        WHEN: the active lookahead window is calculated
        THEN: picks 5 through 16 are included before draft slot 4 picks at 17
        """
        state = make_draft_state(my_draft_slot=4, current_overall_pick=5)

        window_start, target_pick, picks = get_active_lookahead_window(
            state,
            league_config,
        )

        assert window_start == 5
        assert target_pick == 17
        assert [overall for overall, _ in picks] == list(range(5, 17))
        assert [team_id for _, team_id in picks] == [5, 6, 7, 8, 9, 10, 10, 9, 8, 7, 6, 5]

    def test_on_clock_starts_after_current_pick(
        self,
        league_config: LeagueConfig,
        make_draft_state: Callable[..., DraftState],
    ) -> None:
        """
        GIVEN: draft slot 4 is on the clock at overall pick 17
        WHEN: the active lookahead window is calculated
        THEN: opponent picks 18 through 23 are included before slot 4 picks again at 24
        """
        state = make_draft_state(my_draft_slot=4, current_overall_pick=17)

        window_start, target_pick, picks = get_active_lookahead_window(
            state,
            league_config,
        )

        assert window_start == 18
        assert target_pick == 24
        assert [overall for overall, _ in picks] == list(range(18, 24))
        assert [team_id for _, team_id in picks] == [3, 2, 1, 1, 2, 3]

    def test_waiting_after_final_user_pick_stops_at_draft_endpoint(
        self,
        league_config: LeagueConfig,
        make_draft_state: Callable[..., DraftState],
    ) -> None:
        """
        GIVEN: draft slot one has made its final selection and pick one hundred forty-two is active
        WHEN: the remaining lookahead window is calculated
        THEN: no future user pick is invented and only picks through one hundred fifty remain
        """
        state = make_draft_state(my_draft_slot=1, current_overall_pick=142)

        window_start, target_pick, picks = get_active_lookahead_window(state, league_config)

        assert window_start == 142
        assert target_pick is None
        assert [overall for overall, _ in picks] == list(range(142, 151))

    def test_final_user_pick_has_no_following_pick(
        self,
        league_config: LeagueConfig,
        make_draft_state: Callable[..., DraftState],
    ) -> None:
        """
        GIVEN: draft slot one is on the clock for its final selection at pick one hundred forty-one
        WHEN: the active lookahead window is calculated
        THEN: the remaining opponent picks stop at one hundred fifty without a fictional next turn
        """
        state = make_draft_state(my_draft_slot=1, current_overall_pick=141)

        window_start, target_pick, picks = get_active_lookahead_window(state, league_config)

        assert window_start == 142
        assert target_pick is None
        assert [overall for overall, _ in picks] == list(range(142, 151))

    def test_consecutive_turn_has_empty_window(
        self,
        league_config: LeagueConfig,
        make_draft_state: Callable[..., DraftState],
    ) -> None:
        """
        GIVEN: draft slot 10 is on the clock at overall pick 10 before the snake turn
        WHEN: the active lookahead window is calculated
        THEN: there are no opponent selections before slot 10 picks again at 11
        """
        state = make_draft_state(my_draft_slot=10, current_overall_pick=10)

        window_start, target_pick, picks = get_active_lookahead_window(
            state,
            league_config,
        )

        assert window_start == 11
        assert target_pick == 11
        assert picks == []


class TestTeamContextForPicks:
    """Roster-need snapshots for teams in a pick window."""

    def test_groups_multiple_picks_by_team(
        self,
        league_config: LeagueConfig,
        draft_state: DraftState,
    ) -> None:
        """
        GIVEN: a lookahead window where teams 5 and 6 each select twice
        WHEN: per-team lookahead context is built
        THEN: each team contains its pick count and overall pick numbers in order
        """
        picks = [(5, 5), (6, 6), (15, 6), (16, 5)]

        context = get_team_context_for_picks(draft_state, league_config, picks)

        assert context[5].pick_count == 2
        assert context[5].overall_picks == [5, 16]
        assert context[6].pick_count == 2
        assert context[6].overall_picks == [6, 15]

    def test_uses_current_roster_needs_snapshot(
        self,
        league_config: LeagueConfig,
        make_draft_pick: Callable[..., DraftPick],
        make_draft_state: Callable[..., DraftState],
    ) -> None:
        """
        GIVEN: team 5 already has one running back before two lookahead selections
        WHEN: per-team lookahead context is built
        THEN: its open starter slots reflect the current roster before either future pick
        """
        state = make_draft_state(picks=[make_draft_pick(overall=4, team_id=5, position="RB")])
        picks = [(5, 5), (16, 5)]

        context = get_team_context_for_picks(state, league_config, picks)

        assert context[5].open_starter_slots["RB"] == 1
        assert context[5].open_starter_slots["FLEX"] == 1

    def test_empty_window_returns_empty_context(
        self,
        league_config: LeagueConfig,
        draft_state: DraftState,
    ) -> None:
        """
        GIVEN: an active lookahead window with no opponent selections
        WHEN: per-team lookahead context is built
        THEN: no team context is returned
        """
        context = get_team_context_for_picks(draft_state, league_config, [])

        assert context == {}
