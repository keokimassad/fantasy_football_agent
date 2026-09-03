"""Resolve workspace-relative files used by the application."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ApplicationPaths:
    """Collect the files the application expects to find in a workspace.

    Keeping these paths in one place prevents the installed package from depending on
    the repository's location. A caller only needs to choose a workspace; the rest of
    the application can work with explicit paths from this object.
    """

    workspace: Path

    @property
    def league_config(self) -> Path:
        """Return the league configuration file for this workspace."""
        return self.workspace / "config" / "league.json"

    @property
    def draft_state(self) -> Path:
        """Return the persisted draft-state file for this workspace."""
        return self.workspace / "data" / "draft_state.json"

    @property
    def rankings(self) -> Path:
        """Return the Yahoo rankings CSV used by the draft engine."""
        return self.workspace / "data" / "yahoo_rankings_2026.csv"

    @property
    def player_overrides(self) -> Path:
        """Return the optional local player-market override file."""
        return self.workspace / "data" / "player_overrides.json"

    @property
    def yahoo_oauth(self) -> Path:
        """Return the workspace's default Yahoo OAuth credential file."""
        return self.workspace / "oauth2.json"
