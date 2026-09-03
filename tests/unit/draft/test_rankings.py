"""Unit tests for ranking availability, tiers, and scarcity signals."""

from collections.abc import Callable
from pathlib import Path

import pytest

from fantasy_football_agent.draft.models import DraftPick, DraftState, Player
from fantasy_football_agent.draft.rankings import (
    get_available_players,
    get_position_tier_summary,
    get_scarcity_flags,
    get_tier_coverage,
    get_tier_players,
    is_last_in_tier,
    load_rankings,
    next_position_tier,
    remaining_in_player_tier,
)

pytestmark = pytest.mark.unit


class TestRankingLoading:
    """Ranking CSV parsing and normalization."""

    def test_parses_player_fields(self, tmp_path: Path) -> None:
        """
        GIVEN: a Yahoo rankings CSV containing populated player metadata
        WHEN: the rankings file is loaded
        THEN: each CSV field is converted to the corresponding Player value
        """
        path = tmp_path / "rankings.csv"
        path.write_text(
            (
                "Rank,ADP,Player Name,Position,Team,Bye,% Drafted,"
                "Yahoo Player ID,Manual - Tier\n"
                "1,1.7, Bijan Robinson ,RB,ATL,5,99%,40055,1\n"
            ),
            encoding="utf-8-sig",
        )

        rankings = load_rankings(path)

        assert rankings == [
            Player(
                rank=1,
                adp=1.7,
                name="Bijan Robinson",
                position="RB",
                team="ATL",
                bye=5,
                drafted_percentage=99.0,
                yahoo_player_id=40055,
                manual_tier=1,
            )
        ]

    def test_normalizes_optional_blank_and_dash_values(
        self,
        tmp_path: Path,
    ) -> None:
        """
        GIVEN: a rankings CSV using blanks and dashes for optional Yahoo fields
        WHEN: the rankings file is loaded
        THEN: missing ADP, drafted percentage, and manual tier values become None
        """
        path = tmp_path / "rankings.csv"
        path.write_text(
            (
                "Rank,ADP,Player Name,Position,Team,Bye,% Drafted,"
                "Yahoo Player ID,Manual - Tier\n"
                "1,,Player One,RB,TST,7,-,10001,\n"
                "2,-,Player Two,WR,TST,8,,10002,-\n"
            ),
            encoding="utf-8",
        )

        rankings = load_rankings(path)

        assert rankings[0].adp is None
        assert rankings[0].drafted_percentage is None
        assert rankings[0].manual_tier is None
        assert rankings[1].adp is None
        assert rankings[1].drafted_percentage is None
        assert rankings[1].manual_tier is None

    def test_applies_ignore_adp_policy_without_losing_source_value(
        self,
        tmp_path: Path,
    ) -> None:
        """
        GIVEN: source ADP is stale for a player with a local IGNORE override
        WHEN: rankings are loaded with the override file
        THEN: current decisions ignore ADP while preserving the source value for auditability
        """
        rankings_path = tmp_path / "rankings.csv"
        rankings_path.write_text(
            (
                "Rank,ADP,Player Name,Position,Team,Bye,% Drafted,"
                "Yahoo Player ID,Manual - Tier\n"
                "108,35,Josh Jacobs,RB,GB,11,100%,31856,10\n"
            ),
            encoding="utf-8",
        )
        overrides_path = tmp_path / "player_overrides.json"
        overrides_path.write_text(
            """{
  "players": [
    {
      "yahoo_player_id": 31856,
      "adp_policy": "IGNORE",
      "reason": "Source ADP predates material availability news",
      "as_of": "2026-08-31"
    }
  ]
}
""",
            encoding="utf-8",
        )

        player = load_rankings(rankings_path, overrides_path)[0]

        assert player.source_adp == 35.0
        assert player.adp is None
        assert player.adp_policy.value == "IGNORE"
        assert player.adp_override_reason == "Source ADP predates material availability news"
        assert player.adp_override_as_of == "2026-08-31"

    def test_applies_explicit_adp_override(
        self,
        tmp_path: Path,
    ) -> None:
        """
        GIVEN: an audited replacement ADP is explicitly configured
        WHEN: rankings are loaded with the override
        THEN: deterministic market calculations receive the replacement ADP
        """
        rankings_path = tmp_path / "rankings.csv"
        rankings_path.write_text(
            (
                "Rank,ADP,Player Name,Position,Team,Bye,% Drafted,"
                "Yahoo Player ID,Manual - Tier\n"
                "50,35,Player One,RB,TST,7,90%,10001,5\n"
            ),
            encoding="utf-8",
        )
        overrides_path = tmp_path / "player_overrides.json"
        overrides_path.write_text(
            """{
  "players": [
    {
      "yahoo_player_id": 10001,
      "adp_policy": "OVERRIDE",
      "adp": 70.0,
      "reason": "Audited current market correction",
      "as_of": "2026-08-31"
    }
  ]
}
""",
            encoding="utf-8",
        )

        player = load_rankings(rankings_path, overrides_path)[0]

        assert player.source_adp == 35.0
        assert player.adp == 70.0
        assert player.adp_policy.value == "OVERRIDE"

    def test_accepts_decimal_manual_tier(
        self,
        tmp_path: Path,
    ) -> None:
        """
        GIVEN: a rankings CSV where a manual tier is written as decimal text
        WHEN: the rankings file is loaded
        THEN: the tier is normalized to an integer
        """
        path = tmp_path / "rankings.csv"
        path.write_text(
            (
                "Rank,ADP,Player Name,Position,Team,Bye,% Drafted,"
                "Yahoo Player ID,Manual - Tier\n"
                "1,3.2,Player One,WR,TST,7,85.5%,10001,2.0\n"
            ),
            encoding="utf-8",
        )

        rankings = load_rankings(path)

        assert rankings[0].manual_tier == 2
        assert rankings[0].drafted_percentage == 85.5


class TestAvailablePlayers:
    """Filtering the ranking pool against recorded draft state."""

    def test_excludes_drafted_yahoo_ids(
        self,
        make_draft_pick: Callable[..., DraftPick],
        make_draft_state: Callable[..., DraftState],
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: rankings containing one drafted and one undrafted player
        WHEN: available players are calculated
        THEN: the player with the recorded Yahoo Player ID is excluded
        """
        drafted = make_player(
            rank=1,
            name="Drafted Player",
            yahoo_player_id=10001,
        )
        available = make_player(
            rank=2,
            name="Available Player",
            yahoo_player_id=10002,
        )
        state = make_draft_state(
            picks=[
                make_draft_pick(
                    overall=1,
                    team_id=1,
                    position="RB",
                    yahoo_player_id=10001,
                )
            ]
        )

        result = get_available_players([drafted, available], state)

        assert result == [available]

    def test_ignores_pick_without_yahoo_id(
        self,
        make_draft_pick: Callable[..., DraftPick],
        make_draft_state: Callable[..., DraftState],
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: draft state containing a legacy pick without a Yahoo Player ID
        WHEN: available players are calculated
        THEN: ranked players are not removed based on that incomplete identity
        """
        player = make_player(yahoo_player_id=10001)
        pick = make_draft_pick(
            overall=1,
            team_id=1,
            position="RB",
            yahoo_player_id=10001,
        )
        pick.yahoo_player_id = None
        state = make_draft_state(picks=[pick])

        result = get_available_players([player], state)

        assert result == [player]

    def test_preserves_ranking_order(
        self,
        draft_state: DraftState,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: several undrafted players in ranking order
        WHEN: available players are calculated
        THEN: the original ranking order is preserved
        """
        rankings = [
            make_player(rank=1, name="First", yahoo_player_id=10001),
            make_player(rank=2, name="Second", yahoo_player_id=10002),
            make_player(rank=3, name="Third", yahoo_player_id=10003),
        ]

        result = get_available_players(rankings, draft_state)

        assert result == rankings


class TestTierNavigation:
    """Manual-tier lookup, depth, and next-tier navigation."""

    def test_filters_by_position_and_tier(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: available players spanning multiple positions and tiers
        WHEN: one position and tier are requested
        THEN: only players matching both values are returned
        """
        rb_tier_one = make_player(
            name="RB One",
            position="RB",
            manual_tier=1,
            yahoo_player_id=10001,
        )
        rb_tier_two = make_player(
            rank=2,
            name="RB Two",
            position="RB",
            manual_tier=2,
            yahoo_player_id=10002,
        )
        wr_tier_one = make_player(
            rank=3,
            name="WR One",
            position="WR",
            manual_tier=1,
            yahoo_player_id=10003,
        )

        result = get_tier_players(
            [rb_tier_one, rb_tier_two, wr_tier_one],
            position="RB",
            tier=1,
        )

        assert result == [rb_tier_one]

    def test_counts_remaining_peers(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: three available running backs in the same manual tier
        WHEN: remaining depth is calculated for one of those players
        THEN: all three available players in that position tier are counted
        """
        players = [
            make_player(name="RB One", yahoo_player_id=10001, manual_tier=1),
            make_player(
                rank=2,
                name="RB Two",
                yahoo_player_id=10002,
                manual_tier=1,
            ),
            make_player(
                rank=3,
                name="RB Three",
                yahoo_player_id=10003,
                manual_tier=1,
            ),
        ]

        remaining = remaining_in_player_tier(players, players[0])

        assert remaining == 3

    def test_untiered_player_has_unknown_remaining(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: an available player without a manual tier
        WHEN: remaining tier depth is requested
        THEN: None distinguishes missing tier data from an exhausted tier
        """
        player = make_player(manual_tier=None)

        assert remaining_in_player_tier([player], player) is None

    def test_finds_closest_later_tier(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a tier-two running back with later running-back tiers four and six
        WHEN: the next position tier is requested
        THEN: the closest numerically worse available tier is returned
        """
        player = make_player(manual_tier=2, yahoo_player_id=10001)
        available = [
            player,
            make_player(
                rank=2,
                name="Tier Six",
                manual_tier=6,
                yahoo_player_id=10002,
            ),
            make_player(
                rank=3,
                name="Tier Four",
                manual_tier=4,
                yahoo_player_id=10003,
            ),
            make_player(
                rank=4,
                name="Other Position",
                position="WR",
                manual_tier=3,
                yahoo_player_id=10004,
            ),
            make_player(
                rank=5,
                name="Untiered RB",
                manual_tier=None,
                yahoo_player_id=10005,
            ),
        ]

        assert next_position_tier(available, player) == 4

    def test_no_later_tier_returns_none(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a running back already in the latest available tier at the position
        WHEN: the next position tier is requested
        THEN: no later tier is reported
        """
        player = make_player(manual_tier=3, yahoo_player_id=10001)
        available = [
            player,
            make_player(
                rank=2,
                name="Earlier Tier",
                manual_tier=2,
                yahoo_player_id=10002,
            ),
        ]

        assert next_position_tier(available, player) is None

    def test_untiered_player_has_no_next_tier(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a player without a manual tier
        WHEN: the next position tier is requested
        THEN: no tier comparison is attempted
        """
        player = make_player(manual_tier=None)

        assert next_position_tier([player], player) is None


class TestTierScarcity:
    """Tier-depth summaries and scarcity signals."""

    def test_identifies_last_player(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: one tier with a single player and another tier with two players
        WHEN: last-in-tier status is calculated
        THEN: only the sole remaining player is marked as last in tier
        """
        sole_player = make_player(
            name="Sole Player",
            manual_tier=1,
            yahoo_player_id=10001,
        )
        tier_two_a = make_player(
            rank=2,
            name="Tier Two A",
            manual_tier=2,
            yahoo_player_id=10002,
        )
        tier_two_b = make_player(
            rank=3,
            name="Tier Two B",
            manual_tier=2,
            yahoo_player_id=10003,
        )
        available = [sole_player, tier_two_a, tier_two_b]

        assert is_last_in_tier(available, sole_player) is True
        assert is_last_in_tier(available, tier_two_a) is False

    def test_summary_groups_counts_and_omits_untiered(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: available players across positions with one untiered player
        WHEN: the tier summary is calculated
        THEN: tiered players are counted by position and untiered players are omitted
        """
        available = [
            make_player(name="RB One", position="RB", manual_tier=1, yahoo_player_id=10001),
            make_player(
                rank=2,
                name="RB Two",
                position="RB",
                manual_tier=1,
                yahoo_player_id=10002,
            ),
            make_player(
                rank=3,
                name="RB Three",
                position="RB",
                manual_tier=2,
                yahoo_player_id=10003,
            ),
            make_player(
                rank=4,
                name="WR One",
                position="WR",
                manual_tier=1,
                yahoo_player_id=10004,
            ),
            make_player(
                rank=5,
                name="Untiered WR",
                position="WR",
                manual_tier=None,
                yahoo_player_id=10005,
            ),
        ]

        summary = get_position_tier_summary(available)

        assert summary == {
            "RB": {1: 2, 2: 1},
            "WR": {1: 1},
        }

    def test_untiered_player_has_no_flags(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: an available player without a manual tier
        WHEN: scarcity flags are calculated
        THEN: no tier-based scarcity signals are produced
        """
        player = make_player(manual_tier=None)

        assert get_scarcity_flags([player], player) == []

    def test_marks_last_player_and_large_drop(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: the final tier-one running back followed by an available tier-three option
        WHEN: scarcity flags are calculated
        THEN: both last-in-tier and large-tier-drop signals are returned
        """
        player = make_player(
            name="Tier One",
            manual_tier=1,
            yahoo_player_id=10001,
        )
        later = make_player(
            rank=2,
            name="Tier Three",
            manual_tier=3,
            yahoo_player_id=10002,
        )

        flags = get_scarcity_flags([player, later], player)

        assert flags == ["LAST_IN_TIER", "LARGE_TIER_DROP"]

    def test_marks_low_depth_without_large_drop(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: two tier-one running backs followed by an available tier-two option
        WHEN: scarcity flags are calculated
        THEN: low tier depth is reported without a large tier drop
        """
        player = make_player(
            name="Tier One A",
            manual_tier=1,
            yahoo_player_id=10001,
        )
        peer = make_player(
            rank=2,
            name="Tier One B",
            manual_tier=1,
            yahoo_player_id=10002,
        )
        next_tier = make_player(
            rank=3,
            name="Tier Two",
            manual_tier=2,
            yahoo_player_id=10003,
        )

        flags = get_scarcity_flags([player, peer, next_tier], player)

        assert flags == ["LOW_TIER_DEPTH"]

    def test_healthy_depth_has_no_flags(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: at least three players remain in the current tier with no later tier
        WHEN: scarcity flags are calculated
        THEN: no scarcity condition is reported
        """
        players = [
            make_player(name="Player One", manual_tier=1, yahoo_player_id=10001),
            make_player(
                rank=2,
                name="Player Two",
                manual_tier=1,
                yahoo_player_id=10002,
            ),
            make_player(
                rank=3,
                name="Player Three",
                manual_tier=1,
                yahoo_player_id=10003,
            ),
        ]

        assert get_scarcity_flags(players, players[0]) == []


class TestTierCoverage:
    """Manual-tier coverage reporting."""

    def test_counts_tiered_and_total_at_position(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: three running backs with two tiered and one untiered
        WHEN: running-back tier coverage is calculated
        THEN: the result reports two tiered players out of three total
        """
        rankings = [
            make_player(name="RB One", position="RB", manual_tier=1, yahoo_player_id=10001),
            make_player(
                rank=2,
                name="RB Two",
                position="RB",
                manual_tier=2,
                yahoo_player_id=10002,
            ),
            make_player(
                rank=3,
                name="RB Untiered",
                position="RB",
                manual_tier=None,
                yahoo_player_id=10003,
            ),
            make_player(
                rank=4,
                name="WR One",
                position="WR",
                manual_tier=1,
                yahoo_player_id=10004,
            ),
        ]

        assert get_tier_coverage(rankings, "RB") == (2, 3)

    def test_missing_position_returns_zeroes(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: rankings with no tight ends
        WHEN: tight-end tier coverage is calculated
        THEN: both tiered and total counts are zero
        """
        rankings = [make_player(position="RB")]

        assert get_tier_coverage(rankings, "TE") == (0, 0)
