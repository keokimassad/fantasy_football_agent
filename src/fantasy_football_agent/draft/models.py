"""Define the core data models shared by the fantasy draft engine."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DraftStrategyConfig:
    """Represent user-controlled roster-construction targets.

    A position roster target indicates the roster count below which additional
    players at that position receive extra roster-construction consideration.
    Reaching the target does not prevent drafting additional players at that
    position.
    """

    position_roster_targets: dict[str, int]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DraftStrategyConfig":
        """Build draft-strategy settings from JSON-compatible input."""
        return cls(
            position_roster_targets={
                str(position).upper(): int(target)
                for position, target in data["position_roster_targets"].items()
            }
        )


@dataclass
class LeagueConfig:
    """Represent league rules and roster settings that affect draft decisions."""

    league_name: str
    teams: int
    draft: dict[str, Any]
    roster: dict[str, int]
    flex_positions: list[str]
    scoring: dict[str, Any]
    draft_strategy: DraftStrategyConfig

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LeagueConfig":
        """Build a league configuration from its JSON-compatible dictionary form."""
        return cls(
            league_name=data["league_name"],
            teams=data["teams"],
            draft=data["draft"],
            roster=data["roster"],
            flex_positions=data["flex_positions"],
            scoring=data["scoring"],
            draft_strategy=DraftStrategyConfig.from_dict(data["draft_strategy"]),
        )


@dataclass
class DraftPick:
    """Represent one recorded selection in draft order."""

    overall: int
    round: int
    pick_in_round: int
    team_id: int
    player: str
    position: str
    yahoo_player_id: int | None = None


@dataclass
class DraftState:
    """Represent the mutable state of a mock or actual draft session."""

    draft_id: str
    session_type: str
    my_draft_slot: int
    current_overall_pick: int
    picks: list[DraftPick] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DraftState":
        """Reconstruct draft state, including recorded picks, from serialized data."""
        picks = [DraftPick(**pick) for pick in data.get("picks", [])]

        return cls(
            draft_id=data["draft_id"],
            session_type=data["session_type"],
            my_draft_slot=data["my_draft_slot"],
            current_overall_pick=data["current_overall_pick"],
            picks=picks,
        )


@dataclass
class Player:
    """Represent a ranked player and the draft-market metadata used for analysis."""

    rank: int
    adp: float | None
    name: str
    position: str
    team: str
    bye: int
    drafted_percentage: float | None
    yahoo_player_id: int
    manual_tier: int | None


@dataclass
class TeamLookaheadContext:
    """Describe one team's selections and roster needs in a lookahead window."""

    pick_count: int
    overall_picks: list[int]
    open_starter_slots: dict[str, int]


@dataclass
class PositionExposure:
    """Summarize opponent demand for a position during a lookahead window."""

    direct_need_teams: list[int]
    flex_only_teams: list[int]
    selection_chances: int
