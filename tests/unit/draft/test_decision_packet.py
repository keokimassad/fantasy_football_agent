"""Unit tests for the deterministic AI decision-packet boundary."""

import json
from collections.abc import Callable

import pytest

from fantasy_football_agent.draft.decision_packet import (
    DECISION_PACKET_SCHEMA_VERSION,
    DecisionPhase,
    build_draft_decision_packet,
)
from fantasy_football_agent.draft.models import (
    AdpPolicy,
    DraftPick,
    DraftState,
    LeagueConfig,
    Player,
)
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
    WHEN: a decision packet is built with the default phase-aware candidate frontier
    THEN: the packet exposes factual roster context and a compact current-decision set
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
    assert packet.context.consecutive_turn is False
    assert packet.context.roster[0].player == "Roster RB"
    assert packet.context.roster_position_counts == {"RB": 1}
    assert packet.context.open_starter_slots["RB"] == 1
    assert packet.context.open_starter_slots["WR"] == 2
    assert len(packet.candidates) == 10


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

    assert '"schema_version": 2' in serialized
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


def test_waiting_packet_expands_beyond_intervening_selections(
    league_config: LeagueConfig,
    make_draft_state: Callable[..., DraftState],
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: pick one is waiting eighteen selections for the next snake-turn decision
    WHEN: the default decision packet is built
    THEN: the AI can see well beyond the players likely to disappear before the turn
    """
    state = make_draft_state(
        my_draft_slot=1,
        current_overall_pick=62,
    )
    positions = ("RB", "WR", "QB", "TE")
    players = [
        make_player(
            rank=rank,
            adp=float(rank),
            name=f"Waiting Candidate {rank}",
            position=positions[(rank - 1) % len(positions)],
            yahoo_player_id=24000 + rank,
            manual_tier=1 + ((rank - 1) // 8),
        )
        for rank in range(1, 61)
    ]

    packet = build_draft_decision_packet(
        evaluate_candidates(players, state, league_config),
        state,
        league_config,
    )

    assert packet.context.phase == DecisionPhase.WAITING
    assert packet.context.decision_pick == 80
    assert packet.context.selections_before_decision == 18
    assert len(packet.candidates) == 35
    assert len(packet.candidates) > packet.context.selections_before_decision


def test_waiting_packet_expands_skill_position_depth_across_long_gap(
    league_config: LeagueConfig,
    make_draft_state: Callable[..., DraftState],
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: an eighteen-pick wait whose global ordering is crowded by specialists
    WHEN: the waiting packet is built
    THEN: deeper RB, WR, QB, and TE target layers remain visible for the future turn
    """
    state = make_draft_state(my_draft_slot=1, current_overall_pick=62)
    players = [
        make_player(
            rank=rank,
            adp=float(rank),
            name=f"Defense {rank}",
            position="DEF",
            yahoo_player_id=28000 + rank,
            manual_tier=rank,
        )
        for rank in range(1, 26)
    ]
    rank = 26
    for position, count in (("RB", 10), ("WR", 10), ("QB", 6), ("TE", 6)):
        for index in range(count):
            players.append(
                make_player(
                    rank=rank,
                    adp=float(rank),
                    name=f"{position} Waiting {index + 1}",
                    position=position,
                    yahoo_player_id=28000 + rank,
                    manual_tier=index + 1,
                )
            )
            rank += 1

    packet = build_draft_decision_packet(
        evaluate_candidates(players, state, league_config),
        state,
        league_config,
    )
    position_counts = {
        position: sum(candidate.position == position for candidate in packet.candidates)
        for position in ("RB", "WR", "QB", "TE")
    }

    assert packet.context.selections_before_decision == 18
    assert position_counts["RB"] >= 7
    assert position_counts["WR"] >= 7
    assert position_counts["QB"] >= 4
    assert position_counts["TE"] >= 4


def test_consecutive_turn_packet_uses_broader_on_clock_frontier(
    league_config: LeagueConfig,
    make_draft_state: Callable[..., DraftState],
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: the user is on the clock for the first selection of a consecutive snake turn
    WHEN: the default packet is built
    THEN: the context marks the turn and exposes a broader two-pick decision frontier
    """
    state = make_draft_state(
        my_draft_slot=1,
        current_overall_pick=80,
    )
    players = [
        make_player(
            rank=rank,
            adp=float(rank),
            name=f"Turn Candidate {rank}",
            position="WR",
            yahoo_player_id=25000 + rank,
            manual_tier=1 + ((rank - 1) // 5),
        )
        for rank in range(1, 31)
    ]

    packet = build_draft_decision_packet(
        evaluate_candidates(players, state, league_config),
        state,
        league_config,
    )

    assert packet.context.phase == DecisionPhase.ON_CLOCK
    assert packet.context.decision_pick == 80
    assert packet.context.following_pick == 81
    assert packet.context.consecutive_turn is True
    assert len(packet.candidates) == 15


@pytest.mark.parametrize(
    ("filled_specialists", "expected_optional_capacity", "expected_required_positions"),
    [
        (("DEF",), 1, {"K": 2}),
        ((), 0, {"K": 2, "DEF": 2}),
    ],
)
def test_consecutive_endgame_packet_exposes_required_starter_options(
    filled_specialists: tuple[str, ...],
    expected_optional_capacity: int,
    expected_required_positions: dict[str, int],
    league_config: LeagueConfig,
    make_draft_pick: Callable[..., DraftPick],
    make_draft_state: Callable[..., DraftState],
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: slot one has two consecutive picks left and optional depth is constrained
    WHEN: the endgame decision packet is built
    THEN: low-desirability options remain visible for every starter position that must be filled
    """
    user_overall_picks = [1, 20, 21, 40, 41, 60, 61, 80, 81, 100, 101, 120, 121]
    roster_positions = ["QB", "RB", "RB", "WR", "WR", "TE", "RB", *filled_specialists]
    roster_positions.extend(["WR"] * (len(user_overall_picks) - len(roster_positions)))
    state = make_draft_state(
        my_draft_slot=1,
        current_overall_pick=140,
        picks=[
            make_draft_pick(overall=overall, team_id=1, position=position)
            for overall, position in zip(
                user_overall_picks,
                roster_positions,
                strict=True,
            )
        ],
    )
    players = [
        make_player(
            rank=rank,
            adp=float(rank),
            name=f"Depth Player {rank}",
            position="WR" if rank % 2 else "RB",
            yahoo_player_id=30000 + rank,
            manual_tier=10,
        )
        for rank in range(1, 21)
    ]
    for index, position in enumerate(("K", "K", "DEF", "DEF"), start=1):
        players.append(
            make_player(
                rank=190 + index,
                adp=float(190 + index),
                name=f"{position} Option {index}",
                position=position,
                yahoo_player_id=30200 + index,
                manual_tier=index,
            )
        )

    packet = build_draft_decision_packet(
        evaluate_candidates(players, state, league_config),
        state,
        league_config,
    )
    positions_in_packet = [candidate.position for candidate in packet.candidates]

    assert packet.context.phase == DecisionPhase.ON_CLOCK
    assert packet.context.consecutive_turn is True
    assert packet.context.remaining_user_selections == 2
    assert packet.context.optional_draft_capacity == expected_optional_capacity
    for position, expected_count in expected_required_positions.items():
        assert packet.context.open_starter_slots[position] == 1
        assert positions_in_packet.count(position) == expected_count


def test_on_clock_packet_guarantees_core_skill_position_breadth(
    league_config: LeagueConfig,
    make_draft_state: Callable[..., DraftState],
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: specialist candidates dominate the deterministic global ordering
    WHEN: an on-clock turn packet is built
    THEN: RB, WR, QB, and TE alternatives remain visible to the AI reasoning layer
    """
    state = make_draft_state(
        my_draft_slot=1,
        current_overall_pick=80,
    )
    players = [
        make_player(
            rank=rank,
            adp=float(rank),
            name=f"Defense {rank}",
            position="DEF",
            yahoo_player_id=26000 + rank,
            manual_tier=rank,
        )
        for rank in range(1, 19)
    ]
    rank = 19
    for position, count in (("RB", 4), ("WR", 4), ("QB", 3), ("TE", 3)):
        for index in range(count):
            players.append(
                make_player(
                    rank=rank,
                    adp=float(rank),
                    name=f"{position} Candidate {index + 1}",
                    position=position,
                    yahoo_player_id=26000 + rank,
                    manual_tier=index + 1,
                )
            )
            rank += 1

    packet = build_draft_decision_packet(
        evaluate_candidates(players, state, league_config),
        state,
        league_config,
    )
    position_counts = {
        position: sum(candidate.position == position for candidate in packet.candidates)
        for position in ("RB", "WR", "QB", "TE")
    }

    assert position_counts == {"RB": 3, "WR": 3, "QB": 2, "TE": 2}
    selected_names = {candidate.name for candidate in packet.candidates}
    assert "RB Candidate 4" not in selected_names
    assert "WR Candidate 4" not in selected_names
    assert "QB Candidate 3" not in selected_names
    assert "TE Candidate 3" not in selected_names


def test_explicit_candidate_limit_preserves_fixed_diagnostic_boundary(
    league_config: LeagueConfig,
    make_draft_state: Callable[..., DraftState],
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: callers need a fixed deterministic packet size for diagnostics
    WHEN: an explicit candidate limit is supplied
    THEN: phase-aware supplementation is bypassed and exactly that many are returned
    """
    state = make_draft_state(my_draft_slot=1, current_overall_pick=80)
    players = [
        make_player(
            rank=rank,
            adp=float(rank),
            name=f"Candidate {rank}",
            position="WR",
            yahoo_player_id=27000 + rank,
        )
        for rank in range(1, 11)
    ]

    packet = build_draft_decision_packet(
        evaluate_candidates(players, state, league_config),
        state,
        league_config,
        candidate_limit=5,
    )

    assert len(packet.candidates) == 5


def test_ignored_adp_does_not_create_stale_value_signals(
    league_config: LeagueConfig,
    make_draft_state: Callable[..., DraftState],
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: a player's historical ADP has been invalidated by material current news
    WHEN: the player is evaluated on the clock
    THEN: the packet preserves the source ADP but excludes it from current market signals
    """
    state = make_draft_state(my_draft_slot=1, current_overall_pick=80)
    player = make_player(
        rank=108,
        adp=None,
        source_adp=35.0,
        adp_policy=AdpPolicy.IGNORE,
        adp_override_reason="Commissioner's Exempt List",
        adp_override_as_of="2026-08-31",
        name="Josh Jacobs",
        position="RB",
        yahoo_player_id=31856,
        manual_tier=10,
    )

    candidate = build_draft_decision_packet(
        evaluate_candidates([player], state, league_config),
        state,
        league_config,
    ).candidates[0]

    assert candidate.adp is None
    assert candidate.source_adp == 35.0
    assert candidate.adp_policy == AdpPolicy.IGNORE
    assert candidate.market_pick_estimate == 108.0
    assert candidate.adp_value_at_decision is None
    assert "FALLEN_PAST_ADP" not in candidate.signals
    assert "MARKET_EXPECTED_BEFORE_FOLLOWING_PICK" not in candidate.signals
