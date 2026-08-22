"""Resolve Yahoo-specific configuration without coupling it to package location."""

import os
from pathlib import Path

from fantasy_football_agent.application_paths import ApplicationPaths


def resolve_yahoo_oauth_file(
    paths: ApplicationPaths,
    explicit_path: Path | None = None,
) -> Path:
    """Resolve the Yahoo OAuth credential file using a predictable precedence order.

    An explicitly supplied path wins first, followed by the ``YAHOO_OAUTH_FILE``
    environment variable. If neither is provided, the workspace's default
    ``oauth2.json`` path is used. Explicit and environment paths are expanded and
    resolved so downstream Yahoo code receives a concrete filesystem location.
    """
    if explicit_path is not None:
        return explicit_path.expanduser().resolve()

    environment_path = os.getenv("YAHOO_OAUTH_FILE")

    if environment_path:
        return Path(environment_path).expanduser().resolve()

    return paths.yahoo_oauth
