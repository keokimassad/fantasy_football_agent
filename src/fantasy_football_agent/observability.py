"""Persist local, analysis-ready draft telemetry without affecting draft execution."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from fantasy_football_agent.application_paths import ApplicationPaths
from fantasy_football_agent.draft.decision_packet import DraftDecisionPacket
from fantasy_football_agent.draft.models import DraftPick, DraftState

OBSERVABILITY_SCHEMA_VERSION = 1
_SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def _utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp suitable for event ordering."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safe_draft_id(draft_id: str) -> str:
    """Return a filesystem-safe draft identifier without changing the event payload."""
    safe_value = _SAFE_FILENAME_PATTERN.sub("_", draft_id).strip("._")
    return safe_value or "draft"


def _log_path(paths: ApplicationPaths, state: DraftState) -> Path:
    """Return the JSONL telemetry path for one draft session."""
    return paths.draft_logs / f"{_safe_draft_id(state.draft_id)}.jsonl"


def _run_git_command(workspace: Path, *args: str) -> str | None:
    """Return compact Git metadata when the workspace is a repository."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    value = result.stdout.strip()
    return value or None


def _source_snapshot(path: Path, workspace: Path) -> dict[str, Any] | None:
    """Capture one non-secret source file with a reproducibility fingerprint."""
    if not path.exists() or not path.is_file():
        return None

    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None

    try:
        display_path = str(path.relative_to(workspace))
    except ValueError:
        display_path = str(path)

    return {
        "path": display_path,
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "content": content,
    }


def _read_json_if_present(path: Path) -> dict[str, Any] | None:
    """Read an optional JSON object without allowing diagnostics to disrupt the draft."""
    if not path.exists():
        return None

    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict):
        return None

    return cast(dict[str, Any], data)


def _session_started_event(paths: ApplicationPaths, state: DraftState) -> dict[str, Any]:
    """Build the reproducibility snapshot written when a session log first appears."""
    status = _run_git_command(paths.workspace, "status", "--porcelain")
    return {
        "schema_version": OBSERVABILITY_SCHEMA_VERSION,
        "event_id": uuid4().hex,
        "recorded_at": _utc_timestamp(),
        "event_type": "session_started",
        "draft_id": state.draft_id,
        "state": state.to_dict(),
        "runtime": {
            "python": sys.version.split()[0],
            "git_commit": _run_git_command(paths.workspace, "rev-parse", "HEAD"),
            "git_branch": _run_git_command(paths.workspace, "branch", "--show-current"),
            "git_worktree_dirty": bool(status),
        },
        "sources": {
            "league_config": _source_snapshot(paths.league_config, paths.workspace),
            "rankings": _source_snapshot(paths.rankings, paths.workspace),
            "player_overrides": _source_snapshot(paths.player_overrides, paths.workspace),
            "custom_gpt_instructions": _source_snapshot(
                paths.custom_gpt_instructions,
                paths.workspace,
            ),
            "custom_gpt_knowledge": _source_snapshot(
                paths.custom_gpt_knowledge,
                paths.workspace,
            ),
        },
    }


def _append_event(
    paths: ApplicationPaths,
    state: DraftState,
    event: dict[str, Any],
    *,
    ensure_session: bool = True,
) -> str | None:
    """Append one event best-effort; diagnostics must never break live draft flow."""
    try:
        paths.draft_logs.mkdir(parents=True, exist_ok=True)
        log_path = _log_path(paths, state)

        if ensure_session and not log_path.exists():
            session_event = _session_started_event(paths, state)
            with log_path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(session_event, separators=(",", ":")) + "\n")

        with log_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, separators=(",", ":")) + "\n")
    except (OSError, TypeError, ValueError):
        return None

    event_id = event.get("event_id")
    return str(event_id) if event_id is not None else None


def start_draft_log(paths: ApplicationPaths, state: DraftState) -> None:
    """Ensure the active draft has a session/reproducibility event."""
    event = _session_started_event(paths, state)
    _append_event(paths, state, event, ensure_session=False)


def record_yahoo_sync_attempt(
    paths: ApplicationPaths,
    state: DraftState,
    *,
    raw_text: str,
    parsed_pick_count: int,
) -> str | None:
    """Record the exact Yahoo input and pre-sync state before reconciliation begins."""
    event = {
        "schema_version": OBSERVABILITY_SCHEMA_VERSION,
        "event_id": uuid4().hex,
        "recorded_at": _utc_timestamp(),
        "event_type": "yahoo_sync_attempt",
        "draft_id": state.draft_id,
        "current_overall_pick": state.current_overall_pick,
        "parsed_pick_count": parsed_pick_count,
        "raw_yahoo_text": raw_text,
        "state_before": state.to_dict(),
    }
    return _append_event(paths, state, event)


def record_yahoo_sync_result(
    paths: ApplicationPaths,
    state: DraftState,
    *,
    attempt_event_id: str | None,
    success: bool,
) -> None:
    """Record post-sync state and any persisted stale marker."""
    event = {
        "schema_version": OBSERVABILITY_SCHEMA_VERSION,
        "event_id": uuid4().hex,
        "recorded_at": _utc_timestamp(),
        "event_type": "yahoo_sync_result",
        "draft_id": state.draft_id,
        "attempt_event_id": attempt_event_id,
        "success": success,
        "current_overall_pick": state.current_overall_pick,
        "state_after": state.to_dict(),
        "sync_failure": _read_json_if_present(paths.draft_sync_status),
    }
    _append_event(paths, state, event)


def record_state_change(
    paths: ApplicationPaths,
    state: DraftState,
    *,
    action: str,
    pick: DraftPick,
) -> None:
    """Record a manual pick or undo that changed deterministic draft state."""
    event = {
        "schema_version": OBSERVABILITY_SCHEMA_VERSION,
        "event_id": uuid4().hex,
        "recorded_at": _utc_timestamp(),
        "event_type": "state_change",
        "draft_id": state.draft_id,
        "action": action,
        "pick": pick.to_dict(),
        "current_overall_pick": state.current_overall_pick,
        "state_after": state.to_dict(),
    }
    _append_event(paths, state, event)


def record_decision_packet(
    paths: ApplicationPaths,
    state: DraftState,
    packet: DraftDecisionPacket,
    *,
    source: str,
) -> None:
    """Record the exact deterministic packet exposed to CLI or AI reasoning."""
    event = {
        "schema_version": OBSERVABILITY_SCHEMA_VERSION,
        "event_id": uuid4().hex,
        "recorded_at": _utc_timestamp(),
        "event_type": "decision_packet",
        "draft_id": state.draft_id,
        "source": source,
        "current_overall_pick": state.current_overall_pick,
        "state": state.to_dict(),
        "sync_failure": _read_json_if_present(paths.draft_sync_status),
        "packet": packet.to_dict(),
    }
    _append_event(paths, state, event)


def record_decision_blocked(
    paths: ApplicationPaths,
    state: DraftState,
    *,
    source: str,
    reason: str,
) -> None:
    """Record an attempted recommendation that was blocked by stale-state safety."""
    event = {
        "schema_version": OBSERVABILITY_SCHEMA_VERSION,
        "event_id": uuid4().hex,
        "recorded_at": _utc_timestamp(),
        "event_type": "decision_blocked",
        "draft_id": state.draft_id,
        "source": source,
        "reason": reason,
        "current_overall_pick": state.current_overall_pick,
        "state": state.to_dict(),
        "sync_failure": _read_json_if_present(paths.draft_sync_status),
    }
    _append_event(paths, state, event)
