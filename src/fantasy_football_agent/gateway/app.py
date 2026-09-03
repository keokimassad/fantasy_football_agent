"""Serve deterministic fantasy-draft decision context through a read-only HTTP API."""

import argparse
import os
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from fantasy_football_agent.application_paths import ApplicationPaths
from fantasy_football_agent.draft.decision_packet import DraftDecisionPacket
from fantasy_football_agent.draft.sync_status import DraftStateStaleError
from fantasy_football_agent.gateway.service import build_current_decision_packet

DEFAULT_GATEWAY_HOST = "127.0.0.1"
DEFAULT_GATEWAY_PORT = 8000
GATEWAY_API_KEY_ENV = "FANTASY_AGENT_GATEWAY_API_KEY"

DecisionPacketProvider = Callable[[], DraftDecisionPacket]


@dataclass(frozen=True)
class GatewaySettings:
    """Collect runtime settings for the read-only decision gateway."""

    workspace: Path
    api_key: str
    host: str = DEFAULT_GATEWAY_HOST
    port: int = DEFAULT_GATEWAY_PORT
    public_url: str | None = None


@dataclass(frozen=True)
class HealthResponse:
    """Describe basic gateway liveness without exposing draft information."""

    status: str


def _require_bearer_token(
    expected_api_key: str,
) -> Callable[[HTTPAuthorizationCredentials | None], None]:
    """Build a FastAPI dependency that protects draft data with a bearer secret."""
    bearer = HTTPBearer(auto_error=False)

    def require_token(
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Depends(bearer),
        ],
    ) -> None:
        if credentials is None or not secrets.compare_digest(
            credentials.credentials,
            expected_api_key,
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing gateway API key.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return require_token


def create_app(
    *,
    packet_provider: DecisionPacketProvider,
    api_key: str,
    public_url: str | None = None,
) -> FastAPI:
    """Create the read-only API consumed by a private Custom GPT Action.

    Args:
        packet_provider: Callable returning the latest deterministic decision packet.
        api_key: Secret bearer token required for draft-data requests.
        public_url: Optional external HTTPS base URL included in the OpenAPI schema.

    Returns:
        A configured FastAPI application with health and decision endpoints.

    Raises:
        ValueError: If the API key is too short or the public URL is not HTTPS.
    """
    api_key = api_key.strip()
    if len(api_key) < 32:
        raise ValueError("Gateway API key must contain at least 32 characters.")
    if public_url is not None and not public_url.startswith("https://"):
        raise ValueError("Gateway public URL must use HTTPS.")

    servers = None if public_url is None else [{"url": public_url.rstrip("/")}]
    app = FastAPI(
        title="Fantasy Football Draft Decision Gateway",
        version="0.1.0",
        description=(
            "Read-only deterministic fantasy-draft context for a private ChatGPT Action. "
            "This API does not mutate draft state."
        ),
        servers=servers,
    )
    require_token = _require_bearer_token(api_key)

    @app.get(
        "/health",
        operation_id="getGatewayHealth",
        response_model=HealthResponse,
        tags=["health"],
    )
    def get_health() -> HealthResponse:
        """Return gateway liveness without exposing draft or roster data."""
        return HealthResponse(status="ok")

    @app.get(
        "/v1/draft/decision",
        operation_id="getDraftDecision",
        response_model=DraftDecisionPacket,
        dependencies=[Depends(require_token)],
        tags=["draft"],
    )
    def get_draft_decision() -> DraftDecisionPacket:
        """Return the latest deterministic draft decision packet."""
        try:
            return packet_provider()
        except DraftStateStaleError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Draft state is stale because Yahoo synchronization failed: "
                    f"{error.failure.message}"
                ),
            ) from error

    return app


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse gateway command-line settings while keeping secrets out of shell history."""
    parser = argparse.ArgumentParser(
        description="Serve the local deterministic draft decision packet over HTTP.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Directory containing the config and data directories.",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_GATEWAY_HOST,
        help="Local interface to bind. Keep 127.0.0.1 when using a secure tunnel.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_GATEWAY_PORT,
        help="Local TCP port for the read-only gateway.",
    )
    parser.add_argument(
        "--public-url",
        help="Optional public HTTPS base URL to include in the generated OpenAPI schema.",
    )
    return parser.parse_args(argv)


def _settings_from_environment_and_args(args: argparse.Namespace) -> GatewaySettings:
    """Resolve non-secret CLI settings and the required API key environment variable."""
    api_key = os.environ.get(GATEWAY_API_KEY_ENV, "").strip()
    if not api_key:
        raise ValueError(f"Set {GATEWAY_API_KEY_ENV} before starting the decision gateway.")
    if args.port < 1 or args.port > 65535:
        raise ValueError("Gateway port must be between 1 and 65535.")

    return GatewaySettings(
        workspace=args.workspace.resolve(),
        api_key=api_key,
        host=args.host,
        port=args.port,
        public_url=args.public_url,
    )


def main(argv: Sequence[str] | None = None) -> None:
    """Start the local read-only decision gateway."""
    args = _parse_args(argv)
    settings = _settings_from_environment_and_args(args)
    paths = ApplicationPaths(workspace=settings.workspace)

    app = create_app(
        packet_provider=lambda: build_current_decision_packet(paths),
        api_key=settings.api_key,
        public_url=settings.public_url,
    )
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
    )
