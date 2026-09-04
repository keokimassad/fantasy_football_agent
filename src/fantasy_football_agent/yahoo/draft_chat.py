"""Parse Yahoo draft-chat selections and resolve their player references."""

import re
from collections.abc import Collection
from dataclasses import dataclass

from fantasy_football_agent.draft.models import Player

_POSITIONS = frozenset({"QB", "RB", "WR", "TE", "K", "DEF"})
_BYE_PATTERN = re.compile(r"^Bye\s+(\d+)$", re.IGNORECASE)
_TEAM_PATTERN = re.compile(r"^[A-Za-z]{2,3}$")
_DEFENSE_TEAM_BY_REFERENCE = {
    "49ers": "SF",
    "bears": "CHI",
    "bengals": "CIN",
    "bills": "BUF",
    "broncos": "DEN",
    "browns": "CLE",
    "buccaneers": "TB",
    "cardinals": "ARI",
    "chargers": "LAC",
    "chiefs": "KC",
    "colts": "IND",
    "commanders": "WAS",
    "cowboys": "DAL",
    "dolphins": "MIA",
    "eagles": "PHI",
    "falcons": "ATL",
    "giants": "NYG",
    "jaguars": "JAX",
    "jets": "NYJ",
    "lions": "DET",
    "packers": "GB",
    "panthers": "CAR",
    "patriots": "NE",
    "raiders": "LV",
    "rams": "LAR",
    "ravens": "BAL",
    "saints": "NO",
    "seahawks": "SEA",
    "steelers": "PIT",
    "texans": "HOU",
    "titans": "TEN",
    "vikings": "MIN",
}


@dataclass(frozen=True)
class YahooDraftChatPick:
    """Represent one selection parsed from Yahoo draft-chat text."""

    overall: int
    drafter: str
    player_reference: str
    position: str
    team: str | None
    bye: int | None
    status: str | None = None


class AmbiguousYahooPlayerError(ValueError):
    """Signal that a Yahoo player reference matches multiple ranked players."""

    def __init__(
        self,
        chat_pick: YahooDraftChatPick,
        candidates: list[Player],
    ) -> None:
        """Initialize an ambiguity error with the possible ranked players."""
        self.chat_pick = chat_pick
        self.candidates = tuple(candidates)

        candidate_text = ", ".join(
            f"{player.name} (Rank #{player.rank}, ADP {player.adp})" for player in candidates
        )

        super().__init__(
            "Yahoo draft-chat player "
            f'"{chat_pick.player_reference}" '
            f"({chat_pick.position}, {chat_pick.team}) is ambiguous: "
            f"{candidate_text}"
        )


class PotentialYahooPlayerMatchError(ValueError):
    """Signal that an unmatched Yahoo reference has plausible ranked identities."""

    def __init__(
        self,
        chat_pick: YahooDraftChatPick,
        candidates: list[Player],
    ) -> None:
        """Initialize a potential-match error requiring human confirmation."""
        self.chat_pick = chat_pick
        self.candidates = tuple(candidates)

        candidate_text = ", ".join(
            f"{player.name} (Rank #{player.rank}, ADP {player.adp})" for player in candidates
        )

        super().__init__(
            "Yahoo draft-chat player "
            f'"{chat_pick.player_reference}" '
            "has plausible ranked matches that require confirmation: "
            f"{candidate_text}"
        )


class YahooPlayerNotFoundError(ValueError):
    """Signal that no ranked player matches a structurally valid Yahoo selection."""

    def __init__(self, chat_pick: YahooDraftChatPick) -> None:
        """Initialize a no-ranked-identity error for one Yahoo selection."""
        self.chat_pick = chat_pick

        super().__init__(
            "Could not resolve Yahoo draft-chat player "
            f'"{chat_pick.player_reference}" '
            f"({chat_pick.position}, {chat_pick.team})."
        )


def _normalize_line(raw_line: str) -> str:
    line = raw_line.replace("\u00a0", " ").strip()

    if line.startswith("- "):
        line = line[2:].strip()

    if len(line) >= 4 and line.startswith("**") and line.endswith("**"):
        line = line[2:-2].strip()

    return line


def _parse_pick_block(
    overall: int,
    block: list[str],
) -> YahooDraftChatPick | None:
    if len(block) < 4:
        return None

    for position_index in range(2, len(block)):
        position = block[position_index].upper()

        if position not in _POSITIONS:
            continue

        drafter = block[0].strip()
        player_reference = block[1].strip()

        if not drafter or not player_reference:
            return None

        team: str | None
        bye_start_index: int

        if position == "DEF":
            bye_start_index = position_index + 1

            if bye_start_index >= len(block):
                continue

            next_line = block[bye_start_index]
            if next_line != "-" and _BYE_PATTERN.fullmatch(next_line) is None:
                continue

            team = None
        else:
            team_index = position_index + 1

            if team_index >= len(block):
                continue

            team = block[team_index].upper()

            if _TEAM_PATTERN.fullmatch(team) is None:
                continue

            bye_start_index = team_index + 1

        status_parts = [
            line
            for line in block[2:position_index]
            if line != "-" and line.casefold() != player_reference.casefold()
        ]
        status = " ".join(status_parts) or None

        bye: int | None = None

        for line in block[bye_start_index:]:
            bye_match = _BYE_PATTERN.fullmatch(line)

            if bye_match is not None:
                bye = int(bye_match.group(1))
                break

        return YahooDraftChatPick(
            overall=overall,
            drafter=drafter,
            player_reference=player_reference,
            position=position,
            team=team,
            bye=bye,
            status=status,
        )

    return None


def _matches_yahoo_abbreviation(
    reference: str,
    player_name: str,
) -> bool:
    reference_parts = reference.split(" ", maxsplit=1)
    player_parts = player_name.split(" ", maxsplit=1)

    if len(reference_parts) != 2 or len(player_parts) != 2:
        return False

    reference_first, reference_remainder = reference_parts
    player_first, player_remainder = player_parts

    if not reference_first.endswith("."):
        return False

    return (
        reference_first[0].casefold() == player_first[0].casefold()
        and reference_remainder.casefold() == player_remainder.casefold()
    )


def _find_name_matches(
    candidates: list[Player],
    player_reference: str,
) -> list[Player]:
    normalized_reference = player_reference.casefold()

    exact_matches = [
        player for player in candidates if player.name.casefold() == normalized_reference
    ]

    if exact_matches:
        return exact_matches

    return [
        player
        for player in candidates
        if _matches_yahoo_abbreviation(
            player_reference,
            player.name,
        )
    ]


def _normalized_name_parts(name: str) -> tuple[str, str] | None:
    """Return normalized first-name and surname components when both are present."""
    parts = name.split(" ", maxsplit=1)
    if len(parts) != 2:
        return None

    first, surname = parts
    normalized_first = re.sub(r"[^a-z0-9]", "", first.casefold())
    normalized_surname = re.sub(r"[^a-z0-9]", "", surname.casefold())

    if not normalized_first or not normalized_surname:
        return None

    return normalized_first, normalized_surname


def _is_one_edit_apart(left: str, right: str) -> bool:
    """Return whether two normalized strings differ by exactly one basic edit."""
    if left == right or abs(len(left) - len(right)) > 1:
        return False

    if len(left) == len(right):
        differences = sum(
            left_char != right_char for left_char, right_char in zip(left, right, strict=True)
        )
        return differences == 1

    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    short_index = 0
    long_index = 0
    skipped = False

    while short_index < len(shorter) and long_index < len(longer):
        if shorter[short_index] == longer[long_index]:
            short_index += 1
            long_index += 1
            continue

        if skipped:
            return False

        skipped = True
        long_index += 1

    return True


def _find_potential_name_matches(
    candidates: list[Player],
    chat_pick: YahooDraftChatPick,
) -> list[Player]:
    """Return narrowly plausible typo candidates without guessing identity.

    Potential matches must share the reported fantasy position (the caller supplies
    only same-position candidates) and first initial. A candidate is considered
    plausible only when the surname is exact/one basic edit away. Yahoo's NFL-team
    and bye-week metadata only order already-plausible matches; neither is strong enough
    to create one by itself. These candidates require manual confirmation; this helper
    never auto-resolves a player.
    """
    reference_parts = _normalized_name_parts(chat_pick.player_reference)
    if reference_parts is None:
        return []

    reference_first, reference_surname = reference_parts
    potential: list[Player] = []

    for player in candidates:
        player_parts = _normalized_name_parts(player.name)
        if player_parts is None:
            continue

        player_first, player_surname = player_parts
        if reference_first[0] != player_first[0]:
            continue

        surname_is_near = reference_surname == player_surname or _is_one_edit_apart(
            reference_surname, player_surname
        )
        if not surname_is_near:
            continue

        potential.append(player)

    def evidence_order(player: Player) -> tuple[int, int, int, int]:
        player_parts = _normalized_name_parts(player.name)
        if player_parts is None:
            return (1, 1, 1, player.rank)

        _, player_surname = player_parts
        surname_matches = reference_surname == player_surname or _is_one_edit_apart(
            reference_surname, player_surname
        )
        team_matches = (
            chat_pick.team is not None and player.team.casefold() == chat_pick.team.casefold()
        )
        bye_matches = chat_pick.bye is not None and player.bye == chat_pick.bye

        return (
            0 if surname_matches else 1,
            0 if team_matches else 1,
            0 if bye_matches else 1,
            player.rank,
        )

    return sorted(potential, key=evidence_order)


def _find_defense_matches(
    candidates: list[Player],
    player_reference: str,
) -> list[Player]:
    name_matches = _find_name_matches(
        candidates,
        player_reference,
    )

    if name_matches:
        return name_matches

    team = _DEFENSE_TEAM_BY_REFERENCE.get(player_reference.casefold())

    if team is None:
        return []

    return [player for player in candidates if player.team.casefold() == team.casefold()]


def parse_yahoo_draft_chat(text: str) -> list[YahooDraftChatPick]:
    """Parse structurally valid draft selections from copied Yahoo chat text.

    Arbitrary chat messages are ignored rather than classified individually. Numeric
    lines are treated only as possible pick boundaries; the following block must contain
    enough Yahoo draft-selection structure to be accepted as a pick.

    Args:
        text: Raw text copied from the Yahoo draft chat.

    Returns:
        Structurally valid draft selections in the order they appeared.
    """
    lines = [
        normalized for raw_line in text.splitlines() if (normalized := _normalize_line(raw_line))
    ]

    picks: list[YahooDraftChatPick] = []
    index = 0

    while index < len(lines):
        if not lines[index].isdigit():
            index += 1
            continue

        overall = int(lines[index])
        index += 1

        block_start = index

        while index < len(lines) and not lines[index].isdigit():
            index += 1

        parsed = _parse_pick_block(
            overall,
            lines[block_start:index],
        )

        if parsed is not None:
            picks.append(parsed)

    return picks


def resolve_yahoo_chat_player(
    rankings: list[Player],
    chat_pick: YahooDraftChatPick,
    *,
    excluded_yahoo_player_ids: Collection[int] = (),
) -> Player:
    """Resolve a Yahoo draft-chat player against ranked player records.

    Yahoo-reported position and, for individual players, NFL team constrain the
    possible ranked records. Defense selections omit the NFL team-code line in
    Yahoo draft chat, so defense nicknames are resolved to their team identity.
    Bye week is used as an additional discriminator when it produces matching
    candidates. Exact names and Yahoo-style abbreviated names such as ``M. Nabers``
    are supported.

    Previously drafted player IDs may optionally be excluded when resolving a genuinely
    new pick. Callers verifying an overlapping historical pick should not exclude
    already-drafted players.

    Args:
        rankings: Complete ranked player records.
        chat_pick: Parsed Yahoo draft-chat selection.
        excluded_yahoo_player_ids: Player IDs that cannot represent this new selection.

    Returns:
        The uniquely matching ranked player.

    Raises:
        AmbiguousYahooPlayerError: If multiple exact eligible ranked players remain.
        PotentialYahooPlayerMatchError: If only plausible typo candidates remain.
        YahooPlayerNotFoundError: If no exact or plausible ranked player can be resolved.
        ValueError: If matching or plausible ranked identities were already drafted.
    """
    position_candidates = [
        player for player in rankings if player.position.casefold() == chat_pick.position.casefold()
    ]

    if chat_pick.position.casefold() == "def":
        name_matches = _find_defense_matches(
            position_candidates,
            chat_pick.player_reference,
        )
    else:
        name_matches = _find_name_matches(
            position_candidates,
            chat_pick.player_reference,
        )

    if not name_matches:
        potential_matches = _find_potential_name_matches(
            position_candidates,
            chat_pick,
        )
        eligible_potential_matches = [
            player
            for player in potential_matches
            if player.yahoo_player_id not in excluded_yahoo_player_ids
        ]

        if eligible_potential_matches:
            raise PotentialYahooPlayerMatchError(
                chat_pick,
                eligible_potential_matches,
            )

        if potential_matches:
            raise ValueError(
                "All plausible ranked matches for Yahoo draft-chat player "
                f'"{chat_pick.player_reference}" '
                "have already been drafted."
            )

        raise YahooPlayerNotFoundError(chat_pick)

    eligible_matches = [
        player for player in name_matches if player.yahoo_player_id not in excluded_yahoo_player_ids
    ]

    if len(eligible_matches) == 1:
        return eligible_matches[0]

    if not eligible_matches:
        raise ValueError(
            "All players matching Yahoo draft-chat player "
            f'"{chat_pick.player_reference}" '
            "have already been drafted."
        )

    candidates = eligible_matches

    if chat_pick.team is not None:
        team_matches = [
            player for player in candidates if player.team.casefold() == chat_pick.team.casefold()
        ]

        if team_matches:
            candidates = team_matches

    if len(candidates) == 1:
        return candidates[0]

    if chat_pick.bye is not None:
        bye_matches = [player for player in candidates if player.bye == chat_pick.bye]

        if bye_matches:
            candidates = bye_matches

    if len(candidates) == 1:
        return candidates[0]

    raise AmbiguousYahooPlayerError(
        chat_pick,
        candidates,
    )
