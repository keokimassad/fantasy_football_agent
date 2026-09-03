"""Load explicit local corrections for stale draft-market data."""

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .models import AdpPolicy, Player


@dataclass(frozen=True)
class PlayerMarketOverride:
    """Represent one audited local correction to player market metadata."""

    yahoo_player_id: int
    adp_policy: AdpPolicy
    reason: str
    as_of: str
    adp: float | None = None


def _parse_override(raw: dict[str, Any]) -> PlayerMarketOverride:
    """Parse and validate one JSON player override record."""
    try:
        yahoo_player_id = int(raw["yahoo_player_id"])
        adp_policy = AdpPolicy(str(raw["adp_policy"]).upper())
        reason = str(raw["reason"]).strip()
        as_of = str(raw["as_of"]).strip()
    except KeyError as error:
        raise ValueError(f"Missing player override field: {error.args[0]}") from error
    except ValueError as error:
        raise ValueError("Invalid player override value.") from error

    if not reason:
        raise ValueError("Player override reason must not be blank.")
    if not as_of:
        raise ValueError("Player override as_of must not be blank.")

    adp_value = raw.get("adp")
    adp = None if adp_value is None else float(adp_value)

    if adp_policy == AdpPolicy.OVERRIDE and adp is None:
        raise ValueError("ADP OVERRIDE policy requires an adp value.")

    return PlayerMarketOverride(
        yahoo_player_id=yahoo_player_id,
        adp_policy=adp_policy,
        reason=reason,
        as_of=as_of,
        adp=adp,
    )


def load_player_market_overrides(path: str | Path) -> dict[int, PlayerMarketOverride]:
    """Load player-market overrides, returning an empty mapping when absent."""
    path = Path(path)
    if not path.exists():
        return {}

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("players"), list):
        raise ValueError("Player override file must contain a top-level players list.")

    overrides: dict[int, PlayerMarketOverride] = {}
    for raw in payload["players"]:
        if not isinstance(raw, dict):
            raise ValueError("Each player override must be a JSON object.")

        override = _parse_override(raw)
        if override.yahoo_player_id in overrides:
            raise ValueError(
                f"Duplicate player override for Yahoo Player ID {override.yahoo_player_id}."
            )
        overrides[override.yahoo_player_id] = override

    return overrides


def apply_player_market_overrides(
    players: list[Player],
    overrides: dict[int, PlayerMarketOverride],
) -> list[Player]:
    """Return players with effective ADP adjusted by explicit local policy."""
    adjusted: list[Player] = []

    for player in players:
        override = overrides.get(player.yahoo_player_id)
        if override is None:
            adjusted.append(player)
            continue

        effective_adp = player.source_adp
        if override.adp_policy == AdpPolicy.IGNORE:
            effective_adp = None
        elif override.adp_policy == AdpPolicy.OVERRIDE:
            effective_adp = override.adp

        adjusted.append(
            replace(
                player,
                adp=effective_adp,
                adp_policy=override.adp_policy,
                adp_override_reason=override.reason,
                adp_override_as_of=override.as_of,
            )
        )

    return adjusted
