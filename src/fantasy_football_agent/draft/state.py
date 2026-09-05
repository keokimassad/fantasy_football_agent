"""Load, validate, and query deterministic fantasy draft state."""

import json
from collections import Counter
from pathlib import Path

from .models import (
    DraftPick,
    DraftState,
    DraftStrategyConfig,
    LeagueConfig,
    TeamLookaheadContext,
)


def load_draft_strategy_config(path: str | Path) -> DraftStrategyConfig:
    """Load user-controlled draft strategy from a standalone JSON file."""
    path = Path(path)

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    return DraftStrategyConfig.from_dict(data)


def load_league_config(
    path: str | Path,
    *,
    draft_strategy_path: str | Path | None = None,
) -> LeagueConfig:
    """Load league rules and optionally compose a separately stored draft strategy.

    Args:
        path: JSON file containing league rules and scoring.
        draft_strategy_path: Optional standalone user-strategy JSON file. Runtime
            application paths should supply this so ``league.json`` remains league-only.

    Returns:
        The validated runtime league configuration.

    Raises:
        ValueError: If separate strategy is requested while league JSON also embeds one,
            or if the league configuration contains unsupported draft settings.
    """
    path = Path(path)

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    draft_strategy = None
    if draft_strategy_path is not None:
        if "draft_strategy" in data:
            raise ValueError(
                "league.json must contain league rules only when draft_strategy.json "
                "is supplied separately."
            )
        draft_strategy = load_draft_strategy_config(draft_strategy_path)

    config = LeagueConfig.from_dict(data, draft_strategy=draft_strategy)
    validate_league_config(config)

    return config


def load_draft_state(path: str | Path) -> DraftState:
    """Load persisted draft-session state from JSON.

    This function reconstructs the state but does not validate it against a particular
    league. Call ``validate_draft_state`` after the league configuration is available.
    """
    path = Path(path)

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    return DraftState.from_dict(data)


def validate_league_config(config: LeagueConfig) -> None:
    """Check the league settings required by the current draft engine.

    Raises:
        ValueError: If the league has fewer than two teams or does not use a snake draft.
    """
    if config.teams < 2:
        raise ValueError("League must contain at least two teams.")

    if config.draft.get("type") != "snake":
        raise ValueError(f"Unsupported draft type: {config.draft.get('type')}")


def validate_draft_state(
    state: DraftState,
    league: LeagueConfig,
) -> None:
    """Check session state against the league boundaries understood by the engine.

    Raises:
        ValueError: If the session type, user's draft slot, or current overall pick is invalid.
    """
    if state.session_type not in {"mock", "actual"}:
        raise ValueError(f"Unsupported session type: {state.session_type}")

    if not 1 <= state.my_draft_slot <= league.teams:
        raise ValueError(f"Draft slot must be between 1 and {league.teams}.")

    if state.current_overall_pick < 1:
        raise ValueError("Current overall pick must be at least 1.")


def get_round_and_pick_in_round(
    overall_pick: int,
    team_count: int,
) -> tuple[int, int]:
    """Return the round and pick-within-round for an overall selection."""
    round_number = ((overall_pick - 1) // team_count) + 1
    pick_in_round = ((overall_pick - 1) % team_count) + 1

    return round_number, pick_in_round


def team_for_overall_pick(overall_pick: int, teams: int) -> int:
    """Return the draft slot that owns an overall pick in a snake draft.

    Team IDs intentionally match draft slots. Odd-numbered rounds progress from slot 1
    through the final slot; even-numbered rounds reverse that order.

    Raises:
        ValueError: If ``overall_pick`` is less than one.
    """
    if overall_pick < 1:
        raise ValueError("Overall pick must be at least 1.")

    round_number = ((overall_pick - 1) // teams) + 1
    pick_in_round = ((overall_pick - 1) % teams) + 1

    if round_number % 2 == 1:
        return pick_in_round

    return teams - pick_in_round + 1


def get_team_roster(
    state: DraftState,
    team_id: int,
) -> list[DraftPick]:
    """Return recorded picks belonging to a team in draft order."""
    return [pick for pick in state.picks if pick.team_id == team_id]


def get_team_position_counts(
    state: DraftState,
    team_id: int,
) -> dict[str, int]:
    """Count how many players a team has drafted at each position."""
    positions = [pick.position for pick in state.picks if pick.team_id == team_id]

    return dict(Counter(positions))


def get_all_team_position_counts(
    state: DraftState,
    league: LeagueConfig,
) -> dict[int, dict[str, int]]:
    """Return position counts for every draft slot in the league."""
    return {
        team_id: get_team_position_counts(state, team_id) for team_id in range(1, league.teams + 1)
    }


def get_team_open_starter_slots(
    state: DraftState,
    league: LeagueConfig,
    team_id: int,
) -> dict[str, int]:
    """Calculate the team's unfilled starting roster slots.

    Dedicated positions are filled before FLEX is considered. For example, a third RB
    can consume FLEX only after the team's required RB slots are already filled. BENCH
    and IR are intentionally excluded because this function describes starting-roster
    needs, not total roster capacity.
    """
    counts = get_team_position_counts(state, team_id)

    open_slots: dict[str, int] = {}

    # Dedicated starting positions
    for position, required in league.roster.items():
        if position in {"FLEX", "BENCH", "IR"}:
            continue

        drafted = counts.get(position, 0)

        open_slots[position] = max(
            required - drafted,
            0,
        )

    # Calculate FLEX separately.
    flex_slots = league.roster.get("FLEX", 0)

    if flex_slots > 0:
        overflow_flex_players = 0

        for position in league.flex_positions:
            drafted = counts.get(position, 0)
            dedicated_slots = league.roster.get(position, 0)

            overflow_flex_players += max(
                drafted - dedicated_slots,
                0,
            )

        open_slots["FLEX"] = max(
            flex_slots - overflow_flex_players,
            0,
        )

    return open_slots


def get_all_team_open_starter_slots(
    state: DraftState,
    league: LeagueConfig,
) -> dict[int, dict[str, int]]:
    """Return open starting slots for every draft slot in the league."""
    return {
        team_id: get_team_open_starter_slots(
            state,
            league,
            team_id,
        )
        for team_id in range(1, league.teams + 1)
    }


def get_draftable_roster_size(league: LeagueConfig) -> int:
    """Return the number of roster spots filled during the draft.

    IR is post-draft roster capacity rather than a draftable slot in the supported
    Yahoo league format. BENCH and FLEX remain draftable because selections occupy
    those roster spots during the draft.
    """
    return sum(count for position, count in league.roster.items() if position != "IR")


def get_total_draft_picks(league: LeagueConfig) -> int:
    """Return the final overall pick number for the configured draft."""
    return league.teams * get_draftable_roster_size(league)


def is_draft_complete(
    state: DraftState,
    league: LeagueConfig,
) -> bool:
    """Return whether the draft has advanced beyond its final configured pick."""
    return state.current_overall_pick > get_total_draft_picks(league)


def get_team_optional_draft_capacity(
    state: DraftState,
    league: LeagueConfig,
    team_id: int,
) -> int:
    """Return how many remaining selections may be spent on optional depth.

    Remaining roster capacity includes every draftable roster spot. Open starter
    slots are the selections the team must still reserve to produce a legal roster.
    Their difference is therefore the number of picks that can safely be spent on
    players who do not fill an open required slot.
    """
    remaining_roster_slots = max(
        get_draftable_roster_size(league) - len(get_team_roster(state, team_id)),
        0,
    )
    required_open_slots = sum(
        get_team_open_starter_slots(
            state,
            league,
            team_id,
        ).values()
    )

    return remaining_roster_slots - required_open_slots


def get_next_pick_for_team(
    current_overall_pick: int,
    team_id: int,
    teams: int,
    include_current: bool = False,
    max_overall_pick: int | None = None,
) -> int | None:
    """Find the next overall pick owned by a team.

    ``include_current`` controls the on-the-clock case. When it is true, the current
    pick may be returned if it belongs to the requested team. When it is false, the
    search begins with the following overall pick. ``max_overall_pick`` optionally
    bounds the search to a configured draft endpoint; ``None`` is returned when the
    team has no remaining selection inside that boundary.

    Raises:
        ValueError: If ``team_id`` falls outside the league's draft slots.
    """
    if not 1 <= team_id <= teams:
        raise ValueError(f"Team ID must be between 1 and {teams}.")

    candidate = current_overall_pick if include_current else current_overall_pick + 1

    while max_overall_pick is None or candidate <= max_overall_pick:
        if team_for_overall_pick(candidate, teams) == team_id:
            return candidate

        candidate += 1

    return None


def get_active_lookahead_window(
    state: DraftState,
    league: LeagueConfig,
) -> tuple[int, int | None, list[tuple[int, int]]]:
    """Build the lookahead window that matters for the user's next decision point.

    While another team is drafting, the window includes every selection from the
    current pick up to, but not including, the user's next pick. When the user is on the
    clock, it instead starts after the current selection and ends at the user's following
    pick. This lets downstream analysis answer the relevant question in either state:
    what can happen before I pick, or what can happen if I pass on a player now?

    Returns:
        A tuple containing the first pick in the window, the user's target pick at the
        end of the window, and ``(overall_pick, team_id)`` pairs for the intervening
        selections.
    """
    current_pick = state.current_overall_pick
    final_pick = get_total_draft_picks(league)

    next_my_pick = get_next_pick_for_team(
        current_overall_pick=current_pick,
        team_id=state.my_draft_slot,
        teams=league.teams,
        include_current=True,
        max_overall_pick=final_pick,
    )

    # The user's selections are complete while the league draft is still finishing.
    if next_my_pick is None:
        picks = [
            (overall_pick, team_for_overall_pick(overall_pick, league.teams))
            for overall_pick in range(current_pick, final_pick + 1)
        ]
        return current_pick, None, picks

    # We are currently on the clock.
    if next_my_pick == current_pick:
        following_my_pick = get_next_pick_for_team(
            current_overall_pick=current_pick,
            team_id=state.my_draft_slot,
            teams=league.teams,
            include_current=False,
            max_overall_pick=final_pick,
        )

        window_stop = following_my_pick if following_my_pick is not None else final_pick + 1
        picks = [
            (overall_pick, team_for_overall_pick(overall_pick, league.teams))
            for overall_pick in range(current_pick + 1, window_stop)
        ]

        return current_pick + 1, following_my_pick, picks

    # We are waiting for our turn.
    picks = [
        (overall_pick, team_for_overall_pick(overall_pick, league.teams))
        for overall_pick in range(current_pick, next_my_pick)
    ]

    return current_pick, next_my_pick, picks


def get_team_context_for_picks(
    state: DraftState,
    league: LeagueConfig,
    picks: list[tuple[int, int]],
) -> dict[int, TeamLookaheadContext]:
    """Group a lookahead pick sequence into per-team draft context.

    Each team receives its number of selections, corresponding overall pick
    numbers, and a snapshot of its open starting slots from the current draft
    state.

    Args:
        state: Current draft state.
        league: League configuration used to determine roster needs.
        picks: Overall-pick and team-ID pairs in the active lookahead window.

    Returns:
        Lookahead context keyed by team ID.
    """
    context: dict[int, TeamLookaheadContext] = {}

    for overall_pick, opponent_team_id in picks:
        if opponent_team_id not in context:
            context[opponent_team_id] = TeamLookaheadContext(
                pick_count=0,
                overall_picks=[],
                open_starter_slots=get_team_open_starter_slots(
                    state,
                    league,
                    opponent_team_id,
                ),
            )

        team_context = context[opponent_team_id]
        team_context.pick_count += 1
        team_context.overall_picks.append(overall_pick)

    return context
