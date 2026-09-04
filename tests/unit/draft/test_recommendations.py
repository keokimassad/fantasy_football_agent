"""Unit tests for deterministic draft-candidate evaluation."""

from collections.abc import Callable

import pytest

from fantasy_football_agent.draft.models import (
    DraftPick,
    DraftState,
    LeagueConfig,
    Player,
)
from fantasy_football_agent.draft.recommendations import (
    AvailabilityRisk,
    CandidateDesirability,
    CandidateEvaluation,
    DecisionPriority,
    LossCost,
    PositionDepthNeed,
    ReturnRisk,
    RosterFit,
    RosterUtility,
    build_candidate_recommendations,
    evaluate_candidates,
)

pytestmark = pytest.mark.unit


def _evaluation(
    player: Player,
    *,
    roster_fit: RosterFit = RosterFit.DIRECT_STARTER,
    position_depth_need: PositionDepthNeed = PositionDepthNeed.NOT_APPLICABLE,
    scarcity_flags: tuple[str, ...] = (),
    decision_pick: int = 17,
    following_pick: int = 24,
    tier_remaining: int | None = None,
    next_tier: int | None = None,
    position_tier_gap: int | None = 0,
    pre_decision_exposure: int = 0,
    return_exposure: int = 0,
    other_flex_eligible_starter_slots_open: int = 0,
    is_on_clock: bool = True,
) -> CandidateEvaluation:
    """Build candidate evidence for recommendation-specific tests."""
    return CandidateEvaluation(
        player=player,
        decision_pick=decision_pick,
        following_pick=following_pick,
        is_on_clock=is_on_clock,
        roster_fit=roster_fit,
        position_depth_need=position_depth_need,
        tier_remaining=tier_remaining,
        next_tier=next_tier,
        position_tier_gap=position_tier_gap,
        scarcity_flags=scarcity_flags,
        market_pick_estimate=(
            float(player.rank) if player.adp is None else (player.rank + player.adp) / 2
        ),
        adp_value_at_decision=(None if player.adp is None else decision_pick - player.adp),
        pre_decision_position_exposure=pre_decision_exposure,
        return_window_position_exposure=return_exposure,
        other_flex_eligible_starter_slots_open=(other_flex_eligible_starter_slots_open),
    )


def _team_eight_picks(
    make_draft_pick: Callable[..., DraftPick],
    positions: list[str],
) -> list[DraftPick]:
    """Build recorded picks for draft slot eight using its real snake-draft turns."""
    overalls = [8, 13, 28, 33, 48, 53, 68, 73, 88, 93, 108, 113, 128, 133, 148]
    return [
        make_draft_pick(
            overall=overall,
            team_id=8,
            position=position,
        )
        for overall, position in zip(overalls[: len(positions)], positions, strict=True)
    ]


class TestCandidateEvaluation:
    """Candidate evaluation and factual evidence."""

    def test_only_required_positions_remain_when_optional_capacity_is_zero(
        self,
        league_config: LeagueConfig,
        make_draft_pick: Callable[..., DraftPick],
        make_draft_state: Callable[..., DraftState],
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: team eight reaches pick one hundred thirty-three with exactly kicker and defense open
        WHEN: candidates are evaluated with two roster selections remaining
        THEN: optional depth players are excluded while kicker and defense remain eligible
        """
        state = make_draft_state(
            my_draft_slot=8,
            current_overall_pick=133,
            picks=_team_eight_picks(
                make_draft_pick,
                [
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
                    "WR",
                ],
            ),
        )
        candidates = [
            make_player(
                rank=123,
                name="Depth Wide Receiver",
                position="WR",
                yahoo_player_id=1,
            ),
            make_player(
                rank=124,
                name="Depth Running Back",
                position="RB",
                yahoo_player_id=2,
            ),
            make_player(
                rank=166,
                name="Starting Kicker",
                position="K",
                yahoo_player_id=3,
            ),
            make_player(
                rank=151,
                name="Starting Defense",
                position="DEF",
                yahoo_player_id=4,
            ),
        ]

        evaluations = evaluate_candidates(candidates, state, league_config)

        assert [evaluation.player.position for evaluation in evaluations] == ["K", "DEF"]

    def test_depth_candidates_remain_eligible_while_optional_capacity_exists(
        self,
        league_config: LeagueConfig,
        make_draft_pick: Callable[..., DraftPick],
        make_draft_state: Callable[..., DraftState],
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: team eight still has one optional roster slot before reserving kicker and defense
        WHEN: a depth wide receiver is evaluated at pick one hundred twenty-eight
        THEN: the soft roster targets do not prevent that optional depth selection
        """
        state = make_draft_state(
            my_draft_slot=8,
            current_overall_pick=128,
            picks=_team_eight_picks(
                make_draft_pick,
                [
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
                ],
            ),
        )
        depth_receiver = make_player(
            rank=107,
            name="Optional Depth Receiver",
            position="WR",
            yahoo_player_id=5,
        )

        evaluations = evaluate_candidates([depth_receiver], state, league_config)

        assert [evaluation.player.name for evaluation in evaluations] == ["Optional Depth Receiver"]

    def test_rejects_roster_that_cannot_fill_required_starters(
        self,
        league_config: LeagueConfig,
        make_draft_pick: Callable[..., DraftPick],
        make_draft_state: Callable[..., DraftState],
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: team eight has one roster spot left but several required starter positions open
        WHEN: candidates are evaluated before its final selection
        THEN: the impossible roster state is rejected instead of recommending another player
        """
        state = make_draft_state(
            my_draft_slot=8,
            current_overall_pick=148,
            picks=_team_eight_picks(
                make_draft_pick,
                ["WR"] * 14,
            ),
        )
        candidate = make_player(
            rank=150,
            name="Final Candidate",
            position="WR",
            yahoo_player_id=6,
        )

        with pytest.raises(
            ValueError,
            match="Draft state cannot fill every remaining required starter slot",
        ):
            evaluate_candidates([candidate], state, league_config)

    def test_decision_horizons(
        self,
        league_config: LeagueConfig,
        make_draft_state: Callable[..., DraftState],
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a slot-four team waiting at overall pick five
        WHEN: available candidates are evaluated
        THEN: the next decision is pick seventeen and the following turn is pick twenty-four
        """
        state = make_draft_state(
            my_draft_slot=4,
            current_overall_pick=5,
        )
        player = make_player(
            name="Candidate RB",
            position="RB",
        )

        evaluation = evaluate_candidates(
            [player],
            state,
            league_config,
        )[0]

        assert evaluation.decision_pick == 17
        assert evaluation.following_pick == 24
        assert evaluation.is_on_clock is False

    def test_direct_starter_fit(
        self,
        league_config: LeagueConfig,
        make_draft_state: Callable[..., DraftState],
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: the user's starting RB slots are still open
        WHEN: an available running back is evaluated
        THEN: the candidate is classified as a direct starter fit
        """
        state = make_draft_state()
        player = make_player(
            name="Candidate RB",
            position="RB",
        )

        evaluation = evaluate_candidates(
            [player],
            state,
            league_config,
        )[0]

        assert evaluation.roster_fit == RosterFit.DIRECT_STARTER

    def test_flex_fit_after_direct_slots(
        self,
        league_config: LeagueConfig,
        make_draft_pick: Callable[..., DraftPick],
        make_draft_state: Callable[..., DraftState],
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: the user has filled both dedicated RB slots but still has an open FLEX
        WHEN: another running back is evaluated
        THEN: the candidate is classified as a FLEX fit
        """
        state = make_draft_state(
            picks=[
                make_draft_pick(
                    overall=4,
                    team_id=4,
                    position="RB",
                ),
                make_draft_pick(
                    overall=17,
                    team_id=4,
                    position="RB",
                ),
            ],
            current_overall_pick=18,
        )
        player = make_player(
            name="Candidate RB",
            position="RB",
        )

        evaluation = evaluate_candidates(
            [player],
            state,
            league_config,
        )[0]

        assert evaluation.roster_fit == RosterFit.FLEX

    def test_depth_fit_after_flex(
        self,
        league_config: LeagueConfig,
        make_draft_pick: Callable[..., DraftPick],
        make_draft_state: Callable[..., DraftState],
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: the user has filled both dedicated RB slots and FLEX with running backs
        WHEN: another running back is evaluated
        THEN: the candidate is classified as a depth fit
        """
        state = make_draft_state(
            picks=[
                make_draft_pick(
                    overall=4,
                    team_id=4,
                    position="RB",
                ),
                make_draft_pick(
                    overall=17,
                    team_id=4,
                    position="RB",
                ),
                make_draft_pick(
                    overall=24,
                    team_id=4,
                    position="RB",
                ),
            ],
            current_overall_pick=25,
        )
        player = make_player(
            name="Candidate RB",
            position="RB",
        )

        evaluation = evaluate_candidates(
            [player],
            state,
            league_config,
        )[0]

        assert evaluation.roster_fit == RosterFit.DEPTH

    def test_high_depth_need(
        self,
        league_config: LeagueConfig,
        make_draft_pick: Callable[..., DraftPick],
        make_draft_state: Callable[..., DraftState],
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: the user has two RBs, three WRs filling FLEX, and an RB target of four
        WHEN: another RB is evaluated as bench depth
        THEN: the position depth need is high
        """
        state = make_draft_state(
            picks=[
                make_draft_pick(overall=4, team_id=4, position="RB"),
                make_draft_pick(overall=17, team_id=4, position="RB"),
                make_draft_pick(overall=24, team_id=4, position="WR"),
                make_draft_pick(overall=37, team_id=4, position="WR"),
                make_draft_pick(overall=44, team_id=4, position="WR"),
            ],
            current_overall_pick=45,
        )
        player = make_player(
            name="Candidate RB",
            position="RB",
        )

        evaluation = evaluate_candidates(
            [player],
            state,
            league_config,
        )[0]

        assert evaluation.roster_fit == RosterFit.DEPTH
        assert evaluation.position_depth_need == PositionDepthNeed.HIGH

    def test_medium_depth_need(
        self,
        league_config: LeagueConfig,
        make_draft_pick: Callable[..., DraftPick],
        make_draft_state: Callable[..., DraftState],
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: the user has three RBs and a roster target of four
        WHEN: another RB is evaluated as bench depth
        THEN: the position depth need is medium
        """
        state = make_draft_state(
            picks=[
                make_draft_pick(overall=4, team_id=4, position="RB"),
                make_draft_pick(overall=17, team_id=4, position="RB"),
                make_draft_pick(overall=24, team_id=4, position="RB"),
            ],
            current_overall_pick=25,
        )
        player = make_player(
            name="Candidate RB",
            position="RB",
        )

        evaluation = evaluate_candidates(
            [player],
            state,
            league_config,
        )[0]

        assert evaluation.roster_fit == RosterFit.DEPTH
        assert evaluation.position_depth_need == PositionDepthNeed.MEDIUM

    def test_low_depth_need(
        self,
        league_config: LeagueConfig,
        make_draft_pick: Callable[..., DraftPick],
        make_draft_state: Callable[..., DraftState],
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: the user has reached the roster target of four RBs
        WHEN: another RB is evaluated as bench depth
        THEN: the position depth need is low
        """
        state = make_draft_state(
            picks=[
                make_draft_pick(overall=4, team_id=4, position="RB"),
                make_draft_pick(overall=17, team_id=4, position="RB"),
                make_draft_pick(overall=24, team_id=4, position="RB"),
                make_draft_pick(overall=37, team_id=4, position="RB"),
            ],
            current_overall_pick=38,
        )
        player = make_player(
            name="Candidate RB",
            position="RB",
        )

        evaluation = evaluate_candidates(
            [player],
            state,
            league_config,
        )[0]

        assert evaluation.roster_fit == RosterFit.DEPTH
        assert evaluation.position_depth_need == PositionDepthNeed.LOW

    def test_tier_evidence(
        self,
        league_config: LeagueConfig,
        make_draft_state: Callable[..., DraftState],
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: one player remaining in RB tier two with tier four next
        WHEN: the candidate is evaluated
        THEN: tier depth, next tier, and scarcity flags are preserved as evidence
        """
        candidate = make_player(
            rank=10,
            name="Tier Two RB",
            position="RB",
            manual_tier=2,
            yahoo_player_id=10010,
        )
        later_player = make_player(
            rank=20,
            name="Tier Four RB",
            position="RB",
            manual_tier=4,
            yahoo_player_id=10020,
        )

        evaluation = evaluate_candidates(
            [candidate, later_player],
            make_draft_state(),
            league_config,
        )[0]

        assert evaluation.tier_remaining == 1
        assert evaluation.next_tier == 4
        assert evaluation.scarcity_flags == (
            "LAST_IN_TIER",
            "LARGE_TIER_DROP",
        )

    def test_adp_value(
        self,
        league_config: LeagueConfig,
        make_draft_state: Callable[..., DraftState],
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a player with ADP fourteen and the user's next decision at pick seventeen
        WHEN: the candidate is evaluated
        THEN: the player has three picks of positive ADP value at that decision
        """
        player = make_player(
            adp=14.0,
        )

        evaluation = evaluate_candidates(
            [player],
            make_draft_state(
                my_draft_slot=4,
                current_overall_pick=5,
            ),
            league_config,
        )[0]

        assert evaluation.adp_value_at_decision == 3.0

    def test_missing_adp(
        self,
        league_config: LeagueConfig,
        make_draft_state: Callable[..., DraftState],
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: an available player without an ADP
        WHEN: the candidate is evaluated
        THEN: ADP value remains unknown instead of inventing market information
        """
        player = make_player(
            adp=None,
        )

        evaluation = evaluate_candidates(
            [player],
            make_draft_state(),
            league_config,
        )[0]

        assert evaluation.adp_value_at_decision is None

    def test_separate_exposure_windows(
        self,
        league_config: LeagueConfig,
        make_draft_state: Callable[..., DraftState],
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a slot-four team waiting at pick five with empty opponent rosters
        WHEN: an RB candidate is evaluated
        THEN: demand before pick seventeen is separate from demand before pick twenty-four
        """
        player = make_player(
            position="RB",
        )

        evaluation = evaluate_candidates(
            [player],
            make_draft_state(
                my_draft_slot=4,
                current_overall_pick=5,
            ),
            league_config,
        )[0]

        assert evaluation.pre_decision_position_exposure == 12
        assert evaluation.return_window_position_exposure == 6

    def test_other_flex_starter_slots(
        self,
        league_config: LeagueConfig,
        make_draft_state: Callable[..., DraftState],
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: an empty roster with open RB, WR, and TE starter slots
        WHEN: an RB candidate is evaluated
        THEN: other open FLEX-eligible starter slots include WR and TE but exclude RB
        """
        player = make_player(
            position="RB",
        )

        evaluation = evaluate_candidates(
            [player],
            make_draft_state(),
            league_config,
        )[0]

        assert evaluation.other_flex_eligible_starter_slots_open == 3


class TestReturnRisk:
    """Return-risk classification."""

    def test_high_return_risk(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a direct starter whose ADP is before the following pick with opponent exposure
        WHEN: candidate recommendations are built
        THEN: the player receives high return risk and high decision priority
        """
        player = make_player(
            rank=10,
            adp=18.0,
            position="RB",
        )

        recommendation = build_candidate_recommendations(
            [
                _evaluation(
                    player,
                    return_exposure=4,
                )
            ]
        )[0]

        assert recommendation.return_risk == ReturnRisk.HIGH
        assert recommendation.priority == DecisionPriority.HIGH
        assert "FILLS_DIRECT_STARTER" in recommendation.signals
        assert "MARKET_EXPECTED_BEFORE_FOLLOWING_PICK" in recommendation.signals
        assert "RETURN_WINDOW_POSITION_PRESSURE" in recommendation.signals

    def test_low_return_risk(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a depth player whose ADP is after the following pick with no opponent exposure
        WHEN: candidate recommendations are built
        THEN: the player receives low return risk and low decision priority
        """
        player = make_player(
            rank=40,
            adp=40.0,
            position="RB",
        )

        recommendation = build_candidate_recommendations(
            [
                _evaluation(
                    player,
                    roster_fit=RosterFit.DEPTH,
                )
            ]
        )[0]

        assert recommendation.return_risk == ReturnRisk.LOW
        assert recommendation.priority == DecisionPriority.LOW

    def test_unknown_return_risk(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a later-ranked candidate without ADP information
        WHEN: recommendations are built
        THEN: return risk remains unknown rather than inventing missing market timing
        """
        player = make_player(
            rank=40,
            adp=None,
            position="RB",
        )

        recommendation = build_candidate_recommendations([_evaluation(player)])[0]

        assert recommendation.return_risk == ReturnRisk.UNKNOWN

    def test_rank_fallback_without_adp(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: an early-ranked candidate without ADP information
        WHEN: recommendations are built
        THEN: Yahoo rank alone produces medium return risk
        """
        player = make_player(
            rank=10,
            adp=None,
            position="RB",
        )

        recommendation = build_candidate_recommendations([_evaluation(player)])[0]

        assert recommendation.return_risk == ReturnRisk.MEDIUM

    def test_exposure_is_not_probability(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a later-ranked player with many generic positional opportunities before the next turn
        WHEN: return risk is calculated
        THEN: generic exposure alone does not raise a player who both rank and ADP expect later
        """
        player = make_player(
            rank=47,
            adp=50.0,
            position="RB",
        )

        recommendation = build_candidate_recommendations(
            [
                _evaluation(
                    player,
                    decision_pick=36,
                    following_pick=45,
                    return_exposure=8,
                )
            ]
        )[0]

        assert recommendation.return_risk == ReturnRisk.LOW
        assert "RETURN_WINDOW_POSITION_PRESSURE" in recommendation.signals

    def test_market_disagreement_is_medium_risk(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: Yahoo rank expects a player after the following pick but ADP expects him before it
        WHEN: return risk is calculated
        THEN: conflicting market signals produce medium rather than high risk
        """
        player = make_player(
            rank=28,
            adp=19.6,
            position="QB",
        )

        recommendation = build_candidate_recommendations(
            [
                _evaluation(
                    player,
                    decision_pick=16,
                    following_pick=25,
                    return_exposure=8,
                )
            ]
        )[0]

        assert recommendation.return_risk == ReturnRisk.MEDIUM


class TestLossCostAndPriority:
    """Loss-cost and decision-priority classification."""

    def test_tier_loss_separate_from_urgency(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a direct starter who is the final player before a large tier drop
        and is likely to survive
        WHEN: recommendations are built
        THEN: loss cost is high while overall decision priority remains medium
        """
        player = make_player(
            rank=30,
            adp=30.0,
            position="RB",
        )

        recommendation = build_candidate_recommendations(
            [
                _evaluation(
                    player,
                    scarcity_flags=(
                        "LAST_IN_TIER",
                        "LARGE_TIER_DROP",
                    ),
                )
            ]
        )[0]

        assert recommendation.loss_cost == LossCost.HIGH
        assert recommendation.return_risk == ReturnRisk.LOW
        assert recommendation.priority == DecisionPriority.MEDIUM
        assert "LAST_IN_TIER" in recommendation.signals
        assert "LARGE_TIER_DROP" in recommendation.signals

    def test_replaceable_starter_medium_loss(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a direct starter with multiple tier alternatives remaining
        WHEN: recommendations are built
        THEN: roster fit matters but replacement cost remains medium
        """
        player = make_player(
            rank=20,
            position="WR",
            adp=18.0,
        )

        recommendation = build_candidate_recommendations(
            [
                _evaluation(
                    player,
                    tier_remaining=3,
                    next_tier=4,
                )
            ]
        )[0]

        assert recommendation.loss_cost == LossCost.MEDIUM

    def test_known_tier_cliff_high_loss(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a starting candidate who is last in a tier with a known later tier
        WHEN: recommendations are built
        THEN: losing the candidate is classified as high cost
        """
        player = make_player(
            position="RB",
            manual_tier=3,
        )

        recommendation = build_candidate_recommendations(
            [
                _evaluation(
                    player,
                    tier_remaining=1,
                    next_tier=4,
                    scarcity_flags=("LAST_IN_TIER",),
                )
            ]
        )[0]

        assert recommendation.loss_cost == LossCost.HIGH

    def test_unknown_tier_cliff_not_high_loss(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: the last player in the final manually defined tier with no known next tier
        WHEN: recommendations are built
        THEN: the unknown replacement quality does not become high loss cost
        """
        player = make_player(
            position="WR",
            manual_tier=8,
        )

        recommendation = build_candidate_recommendations(
            [
                _evaluation(
                    player,
                    tier_remaining=1,
                    next_tier=None,
                    scarcity_flags=("LAST_IN_TIER",),
                )
            ]
        )[0]

        assert recommendation.loss_cost == LossCost.MEDIUM

    def test_high_loss_can_still_wait(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a costly tier-cliff player who is nevertheless likely to survive
        WHEN: recommendations are built
        THEN: loss cost remains high but overall decision priority is only medium
        """
        player = make_player(
            rank=40,
            position="RB",
            adp=40.0,
        )

        recommendation = build_candidate_recommendations(
            [
                _evaluation(
                    player,
                    decision_pick=17,
                    following_pick=24,
                    next_tier=4,
                    scarcity_flags=("LAST_IN_TIER",),
                    return_exposure=0,
                )
            ]
        )[0]

        assert recommendation.loss_cost == LossCost.HIGH
        assert recommendation.return_risk == ReturnRisk.LOW
        assert recommendation.priority == DecisionPriority.MEDIUM

    def test_plain_depth_low_loss(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a depth candidate without tier scarcity
        WHEN: recommendations are built
        THEN: losing the candidate has low deterministic cost
        """
        player = make_player(
            position="WR",
            adp=40.0,
        )

        recommendation = build_candidate_recommendations(
            [
                _evaluation(
                    player,
                    roster_fit=RosterFit.DEPTH,
                )
            ]
        )[0]

        assert recommendation.loss_cost == LossCost.LOW


class TestRosterUtility:
    """Roster-construction utility and depth need."""

    def test_early_flex_low_utility(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a FLEX candidate while other FLEX-eligible dedicated starter slots remain open
        WHEN: recommendations are built
        THEN: immediate roster utility is low
        """
        player = make_player(
            position="TE",
            adp=18.0,
        )

        recommendation = build_candidate_recommendations(
            [
                _evaluation(
                    player,
                    roster_fit=RosterFit.FLEX,
                    other_flex_eligible_starter_slots_open=2,
                )
            ]
        )[0]

        assert recommendation.roster_utility == RosterUtility.LOW

    def test_late_flex_medium_utility(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a FLEX candidate after all FLEX-eligible dedicated starter slots are filled
        WHEN: recommendations are built
        THEN: the FLEX candidate has medium immediate roster utility
        """
        player = make_player(
            position="TE",
            adp=18.0,
        )

        recommendation = build_candidate_recommendations(
            [
                _evaluation(
                    player,
                    roster_fit=RosterFit.FLEX,
                    other_flex_eligible_starter_slots_open=0,
                )
            ]
        )[0]

        assert recommendation.roster_utility == RosterUtility.MEDIUM

    def test_direct_starter_high_utility(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a candidate who fills an open dedicated starter slot
        WHEN: recommendations are built
        THEN: immediate roster utility is high
        """
        recommendation = build_candidate_recommendations(
            [
                _evaluation(
                    make_player(position="WR"),
                    roster_fit=RosterFit.DIRECT_STARTER,
                )
            ]
        )[0]

        assert recommendation.roster_utility == RosterUtility.HIGH

    def test_direct_starter_over_early_flex(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a direct-starting WR and a similarly urgent TE who would consume FLEX early
        WHEN: the shortlist is ordered
        THEN: the dedicated starter is preferred over the early FLEX candidate
        """
        wide_receiver = make_player(
            rank=40,
            name="Starting Wide Receiver",
            position="WR",
            adp=41.6,
            yahoo_player_id=10040,
        )
        tight_end = make_player(
            rank=39,
            name="Second Tight End",
            position="TE",
            adp=39.6,
            yahoo_player_id=10039,
        )

        recommendations = build_candidate_recommendations(
            [
                _evaluation(
                    tight_end,
                    roster_fit=RosterFit.FLEX,
                    decision_pick=39,
                    following_pick=42,
                    other_flex_eligible_starter_slots_open=2,
                    return_exposure=2,
                ),
                _evaluation(
                    wide_receiver,
                    roster_fit=RosterFit.DIRECT_STARTER,
                    decision_pick=39,
                    following_pick=42,
                    return_exposure=2,
                ),
            ]
        )

        assert recommendations[0].evaluation.player.name == "Starting Wide Receiver"
        assert recommendations[0].roster_utility == RosterUtility.HIGH

        assert recommendations[1].evaluation.player.name == "Second Tight End"
        assert recommendations[1].roster_utility == RosterUtility.LOW

    def test_needed_depth_medium_utility(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a depth candidate at a position still below its roster target
        WHEN: recommendations are built
        THEN: needed bench depth has medium roster utility
        """
        recommendation = build_candidate_recommendations(
            [
                _evaluation(
                    make_player(position="RB"),
                    roster_fit=RosterFit.DEPTH,
                    position_depth_need=PositionDepthNeed.HIGH,
                )
            ]
        )[0]

        assert recommendation.roster_utility == RosterUtility.MEDIUM

    def test_nearly_complete_depth_medium_utility(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a depth candidate when its position is one player below the roster target
        WHEN: recommendations are built
        THEN: the remaining depth need still has medium roster utility
        """
        recommendation = build_candidate_recommendations(
            [
                _evaluation(
                    make_player(position="RB"),
                    roster_fit=RosterFit.DEPTH,
                    position_depth_need=PositionDepthNeed.MEDIUM,
                )
            ]
        )[0]

        assert recommendation.roster_utility == RosterUtility.MEDIUM

    def test_excess_depth_low_utility(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a depth candidate after its position roster target has been reached
        WHEN: recommendations are built
        THEN: additional depth has low roster utility
        """
        recommendation = build_candidate_recommendations(
            [
                _evaluation(
                    make_player(position="WR"),
                    roster_fit=RosterFit.DEPTH,
                    position_depth_need=PositionDepthNeed.LOW,
                )
            ]
        )[0]

        assert recommendation.roster_utility == RosterUtility.LOW

    def test_higher_depth_need_breaks_tie(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: comparable depth candidates with high and medium positional depth need
        WHEN: the shortlist is ordered
        THEN: the position with greater remaining depth need is preferred
        """
        high_need = make_player(
            rank=81,
            name="Needed RB",
            position="RB",
            adp=81.0,
            yahoo_player_id=10081,
        )
        medium_need = make_player(
            rank=80,
            name="Additional WR",
            position="WR",
            adp=80.0,
            yahoo_player_id=10080,
        )

        recommendations = build_candidate_recommendations(
            [
                _evaluation(
                    medium_need,
                    roster_fit=RosterFit.DEPTH,
                    position_depth_need=PositionDepthNeed.MEDIUM,
                ),
                _evaluation(
                    high_need,
                    roster_fit=RosterFit.DEPTH,
                    position_depth_need=PositionDepthNeed.HIGH,
                ),
            ]
        )

        assert recommendations[0].evaluation.player.name == "Needed RB"
        assert recommendations[1].evaluation.player.name == "Additional WR"


class TestRecommendationOrdering:
    """Deterministic shortlist ordering."""

    def test_urgency_before_rank(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a lower-ranked urgent starter and a higher-ranked low-urgency depth player
        WHEN: the shortlist is ordered
        THEN: deterministic urgency outranks raw Yahoo rank
        """
        higher_ranked = make_player(
            rank=5,
            name="Higher Ranked Player",
            adp=40.0,
            position="WR",
            yahoo_player_id=10005,
        )
        urgent_player = make_player(
            rank=20,
            name="Urgent Player",
            adp=18.0,
            position="RB",
            yahoo_player_id=10020,
        )

        recommendations = build_candidate_recommendations(
            [
                _evaluation(
                    higher_ranked,
                    roster_fit=RosterFit.DEPTH,
                ),
                _evaluation(
                    urgent_player,
                    return_exposure=4,
                ),
            ]
        )

        assert [recommendation.evaluation.player.name for recommendation in recommendations] == [
            "Urgent Player",
            "Higher Ranked Player",
        ]

    def test_market_consensus_within_same_priority(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: two candidates with equal recommendation classifications
        WHEN: the shortlist is ordered
        THEN: the Rank/ADP market consensus breaks the tie deterministically
        """
        first = make_player(
            rank=10,
            name="First Player",
            adp=18.0,
            yahoo_player_id=10010,
        )
        second = make_player(
            rank=15,
            name="Second Player",
            adp=18.0,
            yahoo_player_id=10015,
        )

        recommendations = build_candidate_recommendations(
            [
                _evaluation(second, return_exposure=2),
                _evaluation(first, return_exposure=2),
            ]
        )

        assert [recommendation.evaluation.player.name for recommendation in recommendations] == [
            "First Player",
            "Second Player",
        ]

    def test_tier_loss_over_return_risk(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a last-in-tier WR with medium return risk and a replaceable WR with high return risk
        WHEN: the deterministic shortlist is ordered
        THEN: the higher-cost tier loss is prioritized over disappearance risk alone
        """
        egbuka = make_player(
            rank=38,
            name="Emeka Egbuka",
            position="WR",
            adp=43.3,
            manual_tier=3,
            yahoo_player_id=10038,
        )
        mcmillan = make_player(
            rank=39,
            name="Tetairoa McMillan",
            position="WR",
            adp=41.6,
            manual_tier=4,
            yahoo_player_id=10039,
        )

        recommendations = build_candidate_recommendations(
            [
                _evaluation(
                    mcmillan,
                    decision_pick=39,
                    following_pick=42,
                    tier_remaining=3,
                    next_tier=5,
                    return_exposure=2,
                ),
                _evaluation(
                    egbuka,
                    decision_pick=39,
                    following_pick=42,
                    tier_remaining=1,
                    next_tier=4,
                    scarcity_flags=("LAST_IN_TIER",),
                    return_exposure=2,
                ),
            ]
        )

        assert recommendations[0].evaluation.player.name == "Emeka Egbuka"
        assert recommendations[0].loss_cost == LossCost.HIGH
        assert recommendations[0].return_risk == ReturnRisk.MEDIUM

        assert recommendations[1].evaluation.player.name == "Tetairoa McMillan"
        assert recommendations[1].loss_cost == LossCost.MEDIUM
        assert recommendations[1].return_risk == ReturnRisk.HIGH


class TestLowDesirabilityTimingGuardrail:
    """Ordering rules for candidates outside the normal market window."""

    def test_return_risk_precedes_roster_utility_for_low_desirability(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a safe LOW-desirability direct starter and a high-risk LOW-desirability depth player
        WHEN: the on-clock shortlist is ordered
        THEN: timing evidence outranks the empty-starter-slot advantage inside the LOW bucket
        """
        safe_direct_starter = make_player(
            rank=100,
            adp=100.0,
            name="Safe Direct Starter",
            position="TE",
            yahoo_player_id=10100,
        )
        risky_depth = make_player(
            rank=25,
            adp=25.0,
            name="Risky Depth Player",
            position="WR",
            yahoo_player_id=10025,
        )

        recommendations = build_candidate_recommendations(
            [
                _evaluation(
                    safe_direct_starter,
                    decision_pick=20,
                    following_pick=30,
                    roster_fit=RosterFit.DIRECT_STARTER,
                ),
                _evaluation(
                    risky_depth,
                    decision_pick=20,
                    following_pick=30,
                    roster_fit=RosterFit.DEPTH,
                    position_depth_need=PositionDepthNeed.LOW,
                ),
            ]
        )

        assert all(
            recommendation.desirability == CandidateDesirability.LOW
            for recommendation in recommendations
        )
        assert recommendations[0].evaluation.player.name == "Risky Depth Player"
        assert recommendations[0].return_risk == ReturnRisk.HIGH
        assert recommendations[1].evaluation.player.name == "Safe Direct Starter"
        assert recommendations[1].return_risk == ReturnRisk.LOW

    def test_unknown_return_risk_is_not_treated_as_safe_to_wait(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: otherwise comparable LOW-desirability candidates with UNKNOWN and LOW return risk
        WHEN: the on-clock shortlist is ordered
        THEN: missing market evidence remains more cautious than affirmative evidence of low risk
        """
        unknown = make_player(
            rank=90,
            adp=None,
            name="Unknown Timing",
            position="TE",
            yahoo_player_id=10090,
        )
        low = make_player(
            rank=80,
            adp=85.0,
            name="Low Timing",
            position="TE",
            yahoo_player_id=10080,
        )

        recommendations = build_candidate_recommendations(
            [
                _evaluation(unknown, decision_pick=20, following_pick=30),
                _evaluation(low, decision_pick=20, following_pick=30),
            ]
        )

        assert recommendations[0].evaluation.player.name == "Unknown Timing"
        assert recommendations[0].return_risk == ReturnRisk.UNKNOWN
        assert recommendations[1].return_risk == ReturnRisk.LOW

    def test_defense_surfaces_normally_when_market_window_supports_it(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a defense whose market timing places it before the following pick
        WHEN: recommendations are ordered
        THEN: no position-specific suppression prevents the defense from surfacing
        """
        sought_after_defense = make_player(
            rank=24,
            adp=25.0,
            name="Sought After Defense",
            position="DEF",
            yahoo_player_id=10024,
        )
        later_skill_player = make_player(
            rank=60,
            adp=65.0,
            name="Later Skill Player",
            position="WR",
            yahoo_player_id=10060,
        )

        recommendations = build_candidate_recommendations(
            [
                _evaluation(
                    later_skill_player,
                    decision_pick=20,
                    following_pick=30,
                    roster_fit=RosterFit.DEPTH,
                    position_depth_need=PositionDepthNeed.MEDIUM,
                ),
                _evaluation(
                    sought_after_defense,
                    decision_pick=20,
                    following_pick=30,
                    roster_fit=RosterFit.DIRECT_STARTER,
                ),
            ]
        )

        assert recommendations[0].evaluation.player.name == "Sought After Defense"
        assert recommendations[0].desirability == CandidateDesirability.MEDIUM
        assert recommendations[0].return_risk == ReturnRisk.HIGH


class TestRecommendationApi:
    """Recommendation builder API behavior."""

    def test_respects_limit(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: more evaluated candidates than the requested shortlist size
        WHEN: recommendations are built
        THEN: only the requested number of candidates is returned
        """
        evaluations = [
            _evaluation(
                make_player(
                    rank=rank,
                    name=f"Player {rank}",
                    yahoo_player_id=10000 + rank,
                )
            )
            for rank in range(1, 6)
        ]

        recommendations = build_candidate_recommendations(
            evaluations,
            limit=3,
        )

        assert len(recommendations) == 3

    def test_rejects_invalid_limit(self) -> None:
        """
        GIVEN: a recommendation limit less than one
        WHEN: the shortlist is requested
        THEN: the invalid limit is rejected explicitly
        """
        with pytest.raises(
            ValueError,
            match="Recommendation limit must be at least 1",
        ):
            build_candidate_recommendations(
                [],
                limit=0,
            )


class TestRecommendationSignals:
    """Human-readable recommendation signals."""

    def test_waiting_phase_signals(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a highly ranked player while the user is waiting for the next pick
        WHEN: recommendations are built
        THEN: the output describes future availability rather than claiming the player already fell
        """
        player = make_player(
            rank=1,
            adp=1.5,
            position="RB",
        )

        recommendation = build_candidate_recommendations(
            [
                _evaluation(
                    player,
                    decision_pick=5,
                    following_pick=16,
                    is_on_clock=False,
                    pre_decision_exposure=4,
                    return_exposure=10,
                )
            ]
        )[0]

        assert recommendation.availability_risk == AvailabilityRisk.HIGH
        assert "VALUE_IF_AVAILABLE_AT_DECISION" in recommendation.signals
        assert "PRE_DECISION_POSITION_PRESSURE" in recommendation.signals
        assert "FALLEN_PAST_ADP" not in recommendation.signals
        assert "RETURN_WINDOW_POSITION_PRESSURE" not in recommendation.signals

    def test_high_depth_need_signal(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a depth candidate at a position substantially below its roster target
        WHEN: recommendations are built
        THEN: the recommendation explains the high positional depth need
        """
        recommendation = build_candidate_recommendations(
            [
                _evaluation(
                    make_player(position="RB"),
                    roster_fit=RosterFit.DEPTH,
                    position_depth_need=PositionDepthNeed.HIGH,
                )
            ]
        )[0]

        assert "HIGH_POSITION_DEPTH_NEED" in recommendation.signals

    def test_remaining_depth_need_signal(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a depth candidate one player below its position roster target
        WHEN: recommendations are built
        THEN: the recommendation explains the remaining positional depth need
        """
        recommendation = build_candidate_recommendations(
            [
                _evaluation(
                    make_player(position="WR"),
                    roster_fit=RosterFit.DEPTH,
                    position_depth_need=PositionDepthNeed.MEDIUM,
                )
            ]
        )[0]

        assert "POSITION_DEPTH_BELOW_TARGET" in recommendation.signals


class TestRecommendationGuardrails:
    """Regression guardrails against implausible scarcity jumps."""

    def test_blocks_early_round_scarcity_jump(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: an early-round starter and a much later-ranked last-in-tier starter
        WHEN: recommendations are built at pick five
        THEN: scarcity cannot promote the later-ranked player above the plausible draft window
        """
        early_player = make_player(
            rank=6,
            name="Early Round Player",
            position="WR",
            adp=8.1,
            yahoo_player_id=10006,
        )
        scarce_later_player = make_player(
            rank=28,
            name="Scarce Later Player",
            position="QB",
            adp=19.6,
            manual_tier=1,
            yahoo_player_id=10028,
        )

        recommendations = build_candidate_recommendations(
            [
                _evaluation(
                    scarce_later_player,
                    decision_pick=5,
                    following_pick=16,
                    next_tier=2,
                    scarcity_flags=("LAST_IN_TIER",),
                    return_exposure=10,
                ),
                _evaluation(
                    early_player,
                    decision_pick=5,
                    following_pick=16,
                    return_exposure=10,
                ),
            ]
        )

        assert recommendations[0].evaluation.player.name == "Early Round Player"
        assert recommendations[0].desirability == CandidateDesirability.MEDIUM

        assert recommendations[1].evaluation.player.name == "Scarce Later Player"
        assert recommendations[1].desirability == CandidateDesirability.LOW
        assert recommendations[1].loss_cost == LossCost.HIGH

    def test_blocks_late_tier_cliff_jump(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a current-window starter and a later-ranked last-in-tier starter
        WHEN: recommendations are built at pick thirty-six
        THEN: the later tier cliff cannot leapfrog the current draft window
        """
        current_player = make_player(
            rank=26,
            name="Current Window Player",
            position="RB",
            adp=27.1,
            yahoo_player_id=10026,
        )
        later_tier_cliff = make_player(
            rank=47,
            name="Later Tier Cliff",
            position="RB",
            adp=41.2,
            manual_tier=4,
            yahoo_player_id=10047,
        )

        recommendations = build_candidate_recommendations(
            [
                _evaluation(
                    later_tier_cliff,
                    decision_pick=36,
                    following_pick=45,
                    next_tier=5,
                    scarcity_flags=("LAST_IN_TIER",),
                    return_exposure=8,
                ),
                _evaluation(
                    current_player,
                    decision_pick=36,
                    following_pick=45,
                    return_exposure=8,
                ),
            ]
        )

        assert recommendations[0].evaluation.player.name == "Current Window Player"
        assert recommendations[0].desirability == CandidateDesirability.HIGH

        assert recommendations[1].evaluation.player.name == "Later Tier Cliff"
        assert recommendations[1].desirability == CandidateDesirability.MEDIUM

    def test_high_desirability_beats_medium_singleton_scarcity(
        self,
        league_config: LeagueConfig,
        make_draft_pick: Callable[..., DraftPick],
        make_draft_state: Callable[..., DraftState],
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: pick thirteen has elite high-value receivers plus a scarce later-ranked quarterback
        WHEN: the on-clock shortlist is ordered
        THEN: high-desirability value stays ahead of medium-desirability singleton scarcity
        """
        state = make_draft_state(
            my_draft_slot=8,
            current_overall_pick=13,
            picks=[
                make_draft_pick(
                    overall=8,
                    team_id=8,
                    position="WR",
                    player="Amon-Ra St. Brown",
                )
            ],
        )
        candidates = [
            make_player(
                rank=11,
                adp=10.5,
                name="Elite Receiver One",
                position="WR",
                manual_tier=2,
                yahoo_player_id=11,
            ),
            make_player(
                rank=13,
                adp=12.9,
                name="Elite Receiver Two",
                position="WR",
                manual_tier=2,
                yahoo_player_id=13,
            ),
            make_player(
                rank=28,
                adp=19.8,
                name="Scarce Quarterback",
                position="QB",
                manual_tier=1,
                yahoo_player_id=28,
            ),
            make_player(
                rank=61,
                adp=47.0,
                name="Next Quarterback Tier",
                position="QB",
                manual_tier=2,
                yahoo_player_id=61,
            ),
        ]

        recommendations = build_candidate_recommendations(
            evaluate_candidates(candidates, state, league_config),
            limit=4,
        )

        top_names = [
            recommendation.evaluation.player.name for recommendation in recommendations[:2]
        ]
        assert top_names == ["Elite Receiver One", "Elite Receiver Two"]
        assert recommendations[0].desirability == CandidateDesirability.HIGH
        assert recommendations[1].desirability == CandidateDesirability.HIGH
        scarce = next(
            recommendation
            for recommendation in recommendations
            if recommendation.evaluation.player.name == "Scarce Quarterback"
        )
        assert scarce.desirability == CandidateDesirability.MEDIUM
        assert "LAST_IN_TIER" in scarce.signals


class TestMockDraftRegressions:
    """Regression tests from observed 2026 Yahoo mock-draft decisions."""

    def test_pick_32_tier_and_adp_can_beat_small_rank_edge(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: Zay Flowers has the better Yahoo rank but Rashee Rice has better ADP and tier
        WHEN: both receivers are plausible direct starters at pick thirty-two
        THEN: Rice's same-position tier cliff can beat Flowers' small raw-rank edge
        """
        flowers = make_player(
            rank=32,
            name="Zay Flowers",
            position="WR",
            adp=36.2,
            manual_tier=4,
            yahoo_player_id=10032,
        )
        rice = make_player(
            rank=36,
            name="Rashee Rice",
            position="WR",
            adp=34.6,
            manual_tier=3,
            yahoo_player_id=10036,
        )

        recommendations = build_candidate_recommendations(
            [
                _evaluation(
                    flowers,
                    decision_pick=32,
                    following_pick=49,
                    tier_remaining=5,
                    next_tier=5,
                    position_tier_gap=1,
                    return_exposure=16,
                ),
                _evaluation(
                    rice,
                    decision_pick=32,
                    following_pick=49,
                    tier_remaining=1,
                    next_tier=4,
                    position_tier_gap=0,
                    scarcity_flags=("LAST_IN_TIER",),
                    return_exposure=16,
                ),
            ]
        )

        assert recommendations[0].evaluation.player.name == "Rashee Rice"
        assert recommendations[0].desirability == CandidateDesirability.MEDIUM
        assert recommendations[0].loss_cost == LossCost.HIGH
        assert recommendations[1].evaluation.player.name == "Zay Flowers"
        assert recommendations[1].desirability == CandidateDesirability.MEDIUM

    def test_pick_49_waiting_shortlist_includes_open_tight_end(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: several receivers and Tyler Warren are plausible targets before pick forty-nine
        WHEN: the waiting shortlist is limited to five candidates
        THEN: Rank/ADP consensus keeps the open-starter tight end in the decision set
        """
        players = [
            make_player(
                rank=37,
                name="Tetairoa McMillan",
                position="WR",
                adp=41.7,
                manual_tier=5,
                yahoo_player_id=10037,
            ),
            make_player(
                rank=39,
                name="Garrett Wilson",
                position="WR",
                adp=49.4,
                manual_tier=4,
                yahoo_player_id=10039,
            ),
            make_player(
                rank=40,
                name="Ladd McConkey",
                position="WR",
                adp=45.3,
                manual_tier=4,
                yahoo_player_id=10040,
            ),
            make_player(
                rank=42,
                name="Emeka Egbuka",
                position="WR",
                adp=44.0,
                manual_tier=4,
                yahoo_player_id=10042,
            ),
            make_player(
                rank=45,
                name="Luther Burden III",
                position="WR",
                adp=58.8,
                manual_tier=5,
                yahoo_player_id=10045,
            ),
            make_player(
                rank=47,
                name="Tyler Warren",
                position="TE",
                adp=47.2,
                manual_tier=3,
                yahoo_player_id=10047,
            ),
        ]
        evaluations = [
            _evaluation(
                player,
                decision_pick=49,
                following_pick=52,
                is_on_clock=False,
                pre_decision_exposure=8,
            )
            for player in players
        ]

        recommendations = build_candidate_recommendations(evaluations, limit=5)
        names = [recommendation.evaluation.player.name for recommendation in recommendations]

        assert "Tyler Warren" in names
        assert "Luther Burden III" not in names

    def test_pick_109_market_consensus_beats_small_rank_edge(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: Quentin Johnston has a slightly better rank but Alec Pierce has much earlier ADP
        WHEN: otherwise comparable depth receivers are ordered at pick one hundred nine
        THEN: the Rank/ADP consensus prefers Pierce instead of raw Yahoo rank alone
        """
        johnston = make_player(
            rank=95,
            name="Quentin Johnston",
            position="WR",
            adp=109.9,
            manual_tier=8,
            yahoo_player_id=10095,
        )
        pierce = make_player(
            rank=97,
            name="Alec Pierce",
            position="WR",
            adp=92.7,
            manual_tier=8,
            yahoo_player_id=10097,
        )

        recommendations = build_candidate_recommendations(
            [
                _evaluation(
                    johnston,
                    decision_pick=109,
                    following_pick=112,
                    roster_fit=RosterFit.DEPTH,
                    position_depth_need=PositionDepthNeed.LOW,
                    tier_remaining=5,
                    next_tier=9,
                    return_exposure=2,
                ),
                _evaluation(
                    pierce,
                    decision_pick=109,
                    following_pick=112,
                    roster_fit=RosterFit.DEPTH,
                    position_depth_need=PositionDepthNeed.LOW,
                    tier_remaining=5,
                    next_tier=9,
                    return_exposure=2,
                ),
            ]
        )

        assert recommendations[0].evaluation.player.name == "Alec Pierce"
        assert recommendations[1].evaluation.player.name == "Quentin Johnston"

    def test_pick_132_worse_tier_singleton_does_not_beat_best_available_tier(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a Tier-5 defense is last in tier while Tier-1 defenses remain available
        WHEN: defenses are ordered at pick one hundred thirty-two
        THEN: worse-tier scarcity cannot promote the Tier-5 defense above Tier 1
        """
        falcons = make_player(
            rank=262,
            name="Falcons",
            position="DEF",
            adp=132.1,
            manual_tier=5,
            yahoo_player_id=10262,
        )
        broncos = make_player(
            rank=165,
            name="Broncos",
            position="DEF",
            adp=101.1,
            manual_tier=1,
            yahoo_player_id=10165,
        )

        recommendations = build_candidate_recommendations(
            [
                _evaluation(
                    falcons,
                    decision_pick=132,
                    following_pick=149,
                    tier_remaining=1,
                    next_tier=6,
                    position_tier_gap=4,
                    scarcity_flags=("LAST_IN_TIER",),
                    return_exposure=12,
                ),
                _evaluation(
                    broncos,
                    decision_pick=132,
                    following_pick=149,
                    tier_remaining=2,
                    next_tier=2,
                    position_tier_gap=0,
                    scarcity_flags=("LOW_TIER_DEPTH",),
                    return_exposure=12,
                ),
            ]
        )

        assert recommendations[0].evaluation.player.name == "Broncos"
        assert recommendations[1].evaluation.player.name == "Falcons"
        assert recommendations[1].loss_cost == LossCost.MEDIUM

    def test_pick_149_best_available_kicker_tier_breaks_close_market_tie(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: Evan McPherson is in the best available kicker tier while Cairo Santos trails it
        WHEN: otherwise comparable kickers are ordered at pick one hundred forty-nine
        THEN: the position-relative tier gap breaks the close market tie in McPherson's favor
        """
        santos = make_player(
            rank=218,
            name="Cairo Santos",
            position="K",
            adp=144.6,
            manual_tier=4,
            yahoo_player_id=10218,
        )
        mcpherson = make_player(
            rank=221,
            name="Evan McPherson",
            position="K",
            adp=142.6,
            manual_tier=2,
            yahoo_player_id=10221,
        )

        recommendations = build_candidate_recommendations(
            [
                _evaluation(
                    santos,
                    decision_pick=149,
                    following_pick=152,
                    position_tier_gap=2,
                    scarcity_flags=("LOW_TIER_DEPTH",),
                    tier_remaining=2,
                    next_tier=5,
                ),
                _evaluation(
                    mcpherson,
                    decision_pick=149,
                    following_pick=152,
                    position_tier_gap=0,
                    tier_remaining=3,
                    next_tier=3,
                ),
            ]
        )

        assert recommendations[0].evaluation.player.name == "Evan McPherson"
        assert recommendations[1].evaluation.player.name == "Cairo Santos"

    def test_pick_12_waiting_prefers_better_same_position_tier(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: Kenneth Walker and Chase Brown share ADP but Brown is the final available Tier-2 RB
        WHEN: the user is waiting for pick twenty
        THEN: same-position tier quality places Brown ahead of Walker's small Yahoo-rank edge
        """
        walker = make_player(
            rank=12,
            name="Kenneth Walker III",
            position="RB",
            adp=16.3,
            manual_tier=3,
            yahoo_player_id=20012,
        )
        brown = make_player(
            rank=14,
            name="Chase Brown",
            position="RB",
            adp=16.3,
            manual_tier=2,
            yahoo_player_id=20014,
        )

        recommendations = build_candidate_recommendations(
            [
                _evaluation(
                    walker,
                    decision_pick=20,
                    following_pick=21,
                    is_on_clock=False,
                    position_tier_gap=1,
                    tier_remaining=5,
                    next_tier=4,
                    pre_decision_exposure=8,
                ),
                _evaluation(
                    brown,
                    decision_pick=20,
                    following_pick=21,
                    is_on_clock=False,
                    position_tier_gap=0,
                    tier_remaining=1,
                    next_tier=3,
                    scarcity_flags=("LAST_IN_TIER",),
                    pre_decision_exposure=8,
                ),
            ]
        )

        assert [r.evaluation.player.name for r in recommendations] == [
            "Chase Brown",
            "Kenneth Walker III",
        ]

    def test_pick_40_waiting_prefers_rice_over_flowers(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: Rice has better ADP and a better WR tier while Flowers has the better Yahoo rank
        WHEN: the user is preparing for pick forty
        THEN: same-position tier quality keeps Rice ahead inside the same decision band
        """
        flowers = make_player(
            rank=32,
            name="Zay Flowers",
            position="WR",
            adp=36.2,
            manual_tier=4,
            yahoo_player_id=20032,
        )
        rice = make_player(
            rank=36,
            name="Rashee Rice",
            position="WR",
            adp=34.6,
            manual_tier=3,
            yahoo_player_id=20036,
        )

        recommendations = build_candidate_recommendations(
            [
                _evaluation(
                    flowers,
                    decision_pick=40,
                    following_pick=41,
                    is_on_clock=False,
                    position_tier_gap=1,
                    tier_remaining=4,
                    next_tier=5,
                    pre_decision_exposure=4,
                ),
                _evaluation(
                    rice,
                    decision_pick=40,
                    following_pick=41,
                    is_on_clock=False,
                    position_tier_gap=0,
                    tier_remaining=1,
                    next_tier=4,
                    scarcity_flags=("LAST_IN_TIER",),
                    pre_decision_exposure=4,
                ),
            ]
        )

        assert [r.evaluation.player.name for r in recommendations] == [
            "Rashee Rice",
            "Zay Flowers",
        ]

    def test_pick_41_direct_starter_utility_beats_flex_scarcity(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: a scarce FLEX running back competes with a direct-starting wide receiver
        WHEN: both are otherwise plausible on-clock candidates at pick forty-one
        THEN: high direct-starter utility beats low FLEX utility before scarcity breaks the tie
        """
        love = make_player(
            rank=34,
            name="Jeremiyah Love",
            position="RB",
            adp=28.5,
            manual_tier=4,
            yahoo_player_id=20034,
        )
        mcconkey = make_player(
            rank=40,
            name="Ladd McConkey",
            position="WR",
            adp=45.3,
            manual_tier=4,
            yahoo_player_id=20040,
        )

        recommendations = build_candidate_recommendations(
            [
                _evaluation(
                    love,
                    decision_pick=41,
                    following_pick=60,
                    roster_fit=RosterFit.FLEX,
                    other_flex_eligible_starter_slots_open=2,
                    tier_remaining=1,
                    next_tier=5,
                    position_tier_gap=0,
                    scarcity_flags=("LAST_IN_TIER",),
                    return_exposure=18,
                ),
                _evaluation(
                    mcconkey,
                    decision_pick=41,
                    following_pick=60,
                    roster_fit=RosterFit.DIRECT_STARTER,
                    tier_remaining=3,
                    next_tier=5,
                    position_tier_gap=0,
                    return_exposure=18,
                ),
            ]
        )

        assert recommendations[0].evaluation.player.name == "Ladd McConkey"
        assert recommendations[0].roster_utility == RosterUtility.HIGH
        assert recommendations[1].evaluation.player.name == "Jeremiyah Love"
        assert recommendations[1].roster_utility == RosterUtility.LOW

    def test_pick_75_rb_depth_over_wr4(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: the slot-six mock at pick seventy-five with RB2 and WR3
        WHEN: comparable depth candidates are ordered
        THEN: high RB depth need moves Jaylen Warren ahead of Brian Thomas Jr.
        """
        carnell_tate = make_player(
            rank=72,
            name="Carnell Tate",
            position="WR",
            adp=78.7,
            manual_tier=5,
            yahoo_player_id=42626,
        )
        brian_thomas = make_player(
            rank=70,
            name="Brian Thomas Jr.",
            position="WR",
            adp=84.3,
            manual_tier=7,
            yahoo_player_id=40883,
        )
        jaylen_warren = make_player(
            rank=74,
            name="Jaylen Warren",
            position="RB",
            adp=76.8,
            manual_tier=6,
            yahoo_player_id=34447,
        )

        recommendations = build_candidate_recommendations(
            [
                _evaluation(
                    carnell_tate,
                    decision_pick=75,
                    following_pick=86,
                    roster_fit=RosterFit.DEPTH,
                    position_depth_need=PositionDepthNeed.MEDIUM,
                    scarcity_flags=("LOW_TIER_DEPTH",),
                    tier_remaining=2,
                    next_tier=6,
                ),
                _evaluation(
                    brian_thomas,
                    decision_pick=75,
                    following_pick=86,
                    roster_fit=RosterFit.DEPTH,
                    position_depth_need=PositionDepthNeed.MEDIUM,
                    tier_remaining=7,
                    next_tier=8,
                ),
                _evaluation(
                    jaylen_warren,
                    decision_pick=75,
                    following_pick=86,
                    roster_fit=RosterFit.DEPTH,
                    position_depth_need=PositionDepthNeed.HIGH,
                    tier_remaining=5,
                    next_tier=7,
                    return_exposure=2,
                ),
            ]
        )

        names = [recommendation.evaluation.player.name for recommendation in recommendations]

        assert names.index("Jaylen Warren") < names.index("Brian Thomas Jr.")

    def test_pick_86_rb_enters_top_three(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: the slot-six mock at pick eighty-six with RB2 and WR4
        WHEN: the shortlist is ordered
        THEN: viable RB3 depth enters the top three instead of another excess WR
        """
        jordyn_tyson = make_player(
            rank=78,
            name="Jordyn Tyson",
            position="WR",
            adp=91.8,
            manual_tier=8,
            yahoo_player_id=42630,
        )
        josh_downs = make_player(
            rank=82,
            name="Josh Downs",
            position="WR",
            adp=112.7,
            yahoo_player_id=40126,
        )
        stefon_diggs = make_player(
            rank=86,
            name="Stefon Diggs",
            position="WR",
            adp=113.7,
            yahoo_player_id=28534,
        )
        jacory_croskey_merritt = make_player(
            rank=93,
            name="Jacory Croskey-Merritt",
            position="RB",
            adp=115.0,
            manual_tier=8,
            yahoo_player_id=42010,
        )

        recommendations = build_candidate_recommendations(
            [
                _evaluation(
                    jordyn_tyson,
                    decision_pick=86,
                    following_pick=95,
                    roster_fit=RosterFit.DEPTH,
                    position_depth_need=PositionDepthNeed.LOW,
                    scarcity_flags=("LAST_IN_TIER",),
                    tier_remaining=1,
                    next_tier=None,
                ),
                _evaluation(
                    josh_downs,
                    decision_pick=86,
                    following_pick=95,
                    roster_fit=RosterFit.DEPTH,
                    position_depth_need=PositionDepthNeed.LOW,
                ),
                _evaluation(
                    stefon_diggs,
                    decision_pick=86,
                    following_pick=95,
                    roster_fit=RosterFit.DEPTH,
                    position_depth_need=PositionDepthNeed.LOW,
                ),
                _evaluation(
                    jacory_croskey_merritt,
                    decision_pick=86,
                    following_pick=95,
                    roster_fit=RosterFit.DEPTH,
                    position_depth_need=PositionDepthNeed.HIGH,
                    tier_remaining=7,
                    next_tier=9,
                ),
            ],
            limit=3,
        )

        names = [recommendation.evaluation.player.name for recommendation in recommendations]

        assert "Jacory Croskey-Merritt" in names

    def test_pick_95_rb3_over_wr6(
        self,
        make_player: Callable[..., Player],
    ) -> None:
        """
        GIVEN: the slot-six mock at pick ninety-five with RB2 and WR5
        WHEN: Chuba Hubbard and Alec Pierce are compared
        THEN: needed RB3 depth is preferred over additional WR depth
        """
        alec_pierce = make_player(
            rank=91,
            name="Alec Pierce",
            position="WR",
            adp=86.9,
            manual_tier=6,
            yahoo_player_id=34008,
        )
        chuba_hubbard = make_player(
            rank=96,
            name="Chuba Hubbard",
            position="RB",
            adp=78.6,
            manual_tier=5,
            yahoo_player_id=33514,
        )

        recommendations = build_candidate_recommendations(
            [
                _evaluation(
                    alec_pierce,
                    decision_pick=95,
                    following_pick=106,
                    roster_fit=RosterFit.DEPTH,
                    position_depth_need=PositionDepthNeed.LOW,
                    tier_remaining=6,
                    next_tier=7,
                ),
                _evaluation(
                    chuba_hubbard,
                    decision_pick=95,
                    following_pick=106,
                    roster_fit=RosterFit.DEPTH,
                    position_depth_need=PositionDepthNeed.HIGH,
                    scarcity_flags=("LAST_IN_TIER",),
                    tier_remaining=1,
                    next_tier=6,
                ),
            ]
        )

        assert recommendations[0].evaluation.player.name == "Chuba Hubbard"
