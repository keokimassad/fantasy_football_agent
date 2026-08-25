"""Evaluate deterministic evidence relevant to fantasy-draft candidates."""

from dataclasses import dataclass
from enum import StrEnum

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
    team_for_overall_pick,
)


class RosterFit(StrEnum):
    """Describe how a candidate fits the user's current starting roster."""

    DIRECT_STARTER = "DIRECT_STARTER"
    FLEX = "FLEX"
    DEPTH = "DEPTH"


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


@dataclass(frozen=True)
class CandidateEvaluation:
    """Collect deterministic evidence for one available draft candidate."""

    player: Player
    decision_pick: int
    following_pick: int
    roster_fit: RosterFit
    other_flex_eligible_starter_slots_open: int
    tier_remaining: int | None
    next_tier: int | None
    scarcity_flags: tuple[str, ...]
    adp_value_at_decision: float | None
    pre_decision_position_exposure: int
    return_window_position_exposure: int


@dataclass(frozen=True)
class CandidateRecommendation:
    """Combine candidate facts with transparent deterministic decision signals."""

    evaluation: CandidateEvaluation
    roster_utility: RosterUtility
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


def _get_roster_utility(
    evaluation: CandidateEvaluation,
) -> RosterUtility:
    """Estimate immediate roster-construction utility.

    Direct starters have high utility. FLEX candidates have reduced utility
    while other FLEX-eligible dedicated starter slots remain open. Depth
    candidates have low immediate roster utility.
    """
    if evaluation.roster_fit == RosterFit.DIRECT_STARTER:
        return RosterUtility.HIGH

    if evaluation.roster_fit == RosterFit.FLEX:
        if evaluation.other_flex_eligible_starter_slots_open > 0:
            return RosterUtility.LOW

        return RosterUtility.MEDIUM

    return RosterUtility.LOW


def _get_return_risk(
    evaluation: CandidateEvaluation,
) -> ReturnRisk:
    """Estimate return risk from market timing and opponent exposure.

    This is intentionally a heuristic rather than a probability model.
    """
    adp = evaluation.player.adp

    if adp is None:
        return ReturnRisk.UNKNOWN

    if adp <= evaluation.decision_pick:
        return ReturnRisk.HIGH

    if adp < evaluation.following_pick:
        if evaluation.return_window_position_exposure > 0:
            return ReturnRisk.HIGH

        return ReturnRisk.MEDIUM

    if evaluation.return_window_position_exposure > 0:
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

    if evaluation.roster_fit != RosterFit.DEPTH and (
        large_tier_drop or (last_in_tier and has_known_next_tier)
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

    if evaluation.adp_value_at_decision is not None and evaluation.adp_value_at_decision > 0:
        signals.append("FALLEN_PAST_ADP")

    if evaluation.player.adp is not None and evaluation.player.adp < evaluation.following_pick:
        signals.append("MARKET_EXPECTED_BEFORE_FOLLOWING_PICK")

    if evaluation.return_window_position_exposure > 0:
        signals.append("RETURN_WINDOW_POSITION_PRESSURE")

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
    decision_pick = get_next_pick_for_team(
        current_overall_pick=state.current_overall_pick,
        team_id=state.my_draft_slot,
        teams=league.teams,
        include_current=True,
    )

    following_pick = get_next_pick_for_team(
        current_overall_pick=decision_pick,
        team_id=state.my_draft_slot,
        teams=league.teams,
        include_current=False,
    )

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

    evaluations: list[CandidateEvaluation] = []

    for player in available_players:
        adp_value_at_decision = None if player.adp is None else decision_pick - player.adp

        evaluations.append(
            CandidateEvaluation(
                player=player,
                decision_pick=decision_pick,
                following_pick=following_pick,
                roster_fit=_get_roster_fit(
                    player,
                    state,
                    league,
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
                scarcity_flags=tuple(
                    get_scarcity_flags(
                        available_players,
                        player,
                    )
                ),
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
    """Build an explainable deterministic shortlist.

    Priority, loss cost, and return risk organize candidates before Yahoo rank.
    Yahoo rank remains the cross-position market baseline rather than assigning
    arbitrary numerical weights to position-relative manual tiers.

    Args:
        evaluations: Candidate facts produced by ``evaluate_candidates``.
        limit: Maximum number of candidates to return.

    Returns:
        Candidate recommendations ordered by deterministic decision priority.

    Raises:
        ValueError: If limit is less than one.
    """
    if limit < 1:
        raise ValueError("Recommendation limit must be at least 1.")

    recommendations: list[CandidateRecommendation] = []

    for evaluation in evaluations:
        roster_utility = _get_roster_utility(evaluation)
        return_risk = _get_return_risk(evaluation)
        loss_cost = _get_loss_cost(evaluation)

        recommendations.append(
            CandidateRecommendation(
                evaluation=evaluation,
                roster_utility=roster_utility,
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
        key=lambda recommendation: (
            _PRIORITY_ORDER[recommendation.priority],
            _ROSTER_UTILITY_ORDER[recommendation.roster_utility],
            _LOSS_COST_ORDER[recommendation.loss_cost],
            _RETURN_RISK_ORDER[recommendation.return_risk],
            recommendation.evaluation.player.rank,
        ),
    )[:limit]
