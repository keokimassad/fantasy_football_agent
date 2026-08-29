"""Build structured deterministic draft context for downstream decision agents."""

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from .models import DraftState, LeagueConfig
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

DEFAULT_AGENT_CANDIDATE_LIMIT = 15
DECISION_PACKET_SCHEMA_VERSION = 1


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
    following_pick: int | None
    phase: DecisionPhase
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
    scoring: dict[str, Any]


@dataclass(frozen=True)
class CandidateDecisionEvidence:
    """Represent deterministic evidence for one AI-visible draft candidate."""

    yahoo_player_id: int
    name: str
    position: str
    team: str
    bye: int
    rank: int
    adp: float | None
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
        following_pick=following_pick,
        phase=phase,
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
        scoring=dict(league.scoring),
    )


def _to_candidate_evidence(
    recommendation: CandidateRecommendation,
) -> CandidateDecisionEvidence:
    """Convert one deterministic recommendation into an agent-boundary snapshot."""
    evaluation = recommendation.evaluation
    player = evaluation.player

    return CandidateDecisionEvidence(
        yahoo_player_id=player.yahoo_player_id,
        name=player.name,
        position=player.position,
        team=player.team,
        bye=player.bye,
        rank=player.rank,
        adp=player.adp,
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


def build_draft_decision_packet(
    evaluations: list[CandidateEvaluation],
    state: DraftState,
    league: LeagueConfig,
    *,
    candidate_limit: int = DEFAULT_AGENT_CANDIDATE_LIMIT,
) -> DraftDecisionPacket:
    """Build a broader structured decision packet for a future AI agent.

    The packet deliberately consumes deterministic candidate evaluations instead of
    rankings, raw Yahoo text, or CLI output. This preserves the draft engine as the
    source of truth while giving a downstream model more context than the five-name
    human shortlist.

    Args:
        evaluations: Deterministic candidate evidence from ``evaluate_candidates``.
        state: Current factual draft state.
        league: Current league and roster configuration.
        candidate_limit: Maximum ordered candidates exposed to the downstream agent.

    Returns:
        A versioned, JSON-compatible decision packet.

    Raises:
        ValueError: If ``candidate_limit`` is less than one.
    """
    if candidate_limit < 1:
        raise ValueError("Decision packet candidate limit must be at least 1.")

    recommendations = build_candidate_recommendations(
        evaluations,
        limit=candidate_limit,
    )

    return DraftDecisionPacket(
        schema_version=DECISION_PACKET_SCHEMA_VERSION,
        context=_build_context(state, league),
        candidates=tuple(
            _to_candidate_evidence(recommendation) for recommendation in recommendations
        ),
    )
