"""Unit tests for workspace-backed decision-packet construction."""

import json
from pathlib import Path

import pytest

from fantasy_football_agent.application_paths import ApplicationPaths
from fantasy_football_agent.draft.decision_packet import DecisionPhase
from fantasy_football_agent.draft.sync_status import DraftStateStaleError
from fantasy_football_agent.gateway.service import build_current_decision_packet

pytestmark = pytest.mark.unit


def _write_workspace(
    workspace: Path,
    *,
    current_overall_pick: int = 4,
) -> None:
    """Write a minimal deterministic workspace for gateway-service tests."""
    (workspace / "config").mkdir()
    (workspace / "data").mkdir()

    league = {
        "league_name": "Gateway Test League",
        "teams": 10,
        "draft": {"type": "snake"},
        "roster": {
            "QB": 1,
            "WR": 2,
            "RB": 2,
            "TE": 1,
            "FLEX": 1,
            "K": 1,
            "DEF": 1,
            "BENCH": 6,
            "IR": 2,
        },
        "flex_positions": ["RB", "WR", "TE"],
        "scoring": {"receptions": 0.5},
    }
    strategy = {
        "strategy_name": "test-balanced",
        "as_of": "2026-09-04",
        "position_roster_targets": {
            "QB": 1,
            "RB": 4,
            "WR": 4,
            "TE": 1,
            "K": 1,
            "DEF": 1,
        },
    }
    state = {
        "draft_id": "gateway-mock",
        "session_type": "mock",
        "my_draft_slot": 4,
        "current_overall_pick": current_overall_pick,
        "picks": [],
    }

    (workspace / "config" / "league.json").write_text(
        json.dumps(league),
        encoding="utf-8",
    )
    (workspace / "config" / "draft_strategy.json").write_text(
        json.dumps(strategy),
        encoding="utf-8",
    )
    (workspace / "data" / "draft_state.json").write_text(
        json.dumps(state),
        encoding="utf-8",
    )
    (workspace / "data" / "yahoo_rankings_2026.csv").write_text(
        "\n".join(
            [
                "Rank,ADP,Player Name,Position,Team,Bye,% Drafted,Yahoo Player ID,Manual - Tier",
                "1,3.0,Gateway Receiver,WR,TST,10,99%,30001,1",
                "2,5.0,Gateway Running Back,RB,TST,11,98%,30002,1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_service_builds_current_packet_from_workspace(tmp_path: Path) -> None:
    """
    GIVEN: a valid local draft workspace with two available players
    WHEN: the gateway service builds the current decision packet
    THEN: the packet contains factual league context and deterministic candidates
    """
    _write_workspace(tmp_path)

    packet = build_current_decision_packet(ApplicationPaths(workspace=tmp_path))

    assert packet.context.league_name == "Gateway Test League"
    assert packet.context.phase == DecisionPhase.ON_CLOCK
    assert [candidate.name for candidate in packet.candidates] == [
        "Gateway Receiver",
        "Gateway Running Back",
    ]


def test_service_logs_exact_packet_when_called_for_gateway(tmp_path: Path) -> None:
    """
    GIVEN: a valid workspace used by the Custom GPT gateway
    WHEN: the gateway service builds a logged decision packet
    THEN: the local draft log records the exact packet with gateway provenance
    """
    _write_workspace(tmp_path)
    paths = ApplicationPaths(workspace=tmp_path)

    packet = build_current_decision_packet(paths, log_source="gateway")

    log_path = paths.draft_logs / "gateway-mock.jsonl"
    events = [json.loads(line) for line in log_path.read_text().splitlines()]
    packet_event = next(event for event in events if event["event_type"] == "decision_packet")
    assert packet_event["source"] == "gateway"
    assert packet_event["packet"]["context"]["current_overall_pick"] == 4
    assert packet_event["packet"]["candidates"][0]["name"] == packet.candidates[0].name


def test_service_returns_completed_packet_after_final_pick(tmp_path: Path) -> None:
    """
    GIVEN: a valid workspace whose draft has advanced beyond pick one hundred fifty
    WHEN: the gateway service builds the current decision packet
    THEN: it reports a complete phase without inventing another candidate decision
    """
    _write_workspace(tmp_path, current_overall_pick=151)
    (tmp_path / "data" / "yahoo_rankings_2026.csv").unlink()

    packet = build_current_decision_packet(ApplicationPaths(workspace=tmp_path))

    assert packet.context.phase == DecisionPhase.COMPLETE
    assert packet.context.decision_pick is None
    assert packet.candidates == ()


def test_service_applies_local_adp_override_to_packet(tmp_path: Path) -> None:
    """
    GIVEN: a workspace with a player whose source ADP is explicitly invalidated
    WHEN: the gateway builds the current packet
    THEN: the AI boundary receives effective ADP rather than stale source-market evidence
    """
    _write_workspace(tmp_path)
    (tmp_path / "data" / "player_overrides_2026.json").write_text(
        """{
  "players": [
    {
      "yahoo_player_id": 30001,
      "adp_policy": "IGNORE",
      "reason": "Material news invalidated source ADP",
      "as_of": "2026-08-31"
    }
  ]
}
""",
        encoding="utf-8",
    )

    packet = build_current_decision_packet(ApplicationPaths(workspace=tmp_path))
    candidate = next(
        candidate for candidate in packet.candidates if candidate.yahoo_player_id == 30001
    )

    assert candidate.source_adp == 3.0
    assert candidate.adp is None
    assert candidate.adp_policy.value == "IGNORE"
    assert candidate.market_pick_estimate == 1.0


def test_service_refuses_packet_when_active_draft_is_marked_stale(tmp_path: Path) -> None:
    """
    GIVEN: the active workspace is marked stale after a Yahoo synchronization failure
    WHEN: the gateway service is asked to build a current packet
    THEN: it refuses to expose recommendations from known-stale state
    """
    _write_workspace(tmp_path)
    (tmp_path / "data" / "draft_sync_status.json").write_text(
        json.dumps(
            {
                "draft_id": "gateway-mock",
                "message": "Draft gap detected.",
                "local_current_overall_pick": 4,
                "observed_yahoo_pick": 8,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DraftStateStaleError, match="Draft gap detected"):
        build_current_decision_packet(ApplicationPaths(workspace=tmp_path))
