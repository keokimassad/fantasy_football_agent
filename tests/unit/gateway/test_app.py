"""Unit tests for the read-only Custom GPT decision gateway."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from fantasy_football_agent.draft.decision_packet import (
    DraftDecisionPacket,
    build_draft_decision_packet,
)
from fantasy_football_agent.draft.models import DraftState, LeagueConfig, Player
from fantasy_football_agent.draft.recommendations import evaluate_candidates
from fantasy_football_agent.draft.sync_status import DraftStateStaleError, DraftSyncFailure
from fantasy_football_agent.gateway.app import create_app

pytestmark = pytest.mark.unit


def _packet_provider(
    league_config: LeagueConfig,
    make_draft_state: Callable[..., DraftState],
    make_player: Callable[..., Player],
) -> Callable[[], DraftDecisionPacket]:
    """Return a stable deterministic packet provider for HTTP-layer tests."""
    state = make_draft_state(my_draft_slot=4, current_overall_pick=4)
    player = make_player(
        rank=4,
        adp=4.0,
        name="Gateway Candidate",
        position="WR",
        yahoo_player_id=23004,
    )
    packet = build_draft_decision_packet(
        evaluate_candidates([player], state, league_config),
        state,
        league_config,
    )
    return lambda: packet


def test_health_endpoint_is_public_and_contains_no_draft_data(
    league_config: LeagueConfig,
    make_draft_state: Callable[..., DraftState],
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: a configured read-only gateway
    WHEN: an unauthenticated client requests the health endpoint
    THEN: liveness is returned without requiring or exposing draft information
    """
    app = create_app(
        packet_provider=_packet_provider(
            league_config,
            make_draft_state,
            make_player,
        ),
        api_key="t" * 32,
    )

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_decision_endpoint_rejects_missing_or_invalid_bearer_token(
    league_config: LeagueConfig,
    make_draft_state: Callable[..., DraftState],
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: a decision endpoint protected by a configured bearer secret
    WHEN: clients omit the secret or provide the wrong value
    THEN: the gateway refuses to expose draft context
    """
    app = create_app(
        packet_provider=_packet_provider(
            league_config,
            make_draft_state,
            make_player,
        ),
        api_key="t" * 32,
    )
    client = TestClient(app)

    missing = client.get("/v1/draft/decision")
    invalid = client.get(
        "/v1/draft/decision",
        headers={"Authorization": f"Bearer {'w' * 32}"},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_decision_endpoint_returns_deterministic_packet_for_valid_token(
    league_config: LeagueConfig,
    make_draft_state: Callable[..., DraftState],
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: a client with the configured bearer secret
    WHEN: the client requests the current draft decision
    THEN: the API returns the versioned deterministic packet without mutating state
    """
    app = create_app(
        packet_provider=_packet_provider(
            league_config,
            make_draft_state,
            make_player,
        ),
        api_key="t" * 32,
    )

    response = TestClient(app).get(
        "/v1/draft/decision",
        headers={"Authorization": f"Bearer {'t' * 32}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == 2
    assert payload["context"]["phase"] == "ON_CLOCK"
    assert payload["candidates"][0]["name"] == "Gateway Candidate"


def test_decision_endpoint_returns_conflict_when_draft_state_is_stale() -> None:
    """
    GIVEN: the packet provider knows Yahoo synchronization left draft state stale
    WHEN: an authenticated client requests a draft decision
    THEN: the gateway returns conflict instead of a stale recommendation packet
    """
    failure = DraftSyncFailure(
        draft_id="mock-stale",
        message="Draft gap detected.",
        local_current_overall_pick=7,
        observed_yahoo_pick=11,
    )

    def stale_provider() -> DraftDecisionPacket:
        raise DraftStateStaleError(failure)

    app = create_app(
        packet_provider=stale_provider,
        api_key="t" * 32,
    )

    response = TestClient(app).get(
        "/v1/draft/decision",
        headers={"Authorization": f"Bearer {'t' * 32}"},
    )

    assert response.status_code == 409
    assert "Draft state is stale" in response.json()["detail"]
    assert "Draft gap detected" in response.json()["detail"]


def test_openapi_schema_exposes_only_read_operations_and_bearer_auth(
    league_config: LeagueConfig,
    make_draft_state: Callable[..., DraftState],
    make_player: Callable[..., Player],
) -> None:
    """
    GIVEN: a gateway configured with its public HTTPS base URL
    WHEN: the OpenAPI schema is generated for a Custom GPT Action
    THEN: it advertises read-only operations, the public server, and bearer authentication
    """
    app = create_app(
        packet_provider=_packet_provider(
            league_config,
            make_draft_state,
            make_player,
        ),
        api_key="t" * 32,
        public_url="https://draft.example.test/",
    )

    schema = TestClient(app).get("/openapi.json").json()

    assert schema["servers"] == [{"url": "https://draft.example.test"}]
    assert set(schema["paths"]["/v1/draft/decision"]) == {"get"}
    assert set(schema["paths"]["/health"]) == {"get"}
    decision_operation = schema["paths"]["/v1/draft/decision"]["get"]
    assert decision_operation["operationId"] == "getDraftDecision"
    assert decision_operation["security"]
    assert schema["components"]["securitySchemes"]


def test_gateway_rejects_blank_api_key() -> None:
    """
    GIVEN: no usable bearer secret
    WHEN: the gateway application is created
    THEN: startup configuration is rejected before any draft endpoint can be served
    """
    with pytest.raises(ValueError, match="at least 32 characters"):
        create_app(
            packet_provider=lambda: pytest.fail("provider should not be called"),
            api_key="too-short",
        )


def test_gateway_rejects_non_https_public_url() -> None:
    """
    GIVEN: an external base URL that does not use HTTPS
    WHEN: the gateway application is created for an Action schema
    THEN: configuration fails before an insecure public server is advertised
    """
    with pytest.raises(ValueError, match="public URL must use HTTPS"):
        create_app(
            packet_provider=lambda: pytest.fail("provider should not be called"),
            api_key="t" * 32,
            public_url="http://draft.example.test",
        )
