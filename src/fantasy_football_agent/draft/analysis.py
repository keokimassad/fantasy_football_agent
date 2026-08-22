"""Compute deterministic demand signals from a draft lookahead window."""

from .models import LeagueConfig, PositionExposure, TeamLookaheadContext


def get_position_exposure(
    league: LeagueConfig,
    lookahead_context: dict[int, TeamLookaheadContext],
) -> dict[str, PositionExposure]:
    """Describe positional demand among opponents in the active lookahead window.

    This is not a probability model. It summarizes how many teams have direct
    or FLEX-eligible demand for each position and how many selections those
    teams control during the lookahead window.

    Args:
        league: League configuration defining FLEX-eligible positions.
        lookahead_context: Opponent roster needs and picks in the active window.

    Returns:
        Position-level demand and selection exposure.
    """
    positions = [
        "QB",
        "RB",
        "WR",
        "TE",
        "K",
        "DEF",
    ]

    exposure: dict[str, PositionExposure] = {}

    for position in positions:
        direct_need_teams: list[int] = []
        flex_only_teams: list[int] = []
        selection_chances = 0

        for opponent_team_id, context in lookahead_context.items():
            slots = context.open_starter_slots

            has_direct_need = slots.get(position, 0) > 0

            can_use_flex = position in league.flex_positions and slots.get("FLEX", 0) > 0

            if has_direct_need:
                direct_need_teams.append(opponent_team_id)

                selection_chances += context.pick_count

            elif can_use_flex:
                flex_only_teams.append(opponent_team_id)

                selection_chances += context.pick_count

        exposure[position] = PositionExposure(
            direct_need_teams=direct_need_teams,
            flex_only_teams=flex_only_teams,
            selection_chances=selection_chances,
        )

    return exposure
