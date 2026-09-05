"""Build structured deterministic draft context for downstream decision agents."""

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from .models import AdpPolicy, DraftPreference, DraftState, LeagueConfig
from .recommendations import (
    AvailabilityRisk,
    CandidateDesirability,
    CandidateEvaluation,
    CandidateRecommendation,
    DecisionPriority,
    LossCost,
    PositionDepthNeed,
    ReturnRisk,
    RosterFit,
    RosterUtility,
    build_candidate_recommendations,
)
from .state import (
    get_draftable_roster_size,
    get_next_pick_for_team,
    get_team_open_starter_slots,
    get_team_optional_draft_capacity,
    get_team_position_counts,
    get_team_roster,
    get_total_draft_picks,
    team_for_overall_pick,
)

DEFAULT_DETERMINISTIC_ANCHOR_LIMIT = 5
DEFAULT_ON_CLOCK_MARKET_HORIZON = 10
DEFAULT_TURN_MARKET_HORIZON = 15
DEFAULT_WAITING_MIN_CANDIDATE_LIMIT = 20
DEFAULT_WAITING_TARGET_CANDIDATE_COUNT = 12
DEFAULT_WAITING_UNCERTAINTY_BUFFER = 5
DEFAULT_WAITING_MAX_CANDIDATE_LIMIT = 50
ON_CLOCK_SKILL_POSITION_MINIMUMS = {"RB": 3, "WR": 3, "QB": 2, "TE": 2}
WAITING_SKILL_POSITION_MAXIMUMS = {"RB": 9, "WR": 9, "QB": 5, "TE": 5}
REQUIRED_STARTER_POSITION_OPTION_COUNT = 2
RELEVANT_SPECIALIST_OPTION_COUNT = 1
LATE_DRAFT_SPECIALIST_OPTION_COUNT = 2
LATE_DRAFT_SPECIALIST_COVERAGE_SELECTIONS = 4
DECISION_PACKET_SCHEMA_VERSION = 3


class DecisionPhase(StrEnum):
    """Describe where the user is relative to the next draft decision."""

    WAITING = "WAITING"
    ON_CLOCK = "ON_CLOCK"
    COMPLETE = "COMPLETE"


@dataclass(frozen=True)
class RosterEntry:
    """Represent one user-roster selection inside a decision packet."""

    overall_pick: int
    player: str
    position: str
    yahoo_player_id: int | None


@dataclass(frozen=True)
class DraftDecisionContext:
    """Describe factual league and user-roster context for one draft decision."""

    draft_id: str
    session_type: str
    league_name: str
    teams: int
    my_draft_slot: int
    current_overall_pick: int
    current_drafting_team: int | None
    decision_pick: int | None
    decision_round: int | None
    following_pick: int | None
    following_round: int | None
    phase: DecisionPhase
    consecutive_turn: bool
    total_draft_picks: int
    selections_before_decision: int
    opponent_selections_before_following_pick: int
    remaining_user_selections: int
    optional_draft_capacity: int
    roster: tuple[RosterEntry, ...]
    roster_position_counts: dict[str, int]
    open_starter_slots: dict[str, int]
    roster_requirements: dict[str, int]
    flex_positions: tuple[str, ...]
    position_roster_targets: dict[str, int]
    draft_strategy_name: str
    draft_strategy_as_of: str | None
    draft_preferences: tuple[DraftPreference, ...]
    scoring: dict[str, Any]


@dataclass(frozen=True)
class CandidateDecisionEvidence:
    """Represent deterministic evidence for one AI-visible draft candidate."""

    baseline_rank: int
    yahoo_player_id: int
    name: str
    position: str
    team: str
    bye: int
    rank: int
    adp: float | None
    source_adp: float | None
    adp_policy: AdpPolicy
    adp_override_reason: str | None
    adp_override_as_of: str | None
    drafted_percentage: float | None
    manual_tier: int | None
    market_pick_estimate: float
    roster_fit: RosterFit
    roster_utility: RosterUtility
    position_depth_need: PositionDepthNeed
    tier_remaining: int | None
    next_tier: int | None
    position_tier_gap: int | None
    scarcity_flags: tuple[str, ...]
    adp_value_at_decision: float | None
    pre_decision_position_exposure: int
    return_window_position_exposure: int
    desirability: CandidateDesirability
    availability_risk: AvailabilityRisk
    return_risk: ReturnRisk
    loss_cost: LossCost
    priority: DecisionPriority
    signals: tuple[str, ...]


@dataclass(frozen=True)
class DraftDecisionPacket:
    """Provide a versioned deterministic boundary for downstream AI reasoning."""

    schema_version: int
    context: DraftDecisionContext
    candidates: tuple[CandidateDecisionEvidence, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible dictionary for an eventual model boundary."""
        return asdict(self)


def _build_context(
    state: DraftState,
    league: LeagueConfig,
) -> DraftDecisionContext:
    """Build factual decision context without asking an AI layer to reconstruct it."""
    total_draft_picks = get_total_draft_picks(league)
    decision_pick = get_next_pick_for_team(
        current_overall_pick=state.current_overall_pick,
        team_id=state.my_draft_slot,
        teams=league.teams,
        include_current=True,
        max_overall_pick=total_draft_picks,
    )

    following_pick = None
    if decision_pick is not None:
        following_pick = get_next_pick_for_team(
            current_overall_pick=decision_pick,
            team_id=state.my_draft_slot,
            teams=league.teams,
            include_current=False,
            max_overall_pick=total_draft_picks,
        )

    roster = get_team_roster(state, state.my_draft_slot)
    draftable_roster_size = get_draftable_roster_size(league)
    remaining_user_selections = max(draftable_roster_size - len(roster), 0)

    current_drafting_team = (
        None
        if state.current_overall_pick > total_draft_picks
        else team_for_overall_pick(state.current_overall_pick, league.teams)
    )
    if decision_pick is None:
        phase = DecisionPhase.COMPLETE
    elif decision_pick == state.current_overall_pick:
        phase = DecisionPhase.ON_CLOCK
    else:
        phase = DecisionPhase.WAITING

    selections_before_decision = (
        0 if decision_pick is None else max(decision_pick - state.current_overall_pick, 0)
    )
    opponent_selections_before_following_pick = (
        0
        if decision_pick is None or following_pick is None
        else max(following_pick - decision_pick - 1, 0)
    )

    return DraftDecisionContext(
        draft_id=state.draft_id,
        session_type=state.session_type,
        league_name=league.league_name,
        teams=league.teams,
        my_draft_slot=state.my_draft_slot,
        current_overall_pick=state.current_overall_pick,
        current_drafting_team=current_drafting_team,
        decision_pick=decision_pick,
        decision_round=(
            None if decision_pick is None else ((decision_pick - 1) // league.teams) + 1
        ),
        following_pick=following_pick,
        following_round=(
            None if following_pick is None else ((following_pick - 1) // league.teams) + 1
        ),
        phase=phase,
        consecutive_turn=(
            decision_pick is not None
            and following_pick is not None
            and following_pick == decision_pick + 1
        ),
        total_draft_picks=total_draft_picks,
        selections_before_decision=selections_before_decision,
        opponent_selections_before_following_pick=(opponent_selections_before_following_pick),
        remaining_user_selections=remaining_user_selections,
        optional_draft_capacity=get_team_optional_draft_capacity(
            state,
            league,
            state.my_draft_slot,
        ),
        roster=tuple(
            RosterEntry(
                overall_pick=pick.overall,
                player=pick.player,
                position=pick.position,
                yahoo_player_id=pick.yahoo_player_id,
            )
            for pick in roster
        ),
        roster_position_counts=dict(
            get_team_position_counts(
                state,
                state.my_draft_slot,
            )
        ),
        open_starter_slots=dict(
            get_team_open_starter_slots(
                state,
                league,
                state.my_draft_slot,
            )
        ),
        roster_requirements=dict(league.roster),
        flex_positions=tuple(league.flex_positions),
        position_roster_targets=dict(league.draft_strategy.position_roster_targets),
        draft_strategy_name=league.draft_strategy.strategy_name,
        draft_strategy_as_of=league.draft_strategy.as_of,
        draft_preferences=tuple(league.draft_strategy.preferences),
        scoring=dict(league.scoring),
    )


def _to_candidate_evidence(
    recommendation: CandidateRecommendation,
    *,
    baseline_rank: int,
) -> CandidateDecisionEvidence:
    """Convert one deterministic recommendation into an agent-boundary snapshot."""
    evaluation = recommendation.evaluation
    player = evaluation.player

    return CandidateDecisionEvidence(
        baseline_rank=baseline_rank,
        yahoo_player_id=player.yahoo_player_id,
        name=player.name,
        position=player.position,
        team=player.team,
        bye=player.bye,
        rank=player.rank,
        adp=player.adp,
        source_adp=player.source_adp,
        adp_policy=player.adp_policy,
        adp_override_reason=player.adp_override_reason,
        adp_override_as_of=player.adp_override_as_of,
        drafted_percentage=player.drafted_percentage,
        manual_tier=player.manual_tier,
        market_pick_estimate=evaluation.market_pick_estimate,
        roster_fit=evaluation.roster_fit,
        roster_utility=recommendation.roster_utility,
        position_depth_need=evaluation.position_depth_need,
        tier_remaining=evaluation.tier_remaining,
        next_tier=evaluation.next_tier,
        position_tier_gap=evaluation.position_tier_gap,
        scarcity_flags=evaluation.scarcity_flags,
        adp_value_at_decision=evaluation.adp_value_at_decision,
        pre_decision_position_exposure=(evaluation.pre_decision_position_exposure),
        return_window_position_exposure=(evaluation.return_window_position_exposure),
        desirability=recommendation.desirability,
        availability_risk=recommendation.availability_risk,
        return_risk=recommendation.return_risk,
        loss_cost=recommendation.loss_cost,
        priority=recommendation.priority,
        signals=recommendation.signals,
    )


def _get_market_horizon_limit(context: DraftDecisionContext) -> int:
    """Return how far into current market order the AI candidate frontier should scan."""
    if context.phase == DecisionPhase.WAITING:
        dynamic_limit = (
            context.selections_before_decision
            + DEFAULT_WAITING_TARGET_CANDIDATE_COUNT
            + DEFAULT_WAITING_UNCERTAINTY_BUFFER
        )
        return min(
            DEFAULT_WAITING_MAX_CANDIDATE_LIMIT,
            max(DEFAULT_WAITING_MIN_CANDIDATE_LIMIT, dynamic_limit),
        )

    if context.phase == DecisionPhase.ON_CLOCK and context.consecutive_turn:
        return DEFAULT_TURN_MARKET_HORIZON

    return DEFAULT_ON_CLOCK_MARKET_HORIZON


def _market_order(
    recommendations: list[CandidateRecommendation],
) -> list[CandidateRecommendation]:
    """Order candidates by effective current market timing for horizon selection."""
    return sorted(
        recommendations,
        key=lambda recommendation: (
            recommendation.evaluation.market_pick_estimate,
            recommendation.evaluation.player.rank,
        ),
    )


def _get_skill_position_minimums(context: DraftDecisionContext) -> dict[str, int]:
    """Return skill-position breadth appropriate to the current decision phase."""
    if context.phase != DecisionPhase.WAITING or context.selections_before_decision == 0:
        return dict(ON_CLOCK_SKILL_POSITION_MINIMUMS)

    wait_cycles = (context.selections_before_decision + context.teams - 1) // context.teams
    return {
        "RB": min(
            WAITING_SKILL_POSITION_MAXIMUMS["RB"],
            ON_CLOCK_SKILL_POSITION_MINIMUMS["RB"] + (2 * wait_cycles),
        ),
        "WR": min(
            WAITING_SKILL_POSITION_MAXIMUMS["WR"],
            ON_CLOCK_SKILL_POSITION_MINIMUMS["WR"] + (2 * wait_cycles),
        ),
        "QB": min(
            WAITING_SKILL_POSITION_MAXIMUMS["QB"],
            ON_CLOCK_SKILL_POSITION_MINIMUMS["QB"] + wait_cycles,
        ),
        "TE": min(
            WAITING_SKILL_POSITION_MAXIMUMS["TE"],
            ON_CLOCK_SKILL_POSITION_MINIMUMS["TE"] + wait_cycles,
        ),
    }


def _add_position_minimums(
    selected_ids: set[int],
    recommendations: list[CandidateRecommendation],
    context: DraftDecisionContext,
) -> None:
    """Ensure the AI can compare a minimum number of core skill-position options."""
    ranked_recommendations = sorted(
        recommendations,
        key=lambda recommendation: recommendation.evaluation.player.rank,
    )

    for position, minimum in _get_skill_position_minimums(context).items():
        selected_at_position = sum(
            recommendation.evaluation.player.yahoo_player_id in selected_ids
            and recommendation.evaluation.player.position == position
            for recommendation in recommendations
        )
        if selected_at_position >= minimum:
            continue

        for recommendation in ranked_recommendations:
            player = recommendation.evaluation.player
            if player.position != position or player.yahoo_player_id in selected_ids:
                continue

            selected_ids.add(player.yahoo_player_id)
            selected_at_position += 1
            if selected_at_position >= minimum:
                break


def _add_relevant_specialists(
    selected_ids: set[int],
    recommendations: list[CandidateRecommendation],
    context: DraftDecisionContext,
) -> None:
    """Expose specialist comparisons without promoting them in baseline ordering.

    Earlier in the draft, a K/DEF is supplemented only when deterministic evidence
    already makes that specialist at least plausibly timely. During the final four
    user selections, two options at each still-open specialist starter are always
    exposed so the reasoning layer can compare an intentional early specialist pick
    against bench value without having to guess which K/DEF choices remain.
    """
    late_draft_coverage = (
        context.remaining_user_selections <= LATE_DRAFT_SPECIALIST_COVERAGE_SELECTIONS
    )

    for position in ("DEF", "K"):
        if context.open_starter_slots.get(position, 0) <= 0:
            continue

        target_count = (
            LATE_DRAFT_SPECIALIST_OPTION_COUNT
            if late_draft_coverage
            else RELEVANT_SPECIALIST_OPTION_COUNT
        )
        selected_at_position = sum(
            recommendation.evaluation.player.yahoo_player_id in selected_ids
            and recommendation.evaluation.player.position == position
            for recommendation in recommendations
        )
        if selected_at_position >= target_count:
            continue

        for recommendation in recommendations:
            player = recommendation.evaluation.player
            if player.position != position or player.yahoo_player_id in selected_ids:
                continue
            if not late_draft_coverage and recommendation.desirability == CandidateDesirability.LOW:
                continue

            selected_ids.add(player.yahoo_player_id)
            selected_at_position += 1
            if selected_at_position >= target_count:
                break


def _get_joint_decision_selection_count(context: DraftDecisionContext) -> int:
    """Return how many user selections the current packet is expected to optimize."""
    if context.decision_pick is None:
        return 0

    return 2 if context.consecutive_turn else 1


def _add_required_starter_candidates(
    selected_ids: set[int],
    recommendations: list[CandidateRecommendation],
    context: DraftDecisionContext,
) -> None:
    """Expose required-slot options once optional depth can no longer fill the decision."""
    joint_selections = _get_joint_decision_selection_count(context)
    required_fills = min(
        joint_selections,
        max(joint_selections - max(context.optional_draft_capacity, 0), 0),
    )
    if required_fills == 0:
        return

    ranked_recommendations = sorted(
        recommendations,
        key=lambda recommendation: recommendation.evaluation.player.rank,
    )

    for slot, open_count in context.open_starter_slots.items():
        if open_count <= 0:
            continue

        eligible_positions = set(context.flex_positions) if slot == "FLEX" else {slot}
        target_count = max(
            REQUIRED_STARTER_POSITION_OPTION_COUNT,
            min(open_count, joint_selections),
        )
        selected_at_slot = sum(
            recommendation.evaluation.player.yahoo_player_id in selected_ids
            and recommendation.evaluation.player.position in eligible_positions
            for recommendation in recommendations
        )

        if selected_at_slot >= target_count:
            continue

        for recommendation in ranked_recommendations:
            player = recommendation.evaluation.player
            if player.position not in eligible_positions or player.yahoo_player_id in selected_ids:
                continue

            selected_ids.add(player.yahoo_player_id)
            selected_at_slot += 1
            if selected_at_slot >= target_count:
                break


def _select_phase_aware_candidates(
    ordered: list[CandidateRecommendation],
    context: DraftDecisionContext,
) -> list[CandidateRecommendation]:
    """Select a phase-aware, positionally useful AI candidate frontier."""
    if not ordered:
        return []
    selected_ids = {
        recommendation.evaluation.player.yahoo_player_id
        for recommendation in ordered[:DEFAULT_DETERMINISTIC_ANCHOR_LIMIT]
    }
    market_horizon = _get_market_horizon_limit(context)
    selected_ids.update(
        recommendation.evaluation.player.yahoo_player_id
        for recommendation in _market_order(ordered)[:market_horizon]
    )

    _add_position_minimums(selected_ids, ordered, context)
    _add_relevant_specialists(selected_ids, ordered, context)
    _add_required_starter_candidates(selected_ids, ordered, context)

    return [
        recommendation
        for recommendation in ordered
        if recommendation.evaluation.player.yahoo_player_id in selected_ids
    ]


def build_draft_decision_packet(
    evaluations: list[CandidateEvaluation],
    state: DraftState,
    league: LeagueConfig,
    *,
    candidate_limit: int | None = None,
) -> DraftDecisionPacket:
    """Build a structured phase-aware decision packet for the AI reasoning layer.

    Default packet construction is intentionally phase-aware. ``WAITING`` scans far
    enough beyond the intervening selections to expose plausible future targets, while
    ``ON_CLOCK`` anchors on the deterministic fallback, scans a compact effective-market
    horizon, and supplements underrepresented core skill positions. Consecutive turn
    picks receive a broader market horizon so the model can optimize both selections.

    An explicit ``candidate_limit`` remains available for deterministic tests and
    diagnostics; when provided, it returns the first N ordered recommendations without
    phase-aware supplementation.

    Args:
        evaluations: Deterministic candidate evidence from ``evaluate_candidates``.
        state: Current factual draft state.
        league: Current league and roster configuration.
        candidate_limit: Optional explicit ordered-candidate limit.

    Returns:
        A versioned, JSON-compatible decision packet.

    Raises:
        ValueError: If an explicit ``candidate_limit`` is less than one.
    """
    if candidate_limit is not None and candidate_limit < 1:
        raise ValueError("Decision packet candidate limit must be at least 1.")

    context = _build_context(state, league)
    ordered = (
        build_candidate_recommendations(evaluations, limit=len(evaluations)) if evaluations else []
    )
    baseline_rank_by_player_id = {
        recommendation.evaluation.player.yahoo_player_id: rank
        for rank, recommendation in enumerate(ordered, start=1)
    }

    if candidate_limit is None:
        recommendations = _select_phase_aware_candidates(
            ordered,
            context,
        )
    else:
        recommendations = ordered[:candidate_limit]

    return DraftDecisionPacket(
        schema_version=DECISION_PACKET_SCHEMA_VERSION,
        context=context,
        candidates=tuple(
            _to_candidate_evidence(
                recommendation,
                baseline_rank=baseline_rank_by_player_id[
                    recommendation.evaluation.player.yahoo_player_id
                ],
            )
            for recommendation in recommendations
        ),
    )
