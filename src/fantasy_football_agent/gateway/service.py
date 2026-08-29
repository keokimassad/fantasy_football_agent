"""Build the current deterministic decision packet from an application workspace."""

from fantasy_football_agent.application_paths import ApplicationPaths
from fantasy_football_agent.draft.decision_packet import (
    DraftDecisionPacket,
    build_draft_decision_packet,
)
from fantasy_football_agent.draft.rankings import get_available_players, load_rankings
from fantasy_football_agent.draft.recommendations import evaluate_candidates
from fantasy_football_agent.draft.state import (
    is_draft_complete,
    load_draft_state,
    load_league_config,
    validate_draft_state,
)


def build_current_decision_packet(paths: ApplicationPaths) -> DraftDecisionPacket:
    """Load factual workspace state and build the deterministic AI decision packet.

    Args:
        paths: Workspace-relative application files used by the draft engine.

    Returns:
        The current deterministic decision packet. A completed draft is represented by
        a packet with a ``COMPLETE`` phase and no candidates.
    """
    league = load_league_config(paths.league_config)
    state = load_draft_state(paths.draft_state)
    validate_draft_state(state, league)

    if is_draft_complete(state, league):
        return build_draft_decision_packet([], state, league)

    rankings = load_rankings(paths.rankings)
    available = get_available_players(rankings, state)
    evaluations = evaluate_candidates(available, state, league)

    return build_draft_decision_packet(
        evaluations,
        state,
        league,
    )
