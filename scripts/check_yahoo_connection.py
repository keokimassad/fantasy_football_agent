"""Perform a manual Yahoo Fantasy authentication and league lookup check."""

from pathlib import Path

from fantasy_football_agent.application_paths import ApplicationPaths
from fantasy_football_agent.yahoo.yahoo_client import get_game
from fantasy_football_agent.yahoo.yahoo_config import resolve_yahoo_oauth_file

paths = ApplicationPaths(workspace=Path.cwd().resolve())

oauth_file = resolve_yahoo_oauth_file(paths)

game = get_game(oauth_file)

print("OAuth successful")
print("Fantasy football leagues:")
print(game.league_ids())
