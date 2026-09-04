"""Unit tests for reconciling Yahoo selections with draft state."""

from collections.abc import Callable

import pytest

from fantasy_football_agent.draft.models import (
    DraftPick,
    DraftState,
    LeagueConfig,
    Player,
)
from fantasy_football_agent.yahoo.draft_chat import (
    PotentialYahooPlayerMatchError,
    YahooDraftChatPick,
)
from fantasy_football_agent.yahoo.draft_sync import (
    YahooDraftSyncError,
    reconcile_yahoo_chat_pick,
)

pytestmark = pytest.mark.unit


def _chat_pick(
    *,
    overall: int,
    player_reference: str,
    position: str,
    team: str | None,
    drafter: str = "Other",
    bye: int | None = None,
) -> YahooDraftChatPick:
    return YahooDraftChatPick(
        overall=overall,
        drafter=drafter,
        player_reference=player_reference,
        position=position,
        team=team,
        bye=bye,
    )


class TestSuccessfulReconciliation:
    """Successful reconciliation of copied Yahoo history."""

    def test_records_expected_current_pick(
        self,
        league_config: LeagueConfig,
        make_draft_state: Callable[..., DraftState],
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: local state waiting for the same pick supplied by Yahoo
        WHEN: that Yahoo selection is reconciled
        THEN: the player is recorded and draft state advances
        """
        state = make_draft_state(current_overall_pick=5)
        player = make_player(
            name="Christian McCaffrey",
            position="RB",
            team="SF",
            bye=8,
            yahoo_player_id=30121,
        )

        result = reconcile_yahoo_chat_pick(
            state,
            league_config,
            [player],
            _chat_pick(
                overall=5,
                player_reference="C. McCaffrey",
                position="RB",
                team="SF",
                bye=8,
            ),
        )

        assert result.action == "recorded"
        assert result.pick.player == "Christian McCaffrey"
        assert state.current_overall_pick == 6

    def test_verifies_overlapping_pick(
        self,
        league_config: LeagueConfig,
        make_draft_pick: Callable[..., DraftPick],
        make_draft_state: Callable[..., DraftState],
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: Yahoo repeats a selection already stored in local draft state
        WHEN: the same player is reconciled
        THEN: the historical pick is verified without advancing state
        """
        recorded = make_draft_pick(
            overall=4,
            team_id=4,
            player="Puka Nacua",
            position="WR",
            yahoo_player_id=33393,
        )
        state = make_draft_state(
            current_overall_pick=5,
            picks=[recorded],
        )
        player = make_player(
            name="Puka Nacua",
            position="WR",
            team="LAR",
            bye=11,
            yahoo_player_id=33393,
        )

        result = reconcile_yahoo_chat_pick(
            state,
            league_config,
            [player],
            _chat_pick(
                overall=4,
                player_reference="P. Nacua",
                position="WR",
                team="LAR",
                bye=11,
            ),
        )

        assert result.action == "verified"
        assert result.pick is recorded
        assert state.current_overall_pick == 5

    def test_uses_existing_pick_for_historical_ambiguity(
        self,
        league_config: LeagueConfig,
        make_draft_pick: Callable[..., DraftPick],
        make_draft_state: Callable[..., DraftState],
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: an overlapping B. Robinson selection that is ambiguous from Yahoo alone
        WHEN: local history already identifies which Robinson was selected
        THEN: the existing Yahoo Player ID deterministically verifies the overlap
        """
        bijan = make_player(
            rank=2,
            name="Bijan Robinson",
            position="RB",
            team="ATL",
            bye=11,
            yahoo_player_id=40055,
        )
        brian = make_player(
            rank=155,
            name="Brian Robinson",
            position="RB",
            team="ATL",
            bye=11,
            yahoo_player_id=34054,
        )
        recorded = make_draft_pick(
            overall=2,
            team_id=2,
            player="Bijan Robinson",
            position="RB",
            yahoo_player_id=40055,
        )
        state = make_draft_state(
            current_overall_pick=3,
            picks=[recorded],
        )

        result = reconcile_yahoo_chat_pick(
            state,
            league_config,
            [bijan, brian],
            _chat_pick(
                overall=2,
                player_reference="B. Robinson",
                position="RB",
                team="ATL",
                bye=11,
            ),
        )

        assert result.action == "verified"
        assert result.pick is recorded

    def test_records_defense_without_team_code(
        self,
        league_config: LeagueConfig,
        make_draft_state: Callable[..., DraftState],
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: local state waiting for a Yahoo defense selection without a team-code
        WHEN: that defense is reconciled
        THEN: the defense is recorded and draft state advances normally
        """
        state = make_draft_state(
            my_draft_slot=4,
            current_overall_pick=4,
        )
        rams = make_player(
            name="Los Angeles",
            position="DEF",
            team="LAR",
            bye=11,
            yahoo_player_id=50001,
        )

        result = reconcile_yahoo_chat_pick(
            state,
            league_config,
            [rams],
            _chat_pick(
                overall=4,
                drafter="You",
                player_reference="Rams",
                position="DEF",
                team=None,
                bye=11,
            ),
        )

        assert result.action == "recorded"
        assert result.pick.player == "Los Angeles"
        assert result.pick.position == "DEF"
        assert result.pick.yahoo_player_id == 50001
        assert state.current_overall_pick == 5

    def test_plausible_typo_requires_confirmation_before_unranked_fallback(
        self,
        league_config: LeagueConfig,
        make_draft_state: Callable[..., DraftState],
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: Yahoo reports J. Bate while ranked data contains Jake Bates
        WHEN: the expected selection is reconciled
        THEN: state does not advance until a human resolves the plausible typo
        """
        state = make_draft_state(current_overall_pick=147)
        bates = make_player(
            name="Jake Bates",
            position="K",
            team="DET",
            bye=6,
            yahoo_player_id=40835,
        )

        with pytest.raises(PotentialYahooPlayerMatchError):
            reconcile_yahoo_chat_pick(
                state,
                league_config,
                [bates],
                _chat_pick(
                    overall=147,
                    player_reference="J. Bate",
                    position="K",
                    team="DET",
                    bye=6,
                ),
            )

        assert state.current_overall_pick == 147
        assert state.picks == []

    def test_records_structurally_valid_unranked_player(
        self,
        league_config: LeagueConfig,
        make_draft_state: Callable[..., DraftState],
    ) -> None:
        """
        GIVEN: Yahoo supplies the expected pick but the player is absent from rankings
        WHEN: the structurally valid selection is reconciled
        THEN: state advances with Yahoo identity evidence and no invented player ID
        """
        state = make_draft_state(current_overall_pick=147)

        result = reconcile_yahoo_chat_pick(
            state,
            league_config,
            [],
            _chat_pick(
                overall=147,
                player_reference="S. Shrader",
                position="K",
                team="IND",
                bye=13,
            ),
        )

        assert result.action == "recorded"
        assert result.pick.player == "S. Shrader"
        assert result.pick.position == "K"
        assert result.pick.nfl_team == "IND"
        assert result.pick.yahoo_player_id is None
        assert state.current_overall_pick == 148

    def test_verifies_overlapping_ranked_player_through_plausible_typo(
        self,
        league_config: LeagueConfig,
        make_draft_state: Callable[..., DraftState],
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: local history contains Jake Bates and Yahoo later repeats that pick as J. Bate
        WHEN: the historical selection is reconciled
        THEN: the plausible typo verifies only the existing identity and does not advance state
        """
        bates = make_player(
            name="Jake Bates",
            position="K",
            team="DET",
            bye=6,
            yahoo_player_id=40835,
        )
        recorded = DraftPick(
            overall=147,
            round=15,
            pick_in_round=7,
            team_id=7,
            player=bates.name,
            position=bates.position,
            yahoo_player_id=bates.yahoo_player_id,
        )
        state = make_draft_state(
            current_overall_pick=148,
            picks=[recorded],
        )

        result = reconcile_yahoo_chat_pick(
            state,
            league_config,
            [bates],
            _chat_pick(
                overall=147,
                player_reference="J. Bate",
                position="K",
                team="DET",
                bye=6,
            ),
        )

        assert result.action == "verified"
        assert result.pick is recorded
        assert state.current_overall_pick == 148
        assert state.picks == [recorded]

    def test_verifies_overlapping_unranked_player(
        self,
        league_config: LeagueConfig,
        make_draft_state: Callable[..., DraftState],
    ) -> None:
        """
        GIVEN: a previously recorded unranked Yahoo selection appears in a later paste
        WHEN: the overlapping selection has the same Yahoo identity evidence
        THEN: it is verified without requiring ranked-player data
        """
        recorded = DraftPick(
            overall=147,
            round=15,
            pick_in_round=7,
            team_id=7,
            player="S. Shrader",
            position="K",
            yahoo_player_id=None,
            nfl_team="IND",
        )
        state = make_draft_state(
            current_overall_pick=148,
            picks=[recorded],
        )

        result = reconcile_yahoo_chat_pick(
            state,
            league_config,
            [],
            _chat_pick(
                overall=147,
                player_reference="S. Shrader",
                position="K",
                team="IND",
                bye=13,
            ),
        )

        assert result.action == "verified"
        assert result.pick is recorded
        assert state.current_overall_pick == 148


class TestReconciliationErrors:
    """Yahoo-history conditions that must stop reconciliation."""

    def test_rejects_gap(
        self,
        league_config: LeagueConfig,
        make_draft_state: Callable[..., DraftState],
    ) -> None:
        """
        GIVEN: local state waiting for pick five
        WHEN: the next Yahoo selection supplied is pick seven
        THEN: synchronization stops rather than skipping missing picks
        """
        state = make_draft_state(current_overall_pick=5)

        with pytest.raises(
            YahooDraftSyncError,
            match="Draft gap detected",
        ):
            reconcile_yahoo_chat_pick(
                state,
                league_config,
                [],
                _chat_pick(
                    overall=7,
                    player_reference="Test Player",
                    position="RB",
                    team="TST",
                ),
            )

        assert state.current_overall_pick == 5

    def test_rejects_conflicting_overlap(
        self,
        league_config: LeagueConfig,
        make_draft_pick: Callable[..., DraftPick],
        make_draft_state: Callable[..., DraftState],
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: local and Yahoo histories disagree about an already-recorded selection
        WHEN: the Yahoo selection is reconciled
        THEN: synchronization reports the conflict without changing state
        """
        recorded = make_draft_pick(
            overall=4,
            team_id=4,
            player="Puka Nacua",
            position="WR",
            yahoo_player_id=33393,
        )
        state = make_draft_state(
            current_overall_pick=5,
            picks=[recorded],
        )
        other_player = make_player(
            name="Ja'Marr Chase",
            position="WR",
            team="CIN",
            bye=6,
            yahoo_player_id=40001,
        )

        with pytest.raises(
            YahooDraftSyncError,
            match="conflicts with local state",
        ):
            reconcile_yahoo_chat_pick(
                state,
                league_config,
                [other_player],
                _chat_pick(
                    overall=4,
                    player_reference="J. Chase",
                    position="WR",
                    team="CIN",
                    bye=6,
                ),
            )

        assert state.current_overall_pick == 5

    def test_rejects_conflicting_unranked_overlap(
        self,
        league_config: LeagueConfig,
        make_draft_state: Callable[..., DraftState],
    ) -> None:
        """
        GIVEN: local history contains an unranked Yahoo selection
        WHEN: later Yahoo evidence reports a different player for that pick
        THEN: synchronization still fails closed on the historical conflict
        """
        recorded = DraftPick(
            overall=147,
            round=15,
            pick_in_round=7,
            team_id=7,
            player="S. Shrader",
            position="K",
            yahoo_player_id=None,
            nfl_team="IND",
        )
        state = make_draft_state(
            current_overall_pick=148,
            picks=[recorded],
        )

        with pytest.raises(
            YahooDraftSyncError,
            match="conflicts with local state",
        ):
            reconcile_yahoo_chat_pick(
                state,
                league_config,
                [],
                _chat_pick(
                    overall=147,
                    player_reference="H. Mevis",
                    position="K",
                    team="CAR",
                ),
            )

        assert state.current_overall_pick == 148

    def test_does_not_treat_duplicate_ranked_player_as_unranked(
        self,
        league_config: LeagueConfig,
        make_draft_pick: Callable[..., DraftPick],
        make_draft_state: Callable[..., DraftState],
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: Yahoo repeats a ranked player already selected at an earlier pick
        WHEN: the duplicate appears as the expected new selection
        THEN: duplicate detection stops sync instead of using the unranked fallback
        """
        player = make_player(
            name="Malik Nabers",
            position="WR",
            team="NYG",
            yahoo_player_id=10024,
        )
        recorded = make_draft_pick(
            overall=1,
            team_id=1,
            player=player.name,
            position=player.position,
            yahoo_player_id=player.yahoo_player_id,
        )
        state = make_draft_state(
            current_overall_pick=2,
            picks=[recorded],
        )

        with pytest.raises(
            ValueError,
            match="have already been drafted",
        ):
            reconcile_yahoo_chat_pick(
                state,
                league_config,
                [player],
                _chat_pick(
                    overall=2,
                    player_reference="M. Nabers",
                    position="WR",
                    team="NYG",
                ),
            )

        assert state.current_overall_pick == 2

    def test_rejects_you_pick_owned_by_other_slot(
        self,
        league_config: LeagueConfig,
        make_draft_state: Callable[..., DraftState],
    ) -> None:
        """
        GIVEN: a mock configured for slot four
        WHEN: Yahoo marks another draft slot's selection as You
        THEN: synchronization reports the configured-slot mismatch
        """
        state = make_draft_state(
            my_draft_slot=4,
            current_overall_pick=1,
        )

        with pytest.raises(
            YahooDraftSyncError,
            match="does not own that pick",
        ):
            reconcile_yahoo_chat_pick(
                state,
                league_config,
                [],
                _chat_pick(
                    overall=1,
                    drafter="You",
                    player_reference="Test Player",
                    position="RB",
                    team="TST",
                ),
            )
