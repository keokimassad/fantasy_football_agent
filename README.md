# Fantasy Football Agent

A Python 3.12 fantasy-football draft assistant built around a deterministic-first architecture.

The project keeps draft state, player availability, roster accounting, tier analysis, pick
lookahead, opponent exposure, and candidate recommendations deterministic and testable.
Yahoo Fantasy is treated as an integration boundary, while future news/context and AI layers
will reason over structured outputs rather than owning factual draft state.

## Core Principle

> **The agent may reason about draft state, but it should not invent draft state.**

The deterministic engine remains the source of truth for:

- draft order;
- player availability;
- roster construction;
- persisted selections;
- tier evidence;
- pick windows;
- opponent exposure;
- recommendation evidence.

Future AI functionality will consume those results rather than recreate them.

## Current Capabilities

- Load and validate league configuration and persisted draft state.
- Model snake-draft ownership, including turn picks.
- Track rosters and open starter slots, including FLEX overflow.
- Apply configurable soft roster targets by position to identify meaningful bench-depth needs.
- Load Yahoo-derived rankings with:
  - Yahoo rank;
  - ADP;
  - player name;
  - position;
  - team;
  - bye;
  - drafted percentage;
  - Yahoo Player ID;
  - manual tier.
- Determine available players using Yahoo Player ID as the preferred stable identity.
- Calculate:
  - tier depth;
  - next position tier;
  - last-in-tier conditions;
  - tier drops;
  - scarcity flags;
  - tier coverage.
- Build draft lookahead windows between the current pick and future user picks.
- Estimate opponent position exposure inside those windows.
- Evaluate candidates deterministically.
- Produce a compact top-five deterministic decision-support shortlist for the user.
- Build a versioned, JSON-compatible `DraftDecisionPacket` that exposes broader structured
  deterministic evidence for a downstream AI agent.
- Distinguish:
  - cross-position candidate desirability;
  - roster fit;
  - roster utility;
  - position depth need;
  - availability risk while waiting for the next pick;
  - return risk while on the clock;
  - loss cost;
  - decision urgency.
- Render phase-aware shortlists for waiting and on-clock states.
- Keep raw opponent position exposure as descriptive evidence rather than selection probability.
- Record draft picks locally.
- Undo the most recent pick.
- Parse copied Yahoo Draft Chat selections.
- Safely reconcile overlapping Yahoo draft history.
- Detect synchronization gaps and conflicts.
- Surface ambiguous Yahoo player identities instead of guessing.
- Authenticate to Yahoo Fantasy through a dedicated OAuth/client boundary.
- Expose the workflow through installable CLI commands.

## Architecture

```text
Yahoo Draft Chat / future Yahoo API
              |
              | observed selections
              v
          DraftState
              |
              | availability, roster accounting, tiers,
              | snake order, pick windows, opponent exposure
              v
      CandidateEvaluation
              |
              +-------------------------------+
              |                               |
              v                               v
   Waiting for my pick                  On the clock
   - desirability                       - desirability
   - availability risk                  - roster utility
   - pre-decision pressure              - loss cost
                                        - return risk
                                        - urgency
              |                               |
              +---------------+---------------+
                              v
                 Deterministic shortlist
                              |
                              v
             Future news context + AI agent
```

Yahoo-specific code remains outside the core draft engine so deterministic behavior can be
tested without network access. The recommendation layer is phase-aware: waiting mode helps
prepare for the next decision, while on-clock mode helps decide whether to take a player or
risk waiting until the following pick.

### AI Decision Packet Boundary

`draft.decision_packet` now provides the deterministic boundary that a future recommendation
agent will consume. It deliberately sits downstream of candidate evaluation and recommendation
logic instead of asking a model to reconstruct facts from terminal output.

The packet includes:

- factual league, draft, roster, starter-slot, and remaining-capacity context;
- the user's current decision pick and actual following pick when one exists;
- a broader ordered candidate set than the five names rendered for human review;
- typed market, tier, roster-fit, roster-utility, depth-need, scarcity, risk, urgency, and
  explanation evidence for each candidate;
- a schema version and JSON-compatible dictionary representation for a stable model boundary.

The packet does **not** contain model-generated conclusions. The future AI layer will reason
over this deterministic evidence while the top-five shortlist remains the manual fallback.

The initial AI integration target is a private Custom GPT Action backed by a read-only HTTPS
gateway that exposes this packet. Keep the draft domain layer model-provider-independent: the
core engine should not depend on an LLM SDK, and the gateway should not be allowed to mutate
or reconstruct factual draft state.

## Recommendation Model

The recommendation layer intentionally keeps player value, roster construction, scarcity,
and timing as separate concepts.

### Candidate Desirability

Describes whether a player is a plausible cross-position selection in the current draft
window.

Yahoo rank and ADP jointly define the deterministic cross-position market window. When
both are available, the engine uses their midpoint as a transparent market-consensus
estimate so neither source owns the desirability boundary by itself. A substantially later
market candidate still cannot leap the board solely because that player is scarce.

### Roster Fit

Describes where a candidate can fit on the current roster:

- `DIRECT_STARTER`
- `FLEX`
- `DEPTH`

### Roster Utility

Describes how useful that roster fit is **right now**.

For example, a second TE may technically fit in FLEX, but its immediate roster utility can
be lower while dedicated RB or WR starter slots remain open.

### Position Depth Need

Describes whether a `DEPTH` candidate helps fill a configured roster-construction target:

- `HIGH` — the roster is at least two players below the position target;
- `MEDIUM` — the roster is one player below the position target;
- `LOW` — the configured position target has been reached;
- `NOT_APPLICABLE` — the candidate is not currently a depth fit.

Position roster targets are **soft targets, not roster caps**. Reaching a target does not
prevent or prohibit another player at that position. Instead, the target provides
roster-construction context when otherwise-plausible candidates have comparable market value.

Needed bench depth can raise immediate roster utility from `LOW` to `MEDIUM`, but it does not
become `HIGH` solely because a position is below target. Market-consensus desirability remains
the cross-position guardrail.

### Availability Risk

Used while the user is **waiting for the next pick**.

It estimates whether a candidate is likely to survive until the user's decision pick using
Yahoo rank and ADP as independent market signals.

Waiting-mode output is preparation rather than a claim that the player is currently
selectable. Within the same position and decision band, better manual-tier quality can break
a close market-ordering tie; manual tiers are not compared across positions. Signals therefore
use language such as:

- `VALUE_IF_AVAILABLE_AT_DECISION`
- `PRE_DECISION_POSITION_PRESSURE`

The engine does not emit `FALLEN_PAST_ADP` before the user is actually on the clock.

### Return Risk

Used when the user is **on the clock**.

It estimates whether a player is likely to disappear before the user's following pick.
Yahoo rank and ADP provide independent market-timing evidence. On-clock ordering gives
immediate roster utility precedence over scarcity when otherwise-plausible candidates compete,
so a high-utility direct starter is not displaced by a low-utility FLEX option solely because
the FLEX option is scarce.

Raw opponent position exposure remains visible as deterministic context, but generic
exposure is **not treated as selection probability**. An opponent having an open QB slot is
not equivalent to predicting that the opponent will draft a QB.

### Loss Cost

Estimates how costly it would be if a player disappeared.

Inputs include:

- roster fit;
- `LAST_IN_TIER`;
- known next-tier information;
- large tier drops;
- whether the candidate is still in the best currently available manual tier at that
  position.

A last player in a worse tier does not become a high-loss candidate while clearly better
tiers remain available at the same position. Loss cost describes replacement pain; it does
not independently redefine cross-position player value.

### Decision Urgency

The internal decision-priority classification is presented to the user as **Urgency**.
Urgency answers how strongly the current evidence argues against waiting; it is not the
same as overall player desirability.

### Manual Tiers

Manual tiers remain **position-relative**.

A Tier 1 RB is not assumed to have the same universal value as a Tier 1 WR. The engine does
not convert tiers into an arbitrary cross-position numerical score. Instead, it tracks how
far a candidate's tier trails the best currently available tier **at that same position**.
That position-relative gap can break close recommendation ties and prevents singleton
scarcity in a worse tier from masquerading as premium value.

Yahoo rank and ADP jointly provide the cross-position market baseline.

### Draft Boundary

Lookahead is bounded by the configured final overall pick. Once a manager has no remaining
selection inside that boundary, the engine reports that explicitly instead of inventing the
next mathematical snake turn. This keeps late-round exposure and recommendation horizons
inside the actual draft.

## Project Structure

```text
fantasy_football_agent/
├── .github/
│   └── workflows/
│       └── ci.yml
├── config/
│   └── league.example.json
├── data/
│   ├── draft_state.example.json
│   └── yahoo_rankings.example.csv
├── scripts/
│   └── check_yahoo_connection.py
├── src/
│   └── fantasy_football_agent/
│       ├── __init__.py
│       ├── application_paths.py
│       ├── py.typed
│       ├── cli/
│       │   ├── __init__.py
│       │   ├── draft_analyzer.py
│       │   ├── draft_creator.py
│       │   └── draft_updater.py
│       ├── draft/
│       │   ├── __init__.py
│       │   ├── analysis.py
│       │   ├── models.py
│       │   ├── rankings.py
│       │   ├── recommendations.py
│       │   ├── session.py
│       │   └── state.py
│       └── yahoo/
│           ├── __init__.py
│           ├── draft_chat.py
│           ├── draft_sync.py
│           ├── yahoo_client.py
│           └── yahoo_config.py
├── tests/
├── tools/
│   └── check_test_docstrings.py
├── .gitignore
├── .pre-commit-config.yaml
├── DEVELOPMENT.md
├── pyproject.toml
└── README.md
```

Local/private files such as real league configuration, current draft state, full rankings,
raw Yahoo data, and OAuth credentials are intentionally excluded from Git.

## Setup

Create and activate a Python 3.12 environment:

```bash
python -m venv venv
source venv/bin/activate
```

Install the project in editable mode with development dependencies:

```bash
python -m pip install -e ".[dev]"
```

Create local working copies of the example inputs:

```bash
cp config/league.example.json config/league.json
cp data/draft_state.example.json data/draft_state.json
cp data/yahoo_rankings.example.csv data/yahoo_rankings_2026.csv
```

The ranking CSV schema is:

```text
Rank,ADP,Player Name,Position,Team,Bye,% Drafted,Yahoo Player ID,Manual - Tier
```

League configuration also includes soft draft-strategy targets, for example:

```json
"draft_strategy": {
  "position_roster_targets": {
    "QB": 1,
    "RB": 4,
    "WR": 4,
    "TE": 1,
    "K": 1,
    "DEF": 1
  }
}
```

These values describe when additional depth should receive extra roster-construction
consideration. They do not prevent drafting beyond the target.

## CLI Commands

The installed entry points are:

```text
ff-draft
ff-draft-update
ff-draft-new
ff-gateway
```

### Create a Draft Session

Create a mock session after Yahoo reveals the slot:

```bash
ff-draft-new --type mock --slot <SLOT> --workspace .
```

Create the actual league session once the real slot is known:

```bash
ff-draft-new --type actual --slot <SLOT> --workspace .
```

Replace an existing active session explicitly:

```bash
ff-draft-new   --type mock   --slot <SLOT>   --replace   --workspace .
```

A custom draft ID may be supplied with `--draft-id`.

## Read-Only Custom GPT Gateway

The optional gateway exposes the current `DraftDecisionPacket` through a small read-only
HTTP API. It is the intended Action boundary for the initial private Custom GPT integration;
it does not call an LLM and it has no write endpoint.

Install only the gateway runtime when development tooling is not needed:

```bash
python -m pip install -e ".[gateway]"
```

Set the bearer secret in the environment rather than putting it in source control, a `.env`
file, or shell history. On macOS, store the development secret once in the login Keychain:

```bash
export FANTASY_AGENT_GATEWAY_API_KEY="$(
  python -c 'import secrets; print(secrets.token_urlsafe(32))'
)"
security add-generic-password \
  -a "$USER" \
  -s "fantasy_football_agent_gateway" \
  -w "$FANTASY_AGENT_GATEWAY_API_KEY" \
  -U
unset FANTASY_AGENT_GATEWAY_API_KEY
```

The Keychain item persists across terminal sessions and computer reboots. The environment
variable does not. Load the secret independently in every terminal that needs it:

```bash
export FANTASY_AGENT_GATEWAY_API_KEY="$(
  security find-generic-password \
    -a "$USER" \
    -s "fantasy_football_agent_gateway" \
    -w
)"
ff-gateway --workspace .
```

The server binds to `127.0.0.1:8000` by default so it is not directly exposed to the local
network. A later deployment/tunnel layer can provide the public HTTPS URL required by the
Custom GPT Action without changing the deterministic draft engine.

Read-only routes:

```text
GET /health                public liveness only
GET /v1/draft/decision     bearer-authenticated DraftDecisionPacket
GET /openapi.json          generated OpenAPI action schema
```

If a stable public URL is known when the gateway starts, include it in the generated schema:

```bash
ff-gateway --workspace . --public-url https://<public-host>
```

The Action should configure the same bearer secret separately. Never place Yahoo OAuth
credentials, the gateway secret, or other private credentials in the OpenAPI schema.

Local smoke test from a second terminal after loading the same Keychain secret there:

```bash
curl http://127.0.0.1:8000/health
curl \
  -H "Authorization: Bearer $FANTASY_AGENT_GATEWAY_API_KEY" \
  http://127.0.0.1:8000/v1/draft/decision
curl http://127.0.0.1:8000/openapi.json \
  -o /tmp/fantasy-agent-openapi.json
```

After testing, remove only the per-shell copy with
`unset FANTASY_AGENT_GATEWAY_API_KEY`; the Keychain copy remains available for future sessions.
Rotate the Keychain value by generating a new secret and repeating `security add-generic-password`
with `-U`. Delete it completely with:

```bash
security delete-generic-password \
  -a "$USER" \
  -s "fantasy_football_agent_gateway"
```

### Public HTTPS development tunnel

The current development path uses ngrok to expose the local read-only gateway over HTTPS.
The tunnel is transport only: deterministic draft state and recommendation logic remain local.

Install ngrok on macOS:

```bash
brew install ngrok
ngrok version
```

Store the ngrok account authtoken in macOS Keychain rather than committing it or placing it in
project configuration. One-time setup:

```bash
read -s NGROK_AUTHTOKEN
security add-generic-password \
  -a "$USER" \
  -s "fantasy_football_agent_ngrok" \
  -w "$NGROK_AUTHTOKEN" \
  -U
unset NGROK_AUTHTOKEN
```

For each new tunnel shell, load the token and start ngrok:

```bash
export NGROK_AUTHTOKEN="$(
  security find-generic-password \
    -a "$USER" \
    -s "fantasy_football_agent_ngrok" \
    -w
)"
ngrok http 8000
```

Copy the HTTPS forwarding URL shown by ngrok, then restart the gateway with that exact URL so the
generated OpenAPI document advertises the public Action server:

```bash
export FANTASY_AGENT_GATEWAY_API_KEY="$(
  security find-generic-password \
    -a "$USER" \
    -s "fantasy_football_agent_gateway" \
    -w
)"
ff-gateway --workspace . --public-url https://<assigned-host>.ngrok-free.dev
```

Validate the public boundary before configuring ChatGPT:

```bash
curl https://<assigned-host>.ngrok-free.dev/health

curl -i \
  https://<assigned-host>.ngrok-free.dev/v1/draft/decision

curl \
  -H "Authorization: Bearer $FANTASY_AGENT_GATEWAY_API_KEY" \
  https://<assigned-host>.ngrok-free.dev/v1/draft/decision

curl -s \
  https://<assigned-host>.ngrok-free.dev/openapi.json \
  | python -c '
import json, sys
schema = json.load(sys.stdin)
print("OpenAPI:", schema["openapi"])
print("Servers:", schema.get("servers"))
print("Paths:", list(schema["paths"]))
print("Security:", schema["paths"]["/v1/draft/decision"]["get"].get("security"))
'
```

Expected behavior is public `200` for `/health`, `401` for an unauthenticated decision request,
`200` for an authenticated decision request, and an OpenAPI server URL matching the ngrok HTTPS
host. Keep both `ff-gateway` and ngrok running while the Custom GPT Action is in use.

### Private Custom GPT Action

Create a private Custom GPT Action using:

- authentication: API Key;
- auth type: Bearer;
- API key: the same gateway bearer secret stored in macOS Keychain;
- schema URL: `https://<assigned-host>.ngrok-free.dev/openapi.json`.

The imported schema should expose `getGatewayHealth` and `getDraftDecision`. Keep the GPT private
during development. The exact reasoning contract used by the GPT is documented in
`CUSTOM_GPT_INSTRUCTIONS.md`.

The validated Action path is:

```text
Custom GPT
    ↓ HTTPS + Bearer
ngrok development tunnel
    ↓
local FastAPI gateway
    ↓
DraftDecisionPacket
    ↓
deterministic draft engine
```

Validation should cover all three packet phases:

- `WAITING`: identify future targets and risks without telling the user to draft immediately;
- `ON_CLOCK`: provide a recommendation, alternatives, tradeoffs, wait risk, and confidence;
- `COMPLETE`: state that the draft is complete and provide no new pick recommendation.

## Yahoo Draft-Chat Synchronization

Copy a recent Yahoo Draft Chat selection range and pipe the clipboard into the updater:

```bash
pbpaste | ff-draft-update --yahoo-chat --workspace .
```

The synchronizer:

- ignores arbitrary non-selection chat;
- verifies matching overlapping history;
- records the next expected selections;
- persists successful picks incrementally;
- stops on gaps or conflicts;
- resolves exact player identities from ranking data;
- prompts when Yahoo abbreviations are genuinely ambiguous.

Using a recent overlapping range is intentional. Already-recorded selections can be safely
verified before new picks are added.

## Draft Analysis

Run:

```bash
ff-draft --workspace .
```

The first section is phase-aware.

While waiting for the next pick:

```text
Decision prep shortlist for pick #5:
  1. Candidate | RB T1 | Desirability HIGH | Availability risk HIGH
     Rank #1 | ADP 1.5 | Fit DIRECT_STARTER | Roster utility HIGH
     Tier left 3 | Next T2
     Why: FILLS_DIRECT_STARTER, VALUE_IF_AVAILABLE_AT_DECISION,
          PRE_DECISION_POSITION_PRESSURE
```

When on the clock:

```text
Deterministic shortlist:
  1. Candidate | WR T3 | Desirability HIGH | Urgency HIGH
     Rank #38 | ADP 43.3 | Fit DIRECT_STARTER | Roster utility HIGH
     Loss cost HIGH | Return risk MEDIUM
     Tier left 1 | Next T4
     Why: FILLS_DIRECT_STARTER, LAST_IN_TIER,
          RETURN_WINDOW_POSITION_PRESSURE
```

The detailed report also includes:

- draft/session metadata;
- the user's roster;
- top available players;
- tier scarcity;
- tier coverage;
- team roster construction;
- open starter slots;
- active lookahead;
- opponent lookahead;
- raw position exposure in the relevant pick window.

## Manual Draft Updates

Record a player manually:

```bash
ff-draft-update "Player Name" --workspace .
```

Record by Yahoo Player ID:

```bash
ff-draft-update 12345 --workspace .
```

Run interactively:

```bash
ff-draft-update --workspace .
```

Undo the most recent pick:

```bash
ff-draft-update --undo --workspace .
```

## Fast macOS Mock Workflow

A small shell helper can synchronize copied Yahoo chat and immediately rerun analysis:

```bash
ffmock() {
  pbpaste | ff-draft-update --yahoo-chat --workspace .
  ff-draft --workspace .
}
```

Typical mock workflow:

1. wait until Yahoo reveals the mock slot;
2. create a fresh mock session with that exact slot;
3. before any selections exist, run `ff-draft --workspace .` to inspect decision prep;
4. once selections exist, copy a recent overlapping Yahoo Draft Chat range;
5. run `ffmock`;
6. verify `Current overall pick` matches Yahoo;
7. while waiting, review `Decision prep shortlist for pick #X`;
8. when on the clock, review `Deterministic shortlist`;
9. repeat before upcoming selections and again on the clock when useful.

Create or replace the current mock with:

```bash
ff-draft-new \
  --type mock \
  --slot <YAHOO_MOCK_SLOT> \
  --replace \
  --workspace .
```

If synchronization reports a gap, copy a larger overlapping range. If it reports a
conflict, stop and reconcile the state rather than forcing an update.

## Yahoo OAuth

Yahoo API access is optional for the copied-chat workflow.

A local workspace-level `oauth2.json` may contain:

```json
{
  "consumer_key": "YOUR_YAHOO_CLIENT_ID",
  "consumer_secret": "YOUR_YAHOO_CLIENT_SECRET"
}
```

Never commit OAuth credentials, access tokens, refresh tokens, client secrets, `.env`, or
real private league data.

OAuth path precedence is:

```text
explicit path
    ↓
YAHOO_OAUTH_FILE
    ↓
<workspace>/oauth2.json
```

A manual Yahoo connectivity check is available:

```bash
python scripts/check_yahoo_connection.py
```

## Quality Gates

The project uses:

- Ruff;
- strict mypy;
- pytest;
- pytest-cov with branch coverage;
- behavioral test docstrings;
- pre-commit;
- GitHub Actions.

Install pre-commit once per clone:

```bash
python -m pre_commit install
```

Run all configured hooks:

```bash
python -m pre_commit run --all-files
```

Run the full local quality gate:

```bash
python -m ruff format --check src tests scripts tools
python -m ruff check src tests scripts tools
python -m mypy src tests
python tools/check_test_docstrings.py
python -m pytest   --cov=fantasy_football_agent   --cov-branch   --cov-report=term-missing
```

The project enforces a minimum of 90% branch-aware coverage.

Exact test counts and coverage percentages are intentionally not documented here because
they change as the project evolves.

## Testing Philosophy

Tests focus on meaningful behavior rather than coverage for its own sake.

Important areas include:

- snake-draft ownership;
- roster/FLEX accounting;
- tier boundaries;
- player availability;
- two-horizon candidate evaluation;
- waiting-vs-on-clock phase detection;
- candidate desirability;
- roster fit;
- roster utility;
- position depth need and soft roster targets;
- availability risk;
- return risk;
- loss cost;
- urgency;
- cross-position market guardrails;
- recommendation ordering;
- Yahoo draft-chat parsing;
- ambiguity handling;
- overlap verification;
- gap/conflict detection;
- persistence;
- undo;
- OAuth refresh behavior without live network calls.

## Data and Privacy

The repository should contain sanitized example data only.

Keep the following local:

- `config/league.json`
- `data/draft_state.json`
- `data/yahoo_rankings_2026.csv`
- `data/raw/`
- `oauth2.json`

If external ranking or league data is used, ensure that storage and redistribution comply
with the provider's terms.

## Roadmap

The deterministic recommendation layer is now phase-aware, position-depth-aware, and uses
Rank/ADP market consensus plus position-relative tier quality. The rendered top five are a
compact decision set rather than an autonomous final-pick decision.

Next priorities:

1. run a final acceptance mock using the Sunday league configuration and confirm live-clock
   timing/fallback behavior;
2. improve local manual-tier coverage for realistically draftable wide receivers;
3. run additional AI-assisted mocks through the validated private Custom GPT Action and compare
   AI choices with the deterministic evidence packet;
4. harden deterministic fallback and model/action failure behavior under the live draft clock;
5. refine the compact live-draft UX and add timestamped recent-news/injury context;
6. evaluate richer Yahoo API ingestion when available;
7. consider specialized multi-agent roles only if they add measurable value.

The core rule remains:

> **The agent may reason about draft state, but it should not invent draft state.**
