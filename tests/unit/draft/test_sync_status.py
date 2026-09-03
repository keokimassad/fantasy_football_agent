"""Unit tests for persisted draft synchronization safety state."""

from pathlib import Path

import pytest

from fantasy_football_agent.draft.models import DraftState
from fantasy_football_agent.draft.sync_status import (
    DraftStateStaleError,
    clear_draft_state_stale,
    clear_stale_state_after_successful_sync,
    load_draft_sync_failure,
    mark_draft_state_stale,
    require_fresh_draft_state,
)

pytestmark = pytest.mark.unit


def _state(*, draft_id: str = "test-draft", current_overall_pick: int) -> DraftState:
    """Build a minimal draft state for synchronization-status tests."""
    return DraftState(
        draft_id=draft_id,
        session_type="mock",
        my_draft_slot=4,
        current_overall_pick=current_overall_pick,
        picks=[],
    )


def test_stale_marker_round_trips_and_blocks_matching_draft(
    tmp_path: Path,
) -> None:
    """
    GIVEN: Yahoo evidence is ahead of the local current pick
    WHEN: the failure is persisted and the same draft is checked
    THEN: diagnostic context is retained and recommendations are rejected
    """
    path = tmp_path / "draft_sync_status.json"
    state = _state(draft_id="mock-stale", current_overall_pick=7)

    mark_draft_state_stale(
        path,
        state=state,
        message="Draft gap detected.",
        observed_yahoo_pick=11,
    )

    failure = load_draft_sync_failure(path)
    assert failure is not None
    assert failure.draft_id == "mock-stale"
    assert failure.local_current_overall_pick == 7
    assert failure.observed_yahoo_pick == 11

    with pytest.raises(DraftStateStaleError, match="Draft gap detected"):
        require_fresh_draft_state(path, state)


def test_stale_marker_from_other_draft_does_not_block_current_session(
    tmp_path: Path,
) -> None:
    """
    GIVEN: a stale marker belongs to an older draft session
    WHEN: freshness is checked for a different draft ID
    THEN: the unrelated marker does not block the current session
    """
    path = tmp_path / "draft_sync_status.json"
    old_state = _state(draft_id="old-draft", current_overall_pick=7)
    current_state = _state(draft_id="new-draft", current_overall_pick=1)
    mark_draft_state_stale(
        path,
        state=old_state,
        message="Old failure.",
        observed_yahoo_pick=11,
    )

    require_fresh_draft_state(path, current_state)


def test_successful_sync_only_clears_after_local_state_passes_observed_pick(
    tmp_path: Path,
) -> None:
    """
    GIVEN: a stale marker observed Yahoo pick eleven
    WHEN: successful recovery has not yet advanced beyond that pick
    THEN: the marker remains until the local pointer reaches pick twelve or later
    """
    path = tmp_path / "draft_sync_status.json"
    stale_state = _state(draft_id="mock-stale", current_overall_pick=7)
    mark_draft_state_stale(
        path,
        state=stale_state,
        message="Draft gap detected.",
        observed_yahoo_pick=11,
    )

    past_observed_pick = _state(draft_id="mock-stale", current_overall_pick=12)
    assert (
        clear_stale_state_after_successful_sync(
            path,
            past_observed_pick,
            synced_yahoo_picks={7, 8, 9, 10},
        )
        is False
    )
    assert path.exists()

    at_observed_pick = _state(draft_id="mock-stale", current_overall_pick=11)
    assert (
        clear_stale_state_after_successful_sync(
            path,
            at_observed_pick,
            synced_yahoo_picks={11},
        )
        is False
    )
    assert path.exists()

    assert (
        clear_stale_state_after_successful_sync(
            path,
            past_observed_pick,
            synced_yahoo_picks={11},
        )
        is True
    )
    assert not path.exists()


def test_clear_stale_marker_removes_failure(tmp_path: Path) -> None:
    """
    GIVEN: a persisted synchronization failure
    WHEN: a fresh draft explicitly clears the marker
    THEN: no stale failure remains
    """
    path = tmp_path / "draft_sync_status.json"
    state = _state(draft_id="old-draft", current_overall_pick=4)
    mark_draft_state_stale(
        path,
        state=state,
        message="Temporary failure.",
        observed_yahoo_pick=8,
    )

    clear_draft_state_stale(path)

    assert load_draft_sync_failure(path) is None
