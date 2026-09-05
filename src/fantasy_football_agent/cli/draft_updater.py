"""Command-line entry point for recording and undoing draft picks."""

import argparse
import sys
from enum import StrEnum
from pathlib import Path

from fantasy_football_agent.application_paths import ApplicationPaths
from fantasy_football_agent.draft.models import DraftState, LeagueConfig, Player
from fantasy_football_agent.draft.rankings import load_rankings
from fantasy_football_agent.draft.session import (
    record_current_pick,
    record_resolved_current_pick,
    record_unranked_current_pick,
    save_draft_state,
    undo_last_pick,
)
from fantasy_football_agent.draft.state import (
    is_draft_complete,
    load_draft_state,
    load_league_config,
    validate_draft_state,
)
from fantasy_football_agent.draft.sync_status import (
    clear_stale_state_after_successful_sync,
    load_draft_sync_failure,
    mark_draft_state_stale,
)
from fantasy_football_agent.observability import (
    record_state_change,
    record_yahoo_sync_attempt,
    record_yahoo_sync_result,
)
from fantasy_football_agent.yahoo.draft_chat import (
    AmbiguousYahooPlayerError,
    PotentialYahooPlayerMatchError,
    parse_yahoo_draft_chat,
)
from fantasy_football_agent.yahoo.draft_sync import (
    YahooDraftSyncError,
    reconcile_yahoo_chat_pick,
)


class _PotentialMatchChoice(StrEnum):
    """Represent non-player choices for a plausible Yahoo identity match."""

    RECORD_UNRANKED = "RECORD_UNRANKED"


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


def _print_ranked_identity_candidates(candidates: tuple[Player, ...]) -> None:
    """Print ranked identity candidates in a consistent terminal format."""
    for index, player in enumerate(candidates, start=1):
        adp_display = f"{player.adp:.1f}" if player.adp is not None else "-"

        print(
            f"  [{index}] {player.name} "
            f"| Rank #{player.rank} "
            f"| {player.position} {player.team} "
            f"| ADP {adp_display}"
        )


def _prompt_for_ambiguous_player(
    error: AmbiguousYahooPlayerError,
) -> Player | None:
    """Prompt for a player when Yahoo metadata cannot uniquely identify one."""
    print()
    print(
        f"Ambiguous Yahoo player at pick #{error.chat_pick.overall}: "
        f'"{error.chat_pick.player_reference}"'
    )

    _print_ranked_identity_candidates(error.candidates)

    while True:
        choice = _read_terminal_input(f"Select player [1-{len(error.candidates)}] or q to cancel: ")

        if choice.casefold() == "q":
            return None

        if choice.isdigit():
            index = int(choice) - 1

            if 0 <= index < len(error.candidates):
                return error.candidates[index]

        print("Invalid selection.")


def _prompt_for_potential_player_match(
    error: PotentialYahooPlayerMatchError,
) -> Player | _PotentialMatchChoice | None:
    """Prompt before treating a plausible typo as a distinct unranked player."""
    print()
    print(
        f"Possible Yahoo player typo at pick #{error.chat_pick.overall}: "
        f'"{error.chat_pick.player_reference}"'
    )
    _print_ranked_identity_candidates(error.candidates)
    print(f'  [u] Record "{error.chat_pick.player_reference}" as an unranked Yahoo selection')

    while True:
        choice = _read_terminal_input(
            f"Select player [1-{len(error.candidates)}], u for unranked, or q to cancel: "
        )

        if choice.casefold() == "q":
            return None

        if choice.casefold() == "u":
            return _PotentialMatchChoice.RECORD_UNRANKED

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
    sync_status_path: Path,
) -> bool:
    """Reconcile copied Yahoo draft-chat selections and report whether state is safe."""
    chat_picks = sorted(
        parse_yahoo_draft_chat(text),
        key=lambda pick: pick.overall,
    )

    if not chat_picks:
        failure = load_draft_sync_failure(sync_status_path)
        if failure is not None and failure.draft_id == state.draft_id:
            print("No Yahoo draft selections found. Draft state remains stale.")
            return False

        draft_started = state.current_overall_pick > 1 or bool(state.picks)
        if draft_started and not is_draft_complete(state, league):
            print(
                "ERROR: No Yahoo draft selections were parsed for an active draft. "
                "Draft state unchanged."
            )
            print("Copy a recent Yahoo draft-chat range and rerun synchronization.")
            return False

        print("No Yahoo draft selections found. Draft state unchanged.")
        return True

    print()
    print("Synchronizing Yahoo draft chat:")

    failure_message: str | None = None
    failed_yahoo_pick: int | None = None

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
                failure_message = (
                    f"Yahoo synchronization cancelled while resolving pick "
                    f"#{error.chat_pick.overall}."
                )
                failed_yahoo_pick = error.chat_pick.overall
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
                failure_message = str(record_error)
                failed_yahoo_pick = error.chat_pick.overall
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

        except PotentialYahooPlayerMatchError as error:
            choice = _prompt_for_potential_player_match(error)

            if choice is None:
                failure_message = (
                    f"Yahoo synchronization cancelled while resolving pick "
                    f"#{error.chat_pick.overall}."
                )
                failed_yahoo_pick = error.chat_pick.overall
                print("  Synchronization cancelled.")
                print("  Remaining picks were not recorded.")
                break

            try:
                if choice == _PotentialMatchChoice.RECORD_UNRANKED:
                    recorded_pick = record_unranked_current_pick(
                        state=state,
                        league=league,
                        player_reference=error.chat_pick.player_reference,
                        position=error.chat_pick.position,
                        nfl_team=error.chat_pick.team,
                    )
                else:
                    recorded_pick = record_resolved_current_pick(
                        state=state,
                        league=league,
                        player=choice,
                    )
            except ValueError as record_error:
                failure_message = str(record_error)
                failed_yahoo_pick = error.chat_pick.overall
                print(f"  ERROR: {record_error}")
                print("  Remaining picks were not recorded.")
                break

            save_draft_state(
                draft_state_path,
                state,
            )

            identity_note = " [UNRANKED]" if recorded_pick.yahoo_player_id is None else ""
            print(
                f"  RECORDED #{recorded_pick.overall} "
                f"T{recorded_pick.team_id} "
                f"{recorded_pick.player} ({recorded_pick.position}){identity_note}"
            )

            continue

        except (YahooDraftSyncError, ValueError) as error:
            failure_message = str(error)
            failed_yahoo_pick = chat_pick.overall
            print(f"  ERROR: {error}")
            print("  Remaining picks were not recorded.")
            break

        if result.action == "verified":
            identity_note = " [UNRANKED]" if result.pick.yahoo_player_id is None else ""
            print(
                f"  VERIFIED #{result.pick.overall} "
                f"T{result.pick.team_id} "
                f"{result.pick.player} ({result.pick.position}){identity_note}"
            )

            continue

        save_draft_state(
            draft_state_path,
            state,
        )

        identity_note = " [UNRANKED]" if result.pick.yahoo_player_id is None else ""
        print(
            f"  RECORDED #{result.pick.overall} "
            f"T{result.pick.team_id} "
            f"{result.pick.player} ({result.pick.position}){identity_note}"
        )

    print()
    print(f"Current overall pick is now #{state.current_overall_pick}.")

    if failure_message is not None and failed_yahoo_pick is not None:
        mark_draft_state_stale(
            sync_status_path,
            state=state,
            message=failure_message,
            observed_yahoo_pick=failed_yahoo_pick,
        )
        print()
        print("=" * 72)
        print("DRAFT STATE MARKED STALE — RECOMMENDATIONS DISABLED")
        print(
            f"Local state is at pick #{state.current_overall_pick}; "
            f"Yahoo evidence reached pick #{failed_yahoo_pick}."
        )
        print("Resolve the Yahoo synchronization failure before using draft analysis.")
        print("=" * 72)
        return False

    recovered = clear_stale_state_after_successful_sync(
        sync_status_path,
        state,
        synced_yahoo_picks={pick.overall for pick in chat_picks},
    )
    if not recovered:
        failure = load_draft_sync_failure(sync_status_path)
        assert failure is not None
        print()
        print("=" * 72)
        print("DRAFT STATE STILL STALE — MORE YAHOO HISTORY IS REQUIRED")
        print(
            f"The prior failure observed Yahoo pick #{failure.observed_yahoo_pick}; "
            f"local state is only at #{state.current_overall_pick}."
        )
        print("Copy a range that includes the unresolved picks and rerun synchronization.")
        print("=" * 72)
        return False

    return True


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

    league = load_league_config(
        paths.league_config,
        draft_strategy_path=paths.draft_strategy,
    )
    state = load_draft_state(paths.draft_state)

    validate_draft_state(state, league)

    rankings = load_rankings(paths.rankings, paths.player_overrides)

    if args.yahoo_chat:
        if args.undo or args.players:
            print(
                "ERROR: --yahoo-chat cannot be combined with "
                "--undo or positional player references."
            )
            return

        yahoo_text = sys.stdin.read()
        parsed_pick_count = len(parse_yahoo_draft_chat(yahoo_text))
        attempt_event_id = record_yahoo_sync_attempt(
            paths,
            state,
            raw_text=yahoo_text,
            parsed_pick_count=parsed_pick_count,
        )
        sync_succeeded = _sync_yahoo_chat(
            text=yahoo_text,
            state=state,
            league=league,
            rankings=rankings,
            draft_state_path=paths.draft_state,
            sync_status_path=paths.draft_sync_status,
        )
        record_yahoo_sync_result(
            paths,
            state,
            attempt_event_id=attempt_event_id,
            success=sync_succeeded,
        )

        if not sync_succeeded:
            raise SystemExit(1)

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

        record_state_change(
            paths,
            state,
            action="undo",
            pick=undone_pick,
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
        record_state_change(
            paths,
            state,
            action="manual_pick",
            pick=pick,
        )

        print(f"  #{pick.overall} T{pick.team_id} {pick.player} ({pick.position})")

    print()

    print(f"Current overall pick is now #{state.current_overall_pick}.")


if __name__ == "__main__":
    main()
