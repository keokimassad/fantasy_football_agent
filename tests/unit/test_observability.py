"""Unit tests for automatic draft observability logs."""

import json
from pathlib import Path
from typing import Any

import pytest

from fantasy_football_agent.application_paths import ApplicationPaths
from fantasy_football_agent.draft.decision_packet import build_draft_decision_packet
from fantasy_football_agent.draft.models import DraftState, LeagueConfig
from fantasy_football_agent.observability import (
    record_decision_packet,
    record_yahoo_sync_attempt,
    record_yahoo_sync_result,
    start_draft_log,
)

pytestmark = pytest.mark.unit


def _write_source_files(workspace: Path) -> ApplicationPaths:
    """Write representative non-secret inputs captured for draft reproducibility."""
    paths = ApplicationPaths(workspace=workspace)
    paths.league_config.parent.mkdir(parents=True)
    paths.rankings.parent.mkdir(parents=True)
    paths.custom_gpt_instructions.parent.mkdir(parents=True)

    paths.league_config.write_text('{"league_name":"Telemetry League"}\n', encoding="utf-8")
    paths.rankings.write_text("Rank,Player Name\n1,Player One\n", encoding="utf-8")
    paths.player_overrides.write_text('{"players":[]}\n', encoding="utf-8")
    paths.custom_gpt_instructions.write_text("Use the packet.\n", encoding="utf-8")
    paths.custom_gpt_knowledge.write_text("Yahoo mock observations.\n", encoding="utf-8")
    return paths


def _read_events(paths: ApplicationPaths, draft_id: str) -> list[dict[str, Any]]:
    """Read JSONL events written for one test draft."""
    log_path = paths.draft_logs / f"{draft_id}.jsonl"
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]


def test_session_log_captures_reproducibility_sources(tmp_path: Path) -> None:
    """
    GIVEN: a new draft and the non-secret files that influence deterministic/GPT decisions
    WHEN: automatic draft logging starts
    THEN: one local session event snapshots the exact source content and fingerprints
    """
    paths = _write_source_files(tmp_path)
    state = DraftState(
        draft_id="mock-observability",
        session_type="mock",
        my_draft_slot=4,
        current_overall_pick=1,
    )

    start_draft_log(paths, state)

    events = _read_events(paths, state.draft_id)
    assert len(events) == 1
    event = events[0]
    assert event["event_type"] == "session_started"
    assert event["state"]["draft_id"] == state.draft_id
    assert event["sources"]["rankings"]["content"].startswith("Rank,Player Name")
    assert len(event["sources"]["rankings"]["sha256"]) == 64
    assert event["sources"]["custom_gpt_instructions"]["content"] == "Use the packet.\n"
    assert "oauth" not in json.dumps(event).casefold()


def test_yahoo_sync_events_preserve_raw_input_and_before_after_state(tmp_path: Path) -> None:
    """
    GIVEN: an active mock draft receiving copied Yahoo text
    WHEN: synchronization telemetry is recorded around state reconciliation
    THEN: the log links exact raw input to deterministic state before and after the attempt
    """
    paths = _write_source_files(tmp_path)
    state = DraftState(
        draft_id="mock-sync-log",
        session_type="mock",
        my_draft_slot=6,
        current_overall_pick=7,
    )
    raw_text = "Round 1\n7. Example Player (RB)\n"

    attempt_id = record_yahoo_sync_attempt(
        paths,
        state,
        raw_text=raw_text,
        parsed_pick_count=1,
    )
    state.current_overall_pick = 8
    record_yahoo_sync_result(
        paths,
        state,
        attempt_event_id=attempt_id,
        success=True,
    )

    events = _read_events(paths, state.draft_id)
    attempt = next(event for event in events if event["event_type"] == "yahoo_sync_attempt")
    result = next(event for event in events if event["event_type"] == "yahoo_sync_result")
    assert attempt["raw_yahoo_text"] == raw_text
    assert attempt["parsed_pick_count"] == 1
    assert attempt["state_before"]["current_overall_pick"] == 7
    assert result["attempt_event_id"] == attempt["event_id"]
    assert result["success"] is True
    assert result["state_after"]["current_overall_pick"] == 8


def test_decision_packet_event_records_exact_ai_boundary_and_source(
    tmp_path: Path,
    league_config: LeagueConfig,
) -> None:
    """
    GIVEN: a deterministic decision packet exposed to a downstream reasoning surface
    WHEN: the packet is automatically logged
    THEN: the event preserves both full draft state and the exact AI-visible packet
    """
    paths = _write_source_files(tmp_path)
    state = DraftState(
        draft_id="mock-packet-log",
        session_type="mock",
        my_draft_slot=4,
        current_overall_pick=4,
    )
    packet = build_draft_decision_packet([], state, league_config)

    record_decision_packet(paths, state, packet, source="gateway")

    events = _read_events(paths, state.draft_id)
    packet_event = next(event for event in events if event["event_type"] == "decision_packet")
    assert packet_event["source"] == "gateway"
    assert packet_event["state"]["current_overall_pick"] == 4
    assert packet_event["packet"] == json.loads(json.dumps(packet.to_dict()))
