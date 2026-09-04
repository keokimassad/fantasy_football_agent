"""Reconcile parsed Yahoo draft selections with deterministic draft state."""

from dataclasses import dataclass
from typing import Literal

from fantasy_football_agent.draft.models import (
    DraftPick,
    DraftState,
    LeagueConfig,
    Player,
)
from fantasy_football_agent.draft.session import (
    record_resolved_current_pick,
    record_unranked_current_pick,
)
from fantasy_football_agent.draft.state import team_for_overall_pick

from .draft_chat import (
    AmbiguousYahooPlayerError,
    PotentialYahooPlayerMatchError,
    YahooDraftChatPick,
    YahooPlayerNotFoundError,
    resolve_yahoo_chat_player,
)


class YahooDraftSyncError(ValueError):
    """Signal that Yahoo draft history conflicts with local draft state."""


@dataclass(frozen=True)
class YahooDraftReconciliation:
    """Describe how one Yahoo selection was reconciled."""

    action: Literal["verified", "recorded"]
    pick: DraftPick


def _matches_recorded_player(
    player: Player,
    recorded_pick: DraftPick,
) -> bool:
    if recorded_pick.yahoo_player_id is not None:
        return player.yahoo_player_id == recorded_pick.yahoo_player_id

    return (
        player.name.casefold() == recorded_pick.player.casefold()
        and player.position.casefold() == recorded_pick.position.casefold()
    )


def _validate_user_pick(
    state: DraftState,
    league: LeagueConfig,
    chat_pick: YahooDraftChatPick,
) -> None:
    if chat_pick.drafter.casefold() != "you":
        return

    team_id = team_for_overall_pick(
        chat_pick.overall,
        league.teams,
    )

    if team_id != state.my_draft_slot:
        raise YahooDraftSyncError(
            f"Yahoo marks pick #{chat_pick.overall} as yours, "
            f"but draft slot {state.my_draft_slot} does not own that pick."
        )


def _resolve_overlapping_pick(
    rankings: list[Player],
    chat_pick: YahooDraftChatPick,
    recorded_pick: DraftPick,
) -> Player:
    try:
        return resolve_yahoo_chat_player(
            rankings,
            chat_pick,
        )
    except (AmbiguousYahooPlayerError, PotentialYahooPlayerMatchError) as error:
        matching_candidates = [
            candidate
            for candidate in error.candidates
            if _matches_recorded_player(candidate, recorded_pick)
        ]

        if len(matching_candidates) == 1:
            return matching_candidates[0]

        raise YahooDraftSyncError(
            f"Could not verify overlapping Yahoo pick "
            f"#{chat_pick.overall} against existing draft state."
        ) from error


def _matches_unranked_recorded_player(
    chat_pick: YahooDraftChatPick,
    recorded_pick: DraftPick,
) -> bool:
    """Return whether Yahoo repeats the same previously unranked selection."""
    if recorded_pick.yahoo_player_id is not None:
        return False

    if chat_pick.player_reference.casefold() != recorded_pick.player.casefold():
        return False

    if chat_pick.position.casefold() != recorded_pick.position.casefold():
        return False

    if chat_pick.team is None or recorded_pick.nfl_team is None:
        return True

    return chat_pick.team.casefold() == recorded_pick.nfl_team.casefold()


def reconcile_yahoo_chat_pick(
    state: DraftState,
    league: LeagueConfig,
    rankings: list[Player],
    chat_pick: YahooDraftChatPick,
) -> YahooDraftReconciliation:
    """Reconcile one parsed Yahoo selection with current draft state.

    Historical selections are verified against already-recorded picks. The exact
    current selection is resolved and recorded. A future selection indicates that
    draft history is missing and is rejected instead of advancing across a gap.

    Args:
        state: Current deterministic draft state.
        league: League configuration defining snake-draft ownership.
        rankings: Ranked players used to resolve Yahoo identities.
        chat_pick: Parsed Yahoo draft-chat selection.

    Returns:
        Whether the selection was verified or newly recorded.

    Raises:
        AmbiguousYahooPlayerError: If a new exact selection still has multiple candidates.
        PotentialYahooPlayerMatchError: If an unmatched selection has plausible ranked
            typo candidates requiring manual confirmation.
        YahooDraftSyncError: If Yahoo history conflicts with local state or contains
            a gap.
        ValueError: If the Yahoo player cannot be safely resolved or recorded.
    """
    _validate_user_pick(
        state,
        league,
        chat_pick,
    )

    if chat_pick.overall > state.current_overall_pick:
        raise YahooDraftSyncError(
            f"Draft gap detected: local state expects pick "
            f"#{state.current_overall_pick}, but Yahoo supplied "
            f"pick #{chat_pick.overall}. The expected pick is missing "
            f"from parsed Yahoo selections; the copied range may omit it "
            f"or its Yahoo block format may be unsupported."
        )

    if chat_pick.overall < state.current_overall_pick:
        recorded_pick = next(
            (pick for pick in state.picks if pick.overall == chat_pick.overall),
            None,
        )

        if recorded_pick is None:
            raise YahooDraftSyncError(
                f"Yahoo supplied historical pick #{chat_pick.overall}, "
                "but that pick is missing from local draft state."
            )

        if recorded_pick.yahoo_player_id is None:
            if not _matches_unranked_recorded_player(
                chat_pick,
                recorded_pick,
            ):
                raise YahooDraftSyncError(
                    f"Pick #{chat_pick.overall} conflicts with local state: "
                    f'Yahoo reports "{chat_pick.player_reference}", but local state contains '
                    f'"{recorded_pick.player}".'
                )

            return YahooDraftReconciliation(
                action="verified",
                pick=recorded_pick,
            )

        player = _resolve_overlapping_pick(
            rankings,
            chat_pick,
            recorded_pick,
        )

        if not _matches_recorded_player(
            player,
            recorded_pick,
        ):
            raise YahooDraftSyncError(
                f"Pick #{chat_pick.overall} conflicts with local state: "
                f'Yahoo reports "{player.name}", but local state contains '
                f'"{recorded_pick.player}".'
            )

        return YahooDraftReconciliation(
            action="verified",
            pick=recorded_pick,
        )

    drafted_ids = {pick.yahoo_player_id for pick in state.picks if pick.yahoo_player_id is not None}

    try:
        player = resolve_yahoo_chat_player(
            rankings,
            chat_pick,
            excluded_yahoo_player_ids=drafted_ids,
        )
    except YahooPlayerNotFoundError:
        recorded_pick = record_unranked_current_pick(
            state=state,
            league=league,
            player_reference=chat_pick.player_reference,
            position=chat_pick.position,
            nfl_team=chat_pick.team,
        )
    else:
        recorded_pick = record_resolved_current_pick(
            state=state,
            league=league,
            player=player,
        )

    return YahooDraftReconciliation(
        action="recorded",
        pick=recorded_pick,
    )
