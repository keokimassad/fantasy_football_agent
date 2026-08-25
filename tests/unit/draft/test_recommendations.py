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
    scarcity_flags: tuple[str, ...] = (),
    decision_pick: int = 17,
    following_pick: int = 24,
    tier_remaining: int | None = None,
    next_tier: int | None = None,
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
        tier_remaining=tier_remaining,
        next_tier=next_tier,
        scarcity_flags=scarcity_flags,
        adp_value_at_decision=(None if player.adp is None else decision_pick - player.adp),
        pre_decision_position_exposure=pre_decision_exposure,
        return_window_position_exposure=return_exposure,
        other_flex_eligible_starter_slots_open=(other_flex_eligible_starter_slots_open),
    )


def test_evaluate_candidates_builds_two_decision_horizons(
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


def test_evaluate_candidates_reports_direct_starter_fit(
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


def test_evaluate_candidates_reports_flex_fit_after_direct_slots_are_full(
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


def test_evaluate_candidates_reports_depth_fit_after_flex_is_filled(
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


def test_evaluate_candidates_collects_tier_evidence(
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


def test_evaluate_candidates_calculates_adp_value_at_decision(
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


def test_evaluate_candidates_handles_missing_adp(
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


def test_evaluate_candidates_separates_pre_decision_and_return_exposure(
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


def test_build_candidate_recommendations_marks_high_return_risk(
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


def test_build_candidate_recommendations_marks_low_return_risk(
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


def test_build_candidate_recommendations_preserves_unknown_return_risk(
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


def test_build_candidate_recommendations_uses_rank_when_adp_is_missing(
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


def test_build_candidate_recommendations_separates_tier_loss_from_immediate_urgency(
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: a direct starter who is the final player before a large tier drop but likely to survive
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


def test_build_candidate_recommendations_prioritizes_urgency_before_rank(
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


def test_build_candidate_recommendations_uses_rank_within_same_priority(
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: two candidates with equal priority and return risk
    WHEN: the shortlist is ordered
    THEN: Yahoo rank remains the cross-position tie-breaker
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


def test_build_candidate_recommendations_respects_limit(
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


def test_build_candidate_recommendations_rejects_invalid_limit() -> None:
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


def test_build_candidate_recommendations_prioritizes_tier_loss_over_return_risk(
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


def test_build_candidate_recommendations_marks_replaceable_starter_medium_loss(
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


def test_build_candidate_recommendations_marks_known_tier_cliff_high_loss(
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


def test_build_candidate_recommendations_does_not_invent_unknown_tier_cliff(
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


def test_build_candidate_recommendations_can_wait_on_high_loss_low_return_risk(
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


def test_build_candidate_recommendations_marks_depth_without_scarcity_low_loss(
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


def test_build_candidate_recommendations_penalizes_early_flex_usage(
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


def test_build_candidate_recommendations_values_flex_after_starters_are_filled(
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


def test_build_candidate_recommendations_values_direct_starter_highly(
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


def test_build_candidate_recommendations_prefers_direct_starter_over_early_flex(
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


def test_evaluate_candidates_counts_other_flex_eligible_starter_slots(
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


def test_build_candidate_recommendations_blocks_later_ranked_scarcity_jump(
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


def test_build_candidate_recommendations_blocks_late_tier_cliff_jump(
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
    assert recommendations[1].desirability == CandidateDesirability.LOW


def test_build_candidate_recommendations_uses_waiting_phase_signals(
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


def test_build_candidate_recommendations_does_not_treat_exposure_as_probability(
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


def test_build_candidate_recommendations_marks_market_disagreement_medium_return_risk(
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
