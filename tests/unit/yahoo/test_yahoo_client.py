"""Unit tests for the Yahoo Fantasy API client boundary."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fantasy_football_agent.yahoo.yahoo_client import (
    YahooGame,
    YahooOAuth,
    get_game,
    get_oauth,
)

pytestmark = pytest.mark.unit


def test_get_oauth_reuses_valid_token_without_refreshing(
    tmp_path: Path,
) -> None:
    """
    GIVEN: Yahoo OAuth credentials whose current token is still valid
    WHEN: the application creates its OAuth object
    THEN: the token is reused without refreshing or rewriting the credential file
    """
    oauth_file = tmp_path / "oauth2.json"
    oauth = MagicMock(spec=YahooOAuth)
    oauth.token_is_valid.return_value = True

    with patch(
        "fantasy_football_agent.yahoo.yahoo_client.OAuth2",
        return_value=oauth,
    ) as oauth_constructor:
        result = get_oauth(oauth_file)

    assert result is oauth
    oauth_constructor.assert_called_once_with(
        None,
        None,
        from_file=str(oauth_file),
    )
    oauth.token_is_valid.assert_called_once_with()
    oauth.refresh_access_token.assert_not_called()
    oauth.save.assert_not_called()


def test_get_oauth_refreshes_and_saves_expired_token(
    tmp_path: Path,
) -> None:
    """
    GIVEN: Yahoo OAuth credentials whose current token is expired
    WHEN: the application creates its OAuth object
    THEN: the token is refreshed and the updated credentials are saved
    """
    oauth_file = tmp_path / "oauth2.json"
    oauth = MagicMock(spec=YahooOAuth)
    oauth.token_is_valid.return_value = False

    with patch(
        "fantasy_football_agent.yahoo.yahoo_client.OAuth2",
        return_value=oauth,
    ) as oauth_constructor:
        result = get_oauth(oauth_file)

    assert result is oauth
    oauth_constructor.assert_called_once_with(
        None,
        None,
        from_file=str(oauth_file),
    )
    oauth.token_is_valid.assert_called_once_with()
    oauth.refresh_access_token.assert_called_once_with()
    oauth.save.assert_called_once_with(str(oauth_file))


def test_get_game_creates_nfl_game_with_authenticated_oauth(
    tmp_path: Path,
) -> None:
    """
    GIVEN: an OAuth credential path and an authenticated Yahoo OAuth object
    WHEN: the Yahoo Fantasy game client is created
    THEN: the OAuth object is used to construct the NFL game client
    """
    oauth_file = tmp_path / "oauth2.json"
    oauth = MagicMock(spec=YahooOAuth)
    game = MagicMock(spec=YahooGame)

    with (
        patch(
            "fantasy_football_agent.yahoo.yahoo_client.get_oauth",
            return_value=oauth,
        ) as get_oauth_mock,
        patch(
            "fantasy_football_agent.yahoo.yahoo_client.yfa.Game",
            return_value=game,
        ) as game_constructor,
    ):
        result = get_game(oauth_file)

    assert result is game
    get_oauth_mock.assert_called_once_with(oauth_file)
    game_constructor.assert_called_once_with(oauth, "nfl")
