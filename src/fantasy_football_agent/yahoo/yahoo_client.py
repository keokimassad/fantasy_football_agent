"""Create authenticated Yahoo Fantasy API objects for the application."""

from pathlib import Path
from typing import Protocol, cast

import yahoo_fantasy_api as yfa
from yahoo_oauth import OAuth2


class YahooOAuth(Protocol):
    """Operations the application relies on from Yahoo OAuth."""

    def token_is_valid(self) -> bool:
        """Return whether the current OAuth token is valid."""

    def refresh_access_token(self) -> None:
        """Refresh the current OAuth access token."""

    def save(self, filename: str) -> None:
        """Persist the current OAuth credentials."""


class YahooGame(Protocol):
    """Yahoo Fantasy game operations used by the application."""

    def league_ids(self) -> list[str]:
        """Return league IDs associated with the authenticated account."""


def get_oauth(oauth_file: Path) -> YahooOAuth:
    """Create Yahoo OAuth credentials and refresh them when necessary."""
    oauth = cast(
        YahooOAuth,
        OAuth2(
            None,
            None,
            from_file=str(oauth_file),
        ),
    )

    if not oauth.token_is_valid():
        oauth.refresh_access_token()
        oauth.save(str(oauth_file))

    return oauth


def get_game(oauth_file: Path) -> YahooGame:
    """Create an authenticated Yahoo Fantasy Football game client."""
    game = yfa.Game(
        get_oauth(oauth_file),
        "nfl",
    )

    return cast(YahooGame, game)
