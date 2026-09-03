"""Persist whether local draft state is safe to use for recommendations."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import DraftState


@dataclass(frozen=True)
class DraftSyncFailure:
    """Describe a Yahoo synchronization failure that makes local state unsafe."""

    draft_id: str
    message: str
    local_current_overall_pick: int
    observed_yahoo_pick: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DraftSyncFailure":
        """Reconstruct a persisted synchronization failure."""
        return cls(
            draft_id=str(data["draft_id"]),
            message=str(data["message"]),
            local_current_overall_pick=int(data["local_current_overall_pick"]),
            observed_yahoo_pick=int(data["observed_yahoo_pick"]),
        )


class DraftStateStaleError(RuntimeError):
    """Raised when recommendations are requested from known-stale draft state."""

    def __init__(self, failure: DraftSyncFailure) -> None:
        """Initialize the error with persisted synchronization-failure context."""
        super().__init__(failure.message)
        self.failure = failure


def load_draft_sync_failure(path: str | Path) -> DraftSyncFailure | None:
    """Return the persisted synchronization failure, if one exists."""
    path = Path(path)
    if not path.exists():
        return None

    data = json.loads(path.read_text(encoding="utf-8"))
    return DraftSyncFailure.from_dict(data)


def mark_draft_state_stale(
    path: str | Path,
    *,
    state: DraftState,
    message: str,
    observed_yahoo_pick: int,
) -> None:
    """Persist a Yahoo failure that disables recommendations for the active draft."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "draft_id": state.draft_id,
                "message": message,
                "local_current_overall_pick": state.current_overall_pick,
                "observed_yahoo_pick": observed_yahoo_pick,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def clear_draft_state_stale(path: str | Path) -> None:
    """Remove a prior synchronization failure marker."""
    Path(path).unlink(missing_ok=True)


def require_fresh_draft_state(path: str | Path, state: DraftState) -> None:
    """Raise when the active draft is known stale from a Yahoo synchronization failure."""
    failure = load_draft_sync_failure(path)
    if failure is None or failure.draft_id != state.draft_id:
        return

    raise DraftStateStaleError(failure)


def clear_stale_state_after_successful_sync(
    path: str | Path,
    state: DraftState,
    *,
    synced_yahoo_picks: set[int],
) -> bool:
    """Clear stale state only after the failed Yahoo pick is reconciled and caught up."""
    failure = load_draft_sync_failure(path)
    if failure is None:
        return True

    if failure.draft_id != state.draft_id:
        clear_draft_state_stale(path)
        return True

    recovery_floor = max(
        failure.local_current_overall_pick,
        failure.observed_yahoo_pick,
    )
    failure_pick_reconciled = failure.observed_yahoo_pick in synced_yahoo_picks

    if failure_pick_reconciled and state.current_overall_pick > recovery_floor:
        clear_draft_state_stale(path)
        return True

    return False
