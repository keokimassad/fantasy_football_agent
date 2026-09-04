"""Evaluate deterministic evidence relevant to fantasy-draft candidates."""

from dataclasses import dataclass
from enum import StrEnum
from functools import cmp_to_key

from .analysis import get_position_exposure
from .models import DraftState, LeagueConfig, Player
from .rankings import (
    get_scarcity_flags,
    next_position_tier,
    remaining_in_player_tier,
)
from .state import (
    get_next_pick_for_team,
    get_team_context_for_picks,
    get_team_open_starter_slots,
    get_team_optional_draft_capacity,
    get_team_position_counts,
    get_total_draft_picks,
    team_for_overall_pick,
)


class RosterFit(StrEnum):
    """Describe how a candidate fits the user's current starting roster."""

    DIRECT_STARTER = "DIRECT_STARTER"
    FLEX = "FLEX"
    DEPTH = "DEPTH"


class PositionDepthNeed(StrEnum):
    """Describe how strongly the roster still needs depth at a position."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ReturnRisk(StrEnum):
    """Describe the deterministic risk that a player will not return."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class DecisionPriority(StrEnum):
    """Describe how urgently a candidate deserves consideration."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class LossCost(StrEnum):
    """Describe the cost of losing a candidate before the following pick."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class RosterUtility(StrEnum):
    """Describe the candidate's immediate value to current roster construction."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class CandidateDesirability(StrEnum):
    """Describe whether a candidate is a plausible selection in the current draft window."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class AvailabilityRisk(StrEnum):
    """Describe the risk that a candidate disappears before the user's decision pick."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class CandidateEvaluation:
    """Collect deterministic evidence for one available draft candidate."""

    player: Player
    decision_pick: int
    following_pick: int
    is_on_clock: bool
    roster_fit: RosterFit
    position_depth_need: PositionDepthNeed
    other_flex_eligible_starter_slots_open: int
    tier_remaining: int | None
    next_tier: int | None
    position_tier_gap: int | None
    scarcity_flags: tuple[str, ...]
    market_pick_estimate: float
    adp_value_at_decision: float | None
    pre_decision_position_exposure: int
    return_window_position_exposure: int


@dataclass(frozen=True)
class CandidateRecommendation:
    """Combine candidate facts with transparent deterministic decision signals."""

    evaluation: CandidateEvaluation
    desirability: CandidateDesirability
    roster_utility: RosterUtility
    availability_risk: AvailabilityRisk
    return_risk: ReturnRisk
    loss_cost: LossCost
    priority: DecisionPriority
    signals: tuple[str, ...]


def _build_pick_window(
    start: int,
    stop: int,
    teams: int,
) -> list[tuple[int, int]]:
    """Return overall-pick and team-ID pairs in a half-open draft window."""
    return [
        (
            overall_pick,
            team_for_overall_pick(
                overall_pick,
                teams,
            ),
        )
        for overall_pick in range(start, stop)
    ]


def _get_roster_fit(
    player: Player,
    state: DraftState,
    league: LeagueConfig,
) -> RosterFit:
    """Classify whether a candidate fills a starter, FLEX, or depth role."""
    open_slots = get_team_open_starter_slots(
        state,
        league,
        state.my_draft_slot,
    )

    if open_slots.get(player.position, 0) > 0:
        return RosterFit.DIRECT_STARTER

    if player.position in league.flex_positions and open_slots.get("FLEX", 0) > 0:
        return RosterFit.FLEX

    return RosterFit.DEPTH


def _get_position_depth_need(
    player: Player,
    state: DraftState,
    league: LeagueConfig,
    roster_fit: RosterFit,
) -> PositionDepthNeed:
    """Classify how far the roster remains below its position target."""
    if roster_fit != RosterFit.DEPTH:
        return PositionDepthNeed.NOT_APPLICABLE

    position_counts = get_team_position_counts(
        state,
        state.my_draft_slot,
    )
    current_count = position_counts.get(player.position, 0)
    target_count = league.draft_strategy.position_roster_targets[player.position]

    remaining_to_target = max(
        target_count - current_count,
        0,
    )

    if remaining_to_target >= 2:
        return PositionDepthNeed.HIGH

    if remaining_to_target == 1:
        return PositionDepthNeed.MEDIUM

    return PositionDepthNeed.LOW


def _get_roster_utility(
    evaluation: CandidateEvaluation,
) -> RosterUtility:
    """Estimate immediate roster-construction utility.

    Direct starters have high utility. FLEX candidates have reduced utility
    while other FLEX-eligible dedicated starter slots remain open. Bench depth
    has medium utility while its position remains below the configured roster
    target and low utility after that target is reached.
    """
    if evaluation.roster_fit == RosterFit.DIRECT_STARTER:
        return RosterUtility.HIGH

    if evaluation.roster_fit == RosterFit.FLEX:
        if evaluation.other_flex_eligible_starter_slots_open > 0:
            return RosterUtility.LOW

        return RosterUtility.MEDIUM

    if evaluation.position_depth_need in {
        PositionDepthNeed.HIGH,
        PositionDepthNeed.MEDIUM,
    }:
        return RosterUtility.MEDIUM

    return RosterUtility.LOW


def _get_market_pick_estimate(player: Player) -> float:
    """Return a transparent Rank/ADP consensus estimate for draft-window ordering.

    Yahoo rank and ADP are treated as independent market observations. When both are
    available, their midpoint prevents either source from owning the draft-window
    boundary by itself. Yahoo rank remains the fallback when ADP is unavailable.
    """
    if player.adp is None:
        return float(player.rank)

    return (player.rank + player.adp) / 2


def _get_position_tier_gap(
    available_players: list[Player],
    player: Player,
) -> int | None:
    """Return how many manual tiers trail the best available tier at the position.

    The value is position-relative. A gap of zero means the candidate is in the best
    currently available manual tier for that position. Untiered candidates remain
    unknown rather than being treated as worse than tiered candidates.
    """
    if player.manual_tier is None:
        return None

    available_tiers = [
        candidate.manual_tier
        for candidate in available_players
        if candidate.position == player.position and candidate.manual_tier is not None
    ]
    if not available_tiers:
        return None

    return max(player.manual_tier - min(available_tiers), 0)


def _get_candidate_desirability(
    evaluation: CandidateEvaluation,
    roster_utility: RosterUtility,
) -> CandidateDesirability:
    """Classify cross-position plausibility from market consensus and roster utility.

    The Rank/ADP midpoint is the deterministic cross-position guardrail. Scarcity,
    same-position tier quality, and return risk may reorder candidates inside a
    plausible market window, but cannot independently promote a substantially later
    player over clearly earlier market value.
    """
    market_pick_estimate = evaluation.market_pick_estimate

    if market_pick_estimate <= evaluation.decision_pick:
        if roster_utility == RosterUtility.HIGH:
            return CandidateDesirability.HIGH

        return CandidateDesirability.MEDIUM

    if market_pick_estimate <= evaluation.following_pick and roster_utility != RosterUtility.LOW:
        return CandidateDesirability.MEDIUM

    return CandidateDesirability.LOW


def _get_availability_risk(
    evaluation: CandidateEvaluation,
) -> AvailabilityRisk:
    """Estimate whether a player survives until the user's decision pick."""
    if evaluation.is_on_clock:
        return AvailabilityRisk.NOT_APPLICABLE

    rank_expected = evaluation.player.rank <= evaluation.decision_pick
    adp = evaluation.player.adp

    if adp is None:
        if rank_expected:
            return AvailabilityRisk.MEDIUM

        return AvailabilityRisk.UNKNOWN

    adp_expected = adp <= evaluation.decision_pick

    if rank_expected and adp_expected:
        return AvailabilityRisk.HIGH

    if rank_expected or adp_expected:
        return AvailabilityRisk.MEDIUM

    return AvailabilityRisk.LOW


def _get_return_risk(
    evaluation: CandidateEvaluation,
) -> ReturnRisk:
    """Estimate return risk from Yahoo rank and ADP market timing.

    Rank and ADP provide independent market signals. Opponent positional exposure
    remains useful supporting evidence, but it is not treated as selection
    probability until the model has position-specific opponent behavior.
    """
    rank_expected = evaluation.player.rank <= evaluation.following_pick
    adp = evaluation.player.adp

    if adp is None:
        if rank_expected:
            return ReturnRisk.MEDIUM

        return ReturnRisk.UNKNOWN

    adp_expected = adp <= evaluation.following_pick

    if rank_expected and adp_expected:
        return ReturnRisk.HIGH

    if rank_expected or adp_expected:
        return ReturnRisk.MEDIUM

    return ReturnRisk.LOW


def _get_loss_cost(
    evaluation: CandidateEvaluation,
) -> LossCost:
    """Estimate how costly it would be for a candidate to disappear.

    Loss cost describes replacement quality rather than disappearance
    probability. Tier cliffs and roster fit increase the cost of waiting.
    """
    last_in_tier = "LAST_IN_TIER" in evaluation.scarcity_flags
    large_tier_drop = "LARGE_TIER_DROP" in evaluation.scarcity_flags
    has_known_next_tier = evaluation.next_tier is not None
    is_best_available_position_tier = evaluation.position_tier_gap in {None, 0}

    if (
        evaluation.roster_fit != RosterFit.DEPTH
        and is_best_available_position_tier
        and (large_tier_drop or (last_in_tier and has_known_next_tier))
    ):
        return LossCost.HIGH

    if evaluation.roster_fit in {
        RosterFit.DIRECT_STARTER,
        RosterFit.FLEX,
    } or bool(evaluation.scarcity_flags):
        return LossCost.MEDIUM

    return LossCost.LOW


def _get_other_flex_eligible_starter_slots_open(
    player: Player,
    state: DraftState,
    league: LeagueConfig,
) -> int:
    """Count open dedicated starter slots at other FLEX-eligible positions."""
    open_slots = get_team_open_starter_slots(
        state,
        league,
        state.my_draft_slot,
    )

    return sum(
        open_slots.get(position, 0)
        for position in league.flex_positions
        if position != player.position
    )


def _get_recommendation_signals(
    evaluation: CandidateEvaluation,
) -> tuple[str, ...]:
    """Return stable, explainable signals supporting a candidate decision."""
    signals: list[str] = []

    if evaluation.roster_fit == RosterFit.DIRECT_STARTER:
        signals.append("FILLS_DIRECT_STARTER")
    elif evaluation.roster_fit == RosterFit.FLEX:
        signals.append("FILLS_FLEX")

    signals.extend(evaluation.scarcity_flags)

    if evaluation.is_on_clock:
        if evaluation.adp_value_at_decision is not None and evaluation.adp_value_at_decision > 0:
            signals.append("FALLEN_PAST_ADP")
        if evaluation.player.adp is not None and evaluation.player.adp <= evaluation.following_pick:
            signals.append("MARKET_EXPECTED_BEFORE_FOLLOWING_PICK")
        if evaluation.return_window_position_exposure > 0:
            signals.append("RETURN_WINDOW_POSITION_PRESSURE")
    else:
        if evaluation.adp_value_at_decision is not None and evaluation.adp_value_at_decision > 0:
            signals.append("VALUE_IF_AVAILABLE_AT_DECISION")
        if evaluation.pre_decision_position_exposure > 0:
            signals.append("PRE_DECISION_POSITION_PRESSURE")

    if evaluation.position_depth_need == PositionDepthNeed.HIGH:
        signals.append("HIGH_POSITION_DEPTH_NEED")
    elif evaluation.position_depth_need == PositionDepthNeed.MEDIUM:
        signals.append("POSITION_DEPTH_BELOW_TARGET")

    return tuple(signals)


def _get_decision_priority(
    evaluation: CandidateEvaluation,
    roster_utility: RosterUtility,
    return_risk: ReturnRisk,
    loss_cost: LossCost,
) -> DecisionPriority:
    """Combine roster utility, return risk, and loss cost into decision urgency."""
    if roster_utility == RosterUtility.LOW:
        if loss_cost == LossCost.HIGH and return_risk == ReturnRisk.HIGH:
            return DecisionPriority.HIGH

        if loss_cost != LossCost.LOW or return_risk != ReturnRisk.LOW:
            return DecisionPriority.MEDIUM

        return DecisionPriority.LOW

    if loss_cost == LossCost.HIGH and return_risk in {
        ReturnRisk.HIGH,
        ReturnRisk.MEDIUM,
    }:
        return DecisionPriority.HIGH

    if loss_cost == LossCost.MEDIUM and return_risk == ReturnRisk.HIGH:
        return DecisionPriority.HIGH

    if loss_cost == LossCost.HIGH or return_risk == ReturnRisk.HIGH:
        return DecisionPriority.MEDIUM

    if (
        loss_cost == LossCost.MEDIUM
        or return_risk == ReturnRisk.MEDIUM
        or evaluation.roster_fit != RosterFit.DEPTH
    ):
        return DecisionPriority.MEDIUM

    return DecisionPriority.LOW


def _adp_sort_value(player: Player) -> float:
    """Return ADP for deterministic tie-breaking, with missing ADP sorted last."""
    return float("inf") if player.adp is None else player.adp


def _position_tier_gap_sort_value(evaluation: CandidateEvaluation) -> int:
    """Return a neutral tier-gap sort value when manual tier evidence is unknown."""
    return 0 if evaluation.position_tier_gap is None else evaluation.position_tier_gap


def _compare_ordered_values(left: tuple[int | float, ...], right: tuple[int | float, ...]) -> int:
    """Compare two deterministic sort tuples using normal ascending order."""
    return (left > right) - (left < right)


def _recommendation_compare(
    left: CandidateRecommendation,
    right: CandidateRecommendation,
) -> int:
    """Compare recommendations without treating manual tiers as cross-position scores.

    Broad cross-position ordering is still driven by desirability, roster utility, and
    market evidence. Once two candidates at the same position are otherwise in the same
    decision band, position-relative tier quality is allowed to break the tie before the
    small Rank/ADP differences that produced several mock-draft regressions.
    """
    left_evaluation = left.evaluation
    right_evaluation = right.evaluation

    left_prefix: tuple[int, ...]
    right_prefix: tuple[int, ...]

    if not left_evaluation.is_on_clock:
        left_prefix = (
            _DESIRABILITY_GUARDRAIL_ORDER[left.desirability],
            _DESIRABILITY_ORDER[left.desirability],
            _ROSTER_UTILITY_ORDER[left.roster_utility],
            _POSITION_DEPTH_NEED_ORDER[left_evaluation.position_depth_need],
        )
        right_prefix = (
            _DESIRABILITY_GUARDRAIL_ORDER[right.desirability],
            _DESIRABILITY_ORDER[right.desirability],
            _ROSTER_UTILITY_ORDER[right.roster_utility],
            _POSITION_DEPTH_NEED_ORDER[right_evaluation.position_depth_need],
        )
    else:
        left_prefix = _on_clock_sort_prefix(left)
        right_prefix = _on_clock_sort_prefix(right)

    prefix_comparison = _compare_ordered_values(left_prefix, right_prefix)
    if prefix_comparison:
        return prefix_comparison

    if left_evaluation.player.position == right_evaluation.player.position:
        tier_comparison = _compare_ordered_values(
            (_position_tier_gap_sort_value(left_evaluation),),
            (_position_tier_gap_sort_value(right_evaluation),),
        )
        if tier_comparison:
            return tier_comparison

    left_market = (
        left_evaluation.market_pick_estimate,
        _adp_sort_value(left_evaluation.player),
        left_evaluation.player.rank,
    )
    right_market = (
        right_evaluation.market_pick_estimate,
        _adp_sort_value(right_evaluation.player),
        right_evaluation.player.rank,
    )
    return _compare_ordered_values(left_market, right_market)


def _on_clock_sort_prefix(
    recommendation: CandidateRecommendation,
) -> tuple[int, ...]:
    """Return the phase-aware on-clock ordering prefix for one candidate.

    HIGH and MEDIUM desirability already establish that a player belongs in the
    current market window, so roster utility and replacement cost can lead the
    within-window comparison. LOW desirability means market timing has not yet
    justified the selection; return risk therefore becomes the first secondary
    signal before roster fit or scarcity can manufacture urgency.
    """
    evaluation = recommendation.evaluation

    if recommendation.desirability == CandidateDesirability.LOW:
        return (
            _DESIRABILITY_ORDER[recommendation.desirability],
            _RETURN_RISK_ORDER[recommendation.return_risk],
            _ROSTER_UTILITY_ORDER[recommendation.roster_utility],
            _PRIORITY_ORDER[recommendation.priority],
            _LOSS_COST_ORDER[recommendation.loss_cost],
            _POSITION_DEPTH_NEED_ORDER[evaluation.position_depth_need],
        )

    return (
        _DESIRABILITY_ORDER[recommendation.desirability],
        _ROSTER_UTILITY_ORDER[recommendation.roster_utility],
        _PRIORITY_ORDER[recommendation.priority],
        _LOSS_COST_ORDER[recommendation.loss_cost],
        _POSITION_DEPTH_NEED_ORDER[evaluation.position_depth_need],
        _RETURN_RISK_ORDER[recommendation.return_risk],
    )


_PRIORITY_ORDER = {
    DecisionPriority.HIGH: 0,
    DecisionPriority.MEDIUM: 1,
    DecisionPriority.LOW: 2,
}

_RETURN_RISK_ORDER = {
    ReturnRisk.HIGH: 0,
    ReturnRisk.MEDIUM: 1,
    ReturnRisk.UNKNOWN: 2,
    ReturnRisk.LOW: 3,
}


_LOSS_COST_ORDER = {
    LossCost.HIGH: 0,
    LossCost.MEDIUM: 1,
    LossCost.LOW: 2,
}


_ROSTER_UTILITY_ORDER = {
    RosterUtility.HIGH: 0,
    RosterUtility.MEDIUM: 1,
    RosterUtility.LOW: 2,
}


_DESIRABILITY_GUARDRAIL_ORDER = {
    CandidateDesirability.HIGH: 0,
    CandidateDesirability.MEDIUM: 0,
    CandidateDesirability.LOW: 1,
}

_DESIRABILITY_ORDER = {
    CandidateDesirability.HIGH: 0,
    CandidateDesirability.MEDIUM: 1,
    CandidateDesirability.LOW: 2,
}


_POSITION_DEPTH_NEED_ORDER = {
    PositionDepthNeed.NOT_APPLICABLE: 0,
    PositionDepthNeed.HIGH: 0,
    PositionDepthNeed.MEDIUM: 1,
    PositionDepthNeed.LOW: 2,
}


def evaluate_candidates(
    available_players: list[Player],
    state: DraftState,
    league: LeagueConfig,
) -> list[CandidateEvaluation]:
    """Build deterministic decision evidence for every available player.

    The decision pick is the user's next selection, including the current pick
    when the user is already on the clock. The following pick is the user's next
    selection after that decision.

    Exposure before the decision describes how much positional demand exists
    before the user can select the player. Return-window exposure describes the
    demand after the decision if the user passes and waits for the following turn.

    Args:
        available_players: Currently undrafted ranked players.
        state: Current draft session state.
        league: League settings defining draft order and roster construction.

    Returns:
        Candidate evaluations preserving the input ranking order.
    """
    final_pick = get_total_draft_picks(league)
    decision_pick = get_next_pick_for_team(
        current_overall_pick=state.current_overall_pick,
        team_id=state.my_draft_slot,
        teams=league.teams,
        include_current=True,
        max_overall_pick=final_pick,
    )

    if decision_pick is None:
        return []

    next_user_pick = get_next_pick_for_team(
        current_overall_pick=decision_pick,
        team_id=state.my_draft_slot,
        teams=league.teams,
        include_current=False,
        max_overall_pick=final_pick,
    )
    following_pick = next_user_pick if next_user_pick is not None else final_pick + 1

    pre_decision_picks = _build_pick_window(
        state.current_overall_pick,
        decision_pick,
        league.teams,
    )

    return_window_picks = _build_pick_window(
        decision_pick + 1,
        following_pick,
        league.teams,
    )

    pre_decision_context = get_team_context_for_picks(
        state,
        league,
        pre_decision_picks,
    )
    return_window_context = get_team_context_for_picks(
        state,
        league,
        return_window_picks,
    )

    pre_decision_exposure = get_position_exposure(
        league,
        pre_decision_context,
    )
    return_window_exposure = get_position_exposure(
        league,
        return_window_context,
    )

    is_on_clock = (
        team_for_overall_pick(
            state.current_overall_pick,
            league.teams,
        )
        == state.my_draft_slot
    )

    optional_draft_capacity = get_team_optional_draft_capacity(
        state,
        league,
        state.my_draft_slot,
    )

    if optional_draft_capacity < 0:
        raise ValueError("Draft state cannot fill every remaining required starter slot.")

    evaluations: list[CandidateEvaluation] = []

    for player in available_players:
        adp_value_at_decision = None if player.adp is None else decision_pick - player.adp
        roster_fit = _get_roster_fit(
            player,
            state,
            league,
        )

        if optional_draft_capacity == 0 and roster_fit == RosterFit.DEPTH:
            continue

        evaluations.append(
            CandidateEvaluation(
                player=player,
                decision_pick=decision_pick,
                following_pick=following_pick,
                is_on_clock=is_on_clock,
                roster_fit=roster_fit,
                position_depth_need=_get_position_depth_need(
                    player,
                    state,
                    league,
                    roster_fit,
                ),
                other_flex_eligible_starter_slots_open=(
                    _get_other_flex_eligible_starter_slots_open(
                        player,
                        state,
                        league,
                    )
                ),
                tier_remaining=remaining_in_player_tier(
                    available_players,
                    player,
                ),
                next_tier=next_position_tier(
                    available_players,
                    player,
                ),
                position_tier_gap=_get_position_tier_gap(
                    available_players,
                    player,
                ),
                scarcity_flags=tuple(
                    get_scarcity_flags(
                        available_players,
                        player,
                    )
                ),
                market_pick_estimate=_get_market_pick_estimate(player),
                adp_value_at_decision=adp_value_at_decision,
                pre_decision_position_exposure=(
                    pre_decision_exposure[player.position].selection_chances
                ),
                return_window_position_exposure=(
                    return_window_exposure[player.position].selection_chances
                ),
            )
        )

    return evaluations


def build_candidate_recommendations(
    evaluations: list[CandidateEvaluation],
    *,
    limit: int = 5,
) -> list[CandidateRecommendation]:
    """Build an explainable phase-aware deterministic shortlist.

    Candidate desirability provides a cross-position guardrail using transparent
    Yahoo Rank/ADP market consensus plus roster utility. Within a plausible market
    window, roster utility and replacement cost lead the comparison. For LOW
    desirability candidates, return risk leads the secondary ordering so an empty
    starter slot or tier cliff cannot manufacture early urgency without timing evidence.

    Args:
        evaluations: Candidate facts produced by ``evaluate_candidates``.
        limit: Maximum number of candidates to return.

    Returns:
        Candidate recommendations ordered for the current draft phase.

    Raises:
        ValueError: If limit is less than one.
    """
    if limit < 1:
        raise ValueError("Recommendation limit must be at least 1.")

    recommendations: list[CandidateRecommendation] = []

    for evaluation in evaluations:
        roster_utility = _get_roster_utility(evaluation)
        desirability = _get_candidate_desirability(
            evaluation,
            roster_utility,
        )
        availability_risk = _get_availability_risk(evaluation)
        return_risk = _get_return_risk(evaluation)
        loss_cost = _get_loss_cost(evaluation)

        recommendations.append(
            CandidateRecommendation(
                evaluation=evaluation,
                desirability=desirability,
                roster_utility=roster_utility,
                availability_risk=availability_risk,
                return_risk=return_risk,
                loss_cost=loss_cost,
                priority=_get_decision_priority(
                    evaluation,
                    roster_utility,
                    return_risk,
                    loss_cost,
                ),
                signals=_get_recommendation_signals(evaluation),
            )
        )

    return sorted(
        recommendations,
        key=cmp_to_key(_recommendation_compare),
    )[:limit]
