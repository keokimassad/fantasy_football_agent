"""Command-line entry point for recording and undoing draft picks."""

import argparse
import sys
from pathlib import Path

from fantasy_football_agent.application_paths import ApplicationPaths
from fantasy_football_agent.draft.models import DraftState, LeagueConfig, Player
from fantasy_football_agent.draft.rankings import load_rankings
from fantasy_football_agent.draft.session import (
    record_current_pick,
    record_resolved_current_pick,
    save_draft_state,
    undo_last_pick,
)
from fantasy_football_agent.draft.state import (
    load_draft_state,
    load_league_config,
    validate_draft_state,
)
from fantasy_football_agent.yahoo.draft_chat import (
    AmbiguousYahooPlayerError,
    parse_yahoo_draft_chat,
)
from fantasy_football_agent.yahoo.draft_sync import (
    YahooDraftSyncError,
    reconcile_yahoo_chat_pick,
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

    parser.add_argument(
        "--yahoo-chat",
        action="store_true",
        help="Read copied Yahoo draft-chat text from standard input.",
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


def _prompt_for_ambiguous_player(
    error: AmbiguousYahooPlayerError,
) -> Player | None:
    """Prompt for a player when Yahoo metadata cannot uniquely identify one."""
    print()
    print(
        f"Ambiguous Yahoo player at pick #{error.chat_pick.overall}: "
        f'"{error.chat_pick.player_reference}"'
    )

    for index, player in enumerate(error.candidates, start=1):
        adp_display = f"{player.adp:.1f}" if player.adp is not None else "-"

        print(
            f"  [{index}] {player.name} "
            f"| Rank #{player.rank} "
            f"| {player.position} {player.team} "
            f"| ADP {adp_display}"
        )

    while True:
        choice = _read_terminal_input(f"Select player [1-{len(error.candidates)}] or q to cancel: ")

        if choice.casefold() == "q":
            return None

        if choice.isdigit():
            index = int(choice) - 1

            if 0 <= index < len(error.candidates):
                return error.candidates[index]

        print("Invalid selection.")


def _sync_yahoo_chat(
    *,
    text: str,
    state: DraftState,
    league: LeagueConfig,
    rankings: list[Player],
    draft_state_path: Path,
) -> None:
    """Reconcile copied Yahoo draft-chat selections and persist new picks."""
    chat_picks = sorted(
        parse_yahoo_draft_chat(text),
        key=lambda pick: pick.overall,
    )

    if not chat_picks:
        print("No Yahoo draft selections found. Draft state unchanged.")
        return

    print()
    print("Synchronizing Yahoo draft chat:")

    for chat_pick in chat_picks:
        try:
            result = reconcile_yahoo_chat_pick(
                state=state,
                league=league,
                rankings=rankings,
                chat_pick=chat_pick,
            )

        except AmbiguousYahooPlayerError as error:
            player = _prompt_for_ambiguous_player(error)

            if player is None:
                print("  Synchronization cancelled.")
                print("  Remaining picks were not recorded.")
                break

            try:
                recorded_pick = record_resolved_current_pick(
                    state=state,
                    league=league,
                    player=player,
                )
            except ValueError as record_error:
                print(f"  ERROR: {record_error}")
                print("  Remaining picks were not recorded.")
                break

            save_draft_state(
                draft_state_path,
                state,
            )

            print(
                f"  RECORDED #{recorded_pick.overall} "
                f"T{recorded_pick.team_id} "
                f"{recorded_pick.player} ({recorded_pick.position})"
            )

            continue

        except (YahooDraftSyncError, ValueError) as error:
            print(f"  ERROR: {error}")
            print("  Remaining picks were not recorded.")
            break

        if result.action == "verified":
            print(
                f"  VERIFIED #{result.pick.overall} "
                f"T{result.pick.team_id} "
                f"{result.pick.player} ({result.pick.position})"
            )

            continue

        save_draft_state(
            draft_state_path,
            state,
        )

        print(
            f"  RECORDED #{result.pick.overall} "
            f"T{result.pick.team_id} "
            f"{result.pick.player} ({result.pick.position})"
        )

    print()
    print(f"Current overall pick is now #{state.current_overall_pick}.")


def _read_terminal_input(prompt: str) -> str:
    """Read interactive input even when standard input contains piped draft data."""
    if sys.stdin.isatty():
        return input(prompt)

    try:
        with open("/dev/tty", encoding="utf-8") as terminal:
            print(prompt, end="", flush=True)
            response = terminal.readline()
    except OSError as error:
        raise RuntimeError("Interactive player selection requires an attached terminal.") from error

    if not response:
        raise RuntimeError("Interactive player selection requires an attached terminal.")

    return response.strip()


def main() -> None:
    """Apply requested draft-state changes and persist each successful update."""
    args = _parse_args()

    paths = ApplicationPaths(workspace=args.workspace.resolve())

    league = load_league_config(paths.league_config)
    state = load_draft_state(paths.draft_state)

    validate_draft_state(state, league)

    rankings = load_rankings(paths.rankings)

    if args.yahoo_chat:
        if args.undo or args.players:
            print(
                "ERROR: --yahoo-chat cannot be combined with "
                "--undo or positional player references."
            )
            return

        _sync_yahoo_chat(
            text=sys.stdin.read(),
            state=state,
            league=league,
            rankings=rankings,
            draft_state_path=paths.draft_state,
        )

        return

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
