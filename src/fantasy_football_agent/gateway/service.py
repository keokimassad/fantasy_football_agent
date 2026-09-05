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
from fantasy_football_agent.draft.sync_status import (
    DraftStateStaleError,
    require_fresh_draft_state,
)
from fantasy_football_agent.observability import (
    record_decision_blocked,
    record_decision_packet,
)


def build_current_decision_packet(
    paths: ApplicationPaths,
    *,
    log_source: str | None = None,
) -> DraftDecisionPacket:
    """Load factual workspace state and build the deterministic AI decision packet.

    Args:
        paths: Workspace-relative application files used by the draft engine.
        log_source: Optional provenance label used when logging the generated packet.

    Returns:
        The current deterministic decision packet. A completed draft is represented by
        a packet with a ``COMPLETE`` phase and no candidates.
    """
    league = load_league_config(
        paths.league_config,
        draft_strategy_path=paths.draft_strategy,
    )
    state = load_draft_state(paths.draft_state)
    validate_draft_state(state, league)
    try:
        require_fresh_draft_state(paths.draft_sync_status, state)
    except DraftStateStaleError as error:
        if log_source is not None:
            record_decision_blocked(
                paths,
                state,
                source=log_source,
                reason=error.failure.message,
            )
        raise

    if is_draft_complete(state, league):
        packet = build_draft_decision_packet([], state, league)
        if log_source is not None:
            record_decision_packet(paths, state, packet, source=log_source)
        return packet

    rankings = load_rankings(paths.rankings, paths.player_overrides)
    available = get_available_players(rankings, state)
    evaluations = evaluate_candidates(available, state, league)

    packet = build_draft_decision_packet(
        evaluations,
        state,
        league,
    )
    if log_source is not None:
        record_decision_packet(paths, state, packet, source=log_source)
    return packet
