"""Load player rankings and derive availability, tier, and scarcity signals."""

import csv
from pathlib import Path

from .models import DraftState, Player


def _parse_optional_float(value: str) -> float | None:
    value = value.strip()

    if value in {"", "-"}:
        return None

    return float(value)


def _parse_optional_int(value: str) -> int | None:
    value = value.strip()

    if value in {"", "-"}:
        return None

    return int(float(value))


def _parse_percentage(value: str) -> float | None:
    value = value.strip()

    if value in {"", "-"}:
        return None

    return float(value.rstrip("%"))


def load_rankings(path: str | Path) -> list[Player]:
    """Load the draft rankings CSV into ordered player records.

    The loader preserves the ranking order in the file and normalizes optional Yahoo
    fields such as ADP and drafted percentage to ``None`` when the CSV contains a blank
    value or ``-``. ``utf-8-sig`` is used so exports with a byte-order mark are handled
    without leaking that marker into the first column name.

    Args:
        path: Rankings CSV to read.

    Returns:
        Players in the same order they appear in the rankings file.
    """
    path = Path(path)

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)

        players = []

        for row in reader:
            player = Player(
                rank=int(row["Rank"]),
                adp=_parse_optional_float(row["ADP"]),
                name=row["Player Name"].strip(),
                position=row["Position"].strip(),
                team=row["Team"].strip(),
                bye=int(row["Bye"]),
                drafted_percentage=_parse_percentage(row["% Drafted"]),
                yahoo_player_id=int(row["Yahoo Player ID"]),
                manual_tier=_parse_optional_int(row["Manual - Tier"]),
            )

            players.append(player)

        return players


def get_available_players(
    rankings: list[Player],
    state: DraftState,
) -> list[Player]:
    """Return ranked players who have not already been drafted.

    Yahoo Player ID is used as the identity key rather than player name. This keeps
    availability checks stable if display names or formatting change.

    Args:
        rankings: Complete ordered rankings list.
        state: Current draft state containing recorded selections.

    Returns:
        Undrafted players in their original ranking order.
    """
    drafted_player_ids = {
        pick.yahoo_player_id for pick in state.picks if pick.yahoo_player_id is not None
    }

    return [player for player in rankings if player.yahoo_player_id not in drafted_player_ids]


def get_tier_players(
    available_players: list[Player],
    position: str,
    tier: int,
) -> list[Player]:
    """Return available players at a position who share the requested manual tier."""
    return [
        player
        for player in available_players
        if player.position == position and player.manual_tier == tier
    ]


def remaining_in_player_tier(
    available_players: list[Player],
    player: Player,
) -> int | None:
    """Count available peers remaining in the player's position tier.

    ``None`` is returned when the player has no manual tier so callers can distinguish
    missing tier data from a tier that has been exhausted.
    """
    if player.manual_tier is None:
        return None

    return len(
        get_tier_players(
            available_players,
            player.position,
            player.manual_tier,
        )
    )


def next_position_tier(
    available_players: list[Player],
    player: Player,
) -> int | None:
    """Return the next worse available tier at the player's position.

    The search uses the numeric tier ordering and ignores players without manual tiers.
    ``None`` means either the player is untiered or no later tier is currently available.
    """
    if player.manual_tier is None:
        return None

    later_tiers = sorted(
        {
            candidate.manual_tier
            for candidate in available_players
            if candidate.position == player.position
            and candidate.manual_tier is not None
            and candidate.manual_tier > player.manual_tier
        }
    )

    if not later_tiers:
        return None

    return later_tiers[0]


def is_last_in_tier(
    available_players: list[Player],
    player: Player,
) -> bool:
    """Return whether the player is the final available option in the current tier."""
    remaining = remaining_in_player_tier(
        available_players,
        player,
    )

    return remaining == 1


def get_position_tier_summary(
    available_players: list[Player],
) -> dict[str, dict[int, int]]:
    """Count available players by position and manual tier.

    Players without a manual tier are omitted so an incomplete tiering pass does not
    create a synthetic tier or distort the scarcity counts.
    """
    summary: dict[str, dict[int, int]] = {}

    for player in available_players:
        if player.manual_tier is None:
            continue

        if player.position not in summary:
            summary[player.position] = {}

        summary[player.position][player.manual_tier] = (
            summary[player.position].get(player.manual_tier, 0) + 1
        )

    return summary


def get_scarcity_flags(
    available_players: list[Player],
    player: Player,
) -> list[str]:
    """Describe simple tier-scarcity conditions around an available player.

    The flags are intentionally deterministic signals rather than draft recommendations.
    A player may be marked as the last option in a tier, one of only two remaining
    options, or as sitting ahead of a gap of at least two tier numbers. Untiered players
    receive no scarcity flags.
    """
    flags: list[str] = []

    if player.manual_tier is None:
        return flags

    remaining = remaining_in_player_tier(
        available_players,
        player,
    )

    if remaining == 1:
        flags.append("LAST_IN_TIER")
    elif remaining == 2:
        flags.append("LOW_TIER_DEPTH")

    next_tier = next_position_tier(
        available_players,
        player,
    )

    if next_tier is not None:
        tier_gap = next_tier - player.manual_tier

        if tier_gap >= 2:
            flags.append("LARGE_TIER_DROP")

    return flags


def get_tier_coverage(
    rankings: list[Player],
    position: str,
) -> tuple[int, int]:
    """Return tiered and total player counts for a position.

    Coverage is kept separate from scarcity so downstream analysis can judge whether
    manual tiers are complete enough to trust before using tier-based signals.
    """
    position_players = [player for player in rankings if player.position == position]

    tiered_players = [player for player in position_players if player.manual_tier is not None]

    return len(tiered_players), len(position_players)
