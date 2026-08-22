"""Command-line entry point for recording and undoing draft picks."""

import argparse
from pathlib import Path

from fantasy_football_agent.application_paths import ApplicationPaths
from fantasy_football_agent.draft.rankings import load_rankings
from fantasy_football_agent.draft.session import (
    record_current_pick,
    save_draft_state,
    undo_last_pick,
)
from fantasy_football_agent.draft.state import (
    load_draft_state,
    load_league_config,
    validate_draft_state,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record one or more fantasy draft picks.")

    parser.add_argument(
        "players",
        nargs="*",
        help="Player names or Yahoo Player IDs, in draft order.",
    )

    parser.add_argument(
        "--undo",
        action="store_true",
        help="Undo the most recently recorded pick.",
    )

    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Directory containing the config and data directories.",
    )

    return parser.parse_args()


def _prompt_for_players() -> list[str]:
    print("Enter drafted players in order, one per line.")

    print("Press Enter on a blank line when finished.")

    players: list[str] = []

    while True:
        value = input("> ").strip()

        if not value:
            break

        players.append(value)

    return players


def main() -> None:
    """Apply requested draft-state changes and persist each successful update."""
    args = _parse_args()

    paths = ApplicationPaths(workspace=args.workspace.resolve())

    league = load_league_config(paths.league_config)
    state = load_draft_state(paths.draft_state)

    validate_draft_state(state, league)

    rankings = load_rankings(paths.rankings)

    if args.undo:
        try:
            undone_pick = undo_last_pick(
                state,
            )

        except ValueError as error:
            print(f"ERROR: {error}")
            return

        save_draft_state(
            paths.draft_state,
            state,
        )

        print()
        print(f"Undid pick #{undone_pick.overall}: {undone_pick.player} ({undone_pick.position})")

        print(f"Current overall pick is now #{state.current_overall_pick}.")

        return

    player_references = args.players or _prompt_for_players()

    if not player_references:
        print("No picks entered. Draft state unchanged.")
        return

    print()
    print("Recording picks:")

    for player_reference in player_references:
        try:
            pick = record_current_pick(
                state=state,
                league=league,
                rankings=rankings,
                player_reference=player_reference,
            )

        except ValueError as error:
            print(f"  ERROR: {error}")

            print("  Remaining picks were not recorded.")

            break

        # Persist each successful pick immediately.
        save_draft_state(
            paths.draft_state,
            state,
        )

        print(f"  #{pick.overall} T{pick.team_id} {pick.player} ({pick.position})")

    print()

    print(f"Current overall pick is now #{state.current_overall_pick}.")


if __name__ == "__main__":
    main()
