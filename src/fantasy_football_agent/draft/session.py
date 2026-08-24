"""Apply draft selections to in-memory state and persist session changes."""

import json
from dataclasses import asdict
from difflib import get_close_matches
from pathlib import Path

from .models import DraftPick, DraftState, LeagueConfig, Player
from .state import get_round_and_pick_in_round, team_for_overall_pick


def resolve_player(
    rankings: list[Player],
    player_reference: str,
) -> Player:
    """Resolve a player reference against the loaded rankings.

    A reference may be either a Yahoo Player ID or an exact player name. Name matching
    is case-insensitive. When a name does not match, a few close names are included in
    the error message to make manual draft entry easier to correct.

    Args:
        rankings: Ranked players available for lookup.
        player_reference: Player name or Yahoo Player ID supplied by the caller.

    Returns:
        The matching ranked player.

    Raises:
        ValueError: If the reference is blank or no ranked player can be resolved.
    """
    reference = player_reference.strip()

    if not reference:
        raise ValueError("Player reference cannot be blank.")

    # Allow Yahoo Player ID directly.
    if reference.isdigit():
        yahoo_player_id = int(reference)

        for player in rankings:
            if player.yahoo_player_id == yahoo_player_id:
                return player

        raise ValueError(f"No ranked player found with Yahoo Player ID {yahoo_player_id}.")

    normalized_reference = reference.casefold()

    for player in rankings:
        if player.name.casefold() == normalized_reference:
            return player

    names = [player.name for player in rankings]

    suggestions = get_close_matches(
        reference,
        names,
        n=3,
        cutoff=0.6,
    )

    suggestion_text = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""

    raise ValueError(f'No ranked player found matching "{reference}".{suggestion_text}')


def record_current_pick(
    state: DraftState,
    league: LeagueConfig,
    rankings: list[Player],
    player_reference: str,
) -> DraftPick:
    """Record a selection at the state's current overall pick.

    Draft position metadata is derived from the current pick and league size rather
    than supplied by the caller. The player is resolved against the rankings, rejected
    if the same Yahoo Player ID has already been drafted, appended to ``state.picks``,
    and the draft state is advanced to the next overall selection.

    Args:
        state: Draft state to mutate.
        league: League configuration used to derive round and snake-draft ownership.
        rankings: Ranked players used to resolve the selected player.
        player_reference: Player name or Yahoo Player ID to record.

    Returns:
        The draft-pick record added to the state.

    Raises:
        ValueError: If the player cannot be resolved or has already been drafted.
    """
    player = resolve_player(
        rankings,
        player_reference,
    )

    already_drafted = any(pick.yahoo_player_id == player.yahoo_player_id for pick in state.picks)

    if already_drafted:
        raise ValueError(f"{player.name} has already been drafted.")

    overall_pick = state.current_overall_pick
    round_number, pick_in_round = get_round_and_pick_in_round(
        overall_pick,
        league.teams,
    )

    team_id = team_for_overall_pick(
        overall_pick,
        league.teams,
    )

    draft_pick = DraftPick(
        overall=overall_pick,
        round=round_number,
        pick_in_round=pick_in_round,
        team_id=team_id,
        player=player.name,
        position=player.position,
        yahoo_player_id=player.yahoo_player_id,
    )

    state.picks.append(draft_pick)

    # Advance the draft to the next selection.
    state.current_overall_pick += 1

    return draft_pick


def record_resolved_current_pick(
    state: DraftState,
    league: LeagueConfig,
    player: Player,
) -> DraftPick:
    """Record an already-resolved player at the state's current overall pick.

    Args:
        state: Draft state to mutate.
        league: League configuration used to derive snake-draft metadata.
        player: Ranked player whose identity has already been resolved.

    Returns:
        The draft-pick record added to the state.

    Raises:
        ValueError: If the player has already been drafted.
    """
    already_drafted = any(pick.yahoo_player_id == player.yahoo_player_id for pick in state.picks)

    if already_drafted:
        raise ValueError(f"{player.name} has already been drafted.")

    overall_pick = state.current_overall_pick
    round_number, pick_in_round = get_round_and_pick_in_round(
        overall_pick,
        league.teams,
    )

    team_id = team_for_overall_pick(
        overall_pick,
        league.teams,
    )

    draft_pick = DraftPick(
        overall=overall_pick,
        round=round_number,
        pick_in_round=pick_in_round,
        team_id=team_id,
        player=player.name,
        position=player.position,
        yahoo_player_id=player.yahoo_player_id,
    )

    state.picks.append(draft_pick)
    state.current_overall_pick += 1

    return draft_pick


def save_draft_state(
    path: str | Path,
    state: DraftState,
) -> None:
    """Write the complete draft state to disk as human-readable JSON.

    The target file is replaced with the current state on each save. A trailing newline
    is written so the persisted file remains friendly to command-line and version-control
    tooling.
    """
    path = Path(path)

    with path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            asdict(state),
            file,
            indent=2,
        )

        file.write("\n")


def undo_last_pick(
    state: DraftState,
) -> DraftPick:
    """Remove the most recent pick and move the draft pointer back to that selection.

    Raises:
        ValueError: If the draft does not contain a pick to undo.
    """
    if not state.picks:
        raise ValueError("There are no draft picks to undo.")

    last_pick = state.picks.pop()

    state.current_overall_pick = last_pick.overall

    return last_pick
