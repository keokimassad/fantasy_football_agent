"""Command-line entry point for creating a fresh draft session."""

import argparse
from datetime import datetime
from pathlib import Path

from fantasy_football_agent.application_paths import ApplicationPaths
from fantasy_football_agent.draft.models import DraftState
from fantasy_football_agent.draft.session import save_draft_state
from fantasy_football_agent.draft.state import (
    load_league_config,
    validate_draft_state,
)
from fantasy_football_agent.draft.sync_status import clear_draft_state_stale
from fantasy_football_agent.observability import start_draft_log


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a fresh fantasy football draft session.")

    parser.add_argument(
        "--type",
        dest="session_type",
        choices=("mock", "actual"),
        required=True,
        help="Type of draft session to create.",
    )
    parser.add_argument(
        "--slot",
        type=int,
        required=True,
        help="Your draft slot in the league.",
    )
    parser.add_argument(
        "--draft-id",
        help=(
            "Optional draft-session identifier. "
            "A timestamp-based identifier is generated when omitted."
        ),
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace an existing active draft state.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Directory containing the config and data directories.",
    )

    return parser.parse_args()


def _default_draft_id(session_type: str) -> str:
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    return f"{session_type}-{timestamp}"


def main() -> None:
    """Create and persist an empty validated draft session."""
    args = _parse_args()

    paths = ApplicationPaths(workspace=args.workspace.resolve())

    if paths.draft_state.exists() and not args.replace:
        print(f"ERROR: An active draft state already exists at {paths.draft_state}.")
        print("Use --replace to intentionally replace it.")
        return

    league = load_league_config(
        paths.league_config,
        draft_strategy_path=paths.draft_strategy,
    )

    draft_id = args.draft_id.strip() if args.draft_id else _default_draft_id(args.session_type)

    if not draft_id:
        print("ERROR: Draft ID cannot be blank.")
        return

    state = DraftState(
        draft_id=draft_id,
        session_type=args.session_type,
        my_draft_slot=args.slot,
        current_overall_pick=1,
        picks=[],
    )

    try:
        validate_draft_state(state, league)
    except ValueError as error:
        print(f"ERROR: {error}")
        return

    paths.draft_state.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    save_draft_state(
        paths.draft_state,
        state,
    )
    clear_draft_state_stale(paths.draft_sync_status)
    start_draft_log(paths, state)

    print()
    print("Created draft session:")
    print(f"  ID: {state.draft_id}")
    print(f"  Type: {state.session_type}")
    print(f"  Draft slot: {state.my_draft_slot}")
    print("  Current overall pick: #1")


if __name__ == "__main__":
    main()
