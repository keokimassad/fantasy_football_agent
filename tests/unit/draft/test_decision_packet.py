"""Unit tests for the deterministic AI decision-packet boundary."""

import json
from collections.abc import Callable

import pytest

from fantasy_football_agent.draft.decision_packet import (
    DECISION_PACKET_SCHEMA_VERSION,
    DecisionPhase,
    build_draft_decision_packet,
)
from fantasy_football_agent.draft.models import DraftPick, DraftState, LeagueConfig, Player
from fantasy_football_agent.draft.recommendations import (
    RosterFit,
    evaluate_candidates,
)

pytestmark = pytest.mark.unit


def test_packet_contains_factual_context_and_broader_candidate_set(
    league_config: LeagueConfig,
    make_draft_pick: Callable[..., DraftPick],
    make_draft_state: Callable[..., DraftState],
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: an on-clock user with one drafted running back and twenty available players
    WHEN: a decision packet is built with the default broader candidate limit
    THEN: the packet exposes factual roster context and fifteen ordered candidates
    """
    state = make_draft_state(
        my_draft_slot=4,
        current_overall_pick=4,
        picks=[
            make_draft_pick(
                overall=1,
                team_id=4,
                position="RB",
                player="Roster RB",
            )
        ],
    )
    players = [
        make_player(
            rank=rank,
            adp=float(rank),
            name=f"Candidate {rank}",
            position="WR",
            yahoo_player_id=20000 + rank,
            manual_tier=1 + ((rank - 1) // 5),
        )
        for rank in range(1, 21)
    ]
    evaluations = evaluate_candidates(players, state, league_config)

    packet = build_draft_decision_packet(evaluations, state, league_config)

    assert packet.schema_version == DECISION_PACKET_SCHEMA_VERSION
    assert packet.context.current_drafting_team == 4
    assert packet.context.decision_pick == 4
    assert packet.context.following_pick == 17
    assert packet.context.phase == DecisionPhase.ON_CLOCK
    assert packet.context.roster[0].player == "Roster RB"
    assert packet.context.roster_position_counts == {"RB": 1}
    assert packet.context.open_starter_slots["RB"] == 1
    assert packet.context.open_starter_slots["WR"] == 2
    assert len(packet.candidates) == 15


def test_packet_preserves_deterministic_candidate_evidence(
    league_config: LeagueConfig,
    make_draft_state: Callable[..., DraftState],
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: a tiered receiver with market and roster evidence
    WHEN: the candidate is converted into a decision packet
    THEN: the packet preserves typed deterministic evidence instead of flattening it into prose
    """
    state = make_draft_state(
        my_draft_slot=4,
        current_overall_pick=4,
    )
    player = make_player(
        rank=8,
        adp=10.0,
        name="Tiered Receiver",
        position="WR",
        manual_tier=3,
        yahoo_player_id=22008,
    )
    evaluations = evaluate_candidates([player], state, league_config)

    candidate = build_draft_decision_packet(
        evaluations,
        state,
        league_config,
    ).candidates[0]

    assert candidate.name == "Tiered Receiver"
    assert candidate.manual_tier == 3
    assert candidate.market_pick_estimate == 9.0
    assert candidate.roster_fit == RosterFit.DIRECT_STARTER
    assert candidate.tier_remaining == 1
    assert candidate.position_tier_gap == 0
    assert "FILLS_DIRECT_STARTER" in candidate.signals


def test_packet_normalizes_missing_following_turn_at_end_of_draft(
    league_config: LeagueConfig,
    make_draft_state: Callable[..., DraftState],
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: the user is on the clock for the user's final selection of a fifteen-round draft
    WHEN: a decision packet is built
    THEN: the context represents the absent following user turn with None
    """
    state = make_draft_state(
        my_draft_slot=6,
        current_overall_pick=146,
    )
    player = make_player(
        rank=146,
        adp=146.0,
        name="Final Candidate",
        position="K",
        yahoo_player_id=22146,
    )
    evaluations = evaluate_candidates([player], state, league_config)

    packet = build_draft_decision_packet(evaluations, state, league_config)

    assert packet.context.total_draft_picks == 150
    assert packet.context.decision_pick == 146
    assert packet.context.following_pick is None
    assert packet.context.phase == DecisionPhase.ON_CLOCK
    assert packet.context.opponent_selections_before_following_pick == 0


def test_packet_marks_completed_draft_without_current_team(
    league_config: LeagueConfig,
    make_draft_state: Callable[..., DraftState],
) -> None:
    """
    GIVEN: the league draft has advanced beyond its configured final overall pick
    WHEN: a decision packet is built with no remaining evaluations
    THEN: the packet explicitly marks the decision phase complete without inventing a team turn
    """
    state = make_draft_state(
        my_draft_slot=6,
        current_overall_pick=151,
    )

    packet = build_draft_decision_packet([], state, league_config)

    assert packet.context.current_drafting_team is None
    assert packet.context.decision_pick is None
    assert packet.context.following_pick is None
    assert packet.context.phase == DecisionPhase.COMPLETE
    assert packet.candidates == ()


def test_packet_serializes_to_json_compatible_dictionary(
    league_config: LeagueConfig,
    make_draft_state: Callable[..., DraftState],
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: a deterministic decision packet with enum-backed evidence
    WHEN: its dictionary form is passed to the standard JSON encoder
    THEN: the packet can cross a future model boundary without custom object serialization
    """
    state = make_draft_state(
        my_draft_slot=4,
        current_overall_pick=4,
    )
    evaluations = evaluate_candidates(
        [
            make_player(
                rank=4,
                adp=4.0,
                name="Serializable Candidate",
                position="RB",
                yahoo_player_id=22004,
            )
        ],
        state,
        league_config,
    )
    packet = build_draft_decision_packet(evaluations, state, league_config)

    serialized = json.dumps(packet.to_dict())

    assert '"schema_version": 1' in serialized
    assert '"Serializable Candidate"' in serialized


def test_packet_rejects_non_positive_candidate_limit(
    league_config: LeagueConfig,
    make_draft_state: Callable[..., DraftState],
) -> None:
    """
    GIVEN: deterministic draft context
    WHEN: a decision packet is requested with a non-positive candidate limit
    THEN: packet construction rejects the invalid boundary configuration
    """
    state = make_draft_state()

    with pytest.raises(
        ValueError,
        match="Decision packet candidate limit must be at least 1",
    ):
        build_draft_decision_packet(
            [],
            state,
            league_config,
            candidate_limit=0,
        )
