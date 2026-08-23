# Fantasy Football Agent

A Python 3.12 fantasy-football draft assistant that keeps draft state, roster accounting,
tier analysis, and pick lookahead deterministic while isolating Yahoo Fantasy integration
behind a small external-service boundary.

The current project is deliberately **deterministic first**. The draft engine owns factual
state and calculations; a future agent/LLM layer can reason over those results without
becoming the source of truth for draft order, roster state, or player availability.

## What It Does

- Loads and validates league configuration and persisted draft state.
- Models snake-draft ownership, including round turns.
- Tracks rosters and open starter slots, including FLEX overflow.
- Loads ranked players and identifies which players remain available.
- Calculates tier depth, tier drops, scarcity flags, and tier coverage.
- Builds active lookahead windows between the current pick and the user's next turn.
- Estimates position exposure from opponents drafting inside that window.
- Records draft picks locally and supports undo.
- Authenticates to Yahoo Fantasy through a dedicated OAuth/client boundary.
- Exposes draft analysis and state updates through command-line entry points.

## Architecture

```text
Future agent / LLM
        |
        | reasoning and recommendations
        v
Deterministic draft engine
        |
        | draft order, roster accounting, availability,
        | tiers, lookahead, persistence
        v
Yahoo integration boundary
        |
        | authentication / external league data
        v
Yahoo Fantasy
```

The design intentionally keeps Yahoo-specific code out of the draft engine. That makes the
core logic testable without network access and leaves room for other data sources later.

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
│       ├── application_paths.py
│       ├── cli/
│       │   ├── draft_analyzer.py
│       │   └── draft_updater.py
│       ├── draft/
│       │   ├── analysis.py
│       │   ├── models.py
│       │   ├── rankings.py
│       │   ├── session.py
│       │   └── state.py
│       └── yahoo/
│           ├── yahoo_client.py
│           └── yahoo_config.py
├── tests/
├── tools/
│   └── check_test_docstrings.py
├── .pre-commit-config.yaml
├── pyproject.toml
└── README.md
```

Local runtime files such as `oauth2.json`, the active league configuration, current draft
state, and full ranking data are intentionally ignored by Git.

## Setup

Create and activate a Python 3.12 virtual environment:

```bash
python -m venv venv
source venv/bin/activate
```

Install the project and development tooling:

```bash
python -m pip install -e ".[dev]"
```

Create local working copies of the example inputs:

```bash
cp config/league.example.json config/league.json
cp data/draft_state.example.json data/draft_state.json
cp data/yahoo_rankings.example.csv data/yahoo_rankings_2026.csv
```

Replace the example values with the league settings, draft session, and ranking data you
intend to use. The ranking CSV schema is:

```text
Rank,ADP,Player Name,Position,Team,Bye,% Drafted,Yahoo Player ID,Manual - Tier
```

`Yahoo Player ID` is the preferred stable identity when available. `Manual - Tier` is
optional and can be populated as tiers are assigned.

## Starting a Draft Session

Create a fresh mock draft:

```bash
ff-draft-new --type mock --slot 4 --workspace .
```

Create the real league draft once your actual draft slot is known:

```bash
ff-draft-new --type actual --slot <YOUR_SLOT> --workspace .
```

A readable timestamp-based draft ID is generated automatically. An explicit ID may
instead be supplied with `--draft-id`.

The command will not overwrite an existing active `draft_state.json` unless
`--replace` is explicitly supplied:

```bash
ff-draft-new --type mock --slot 7 --replace --workspace .
```

Draft rankings, manual tiers, and league configuration are not reset when a new
draft session is created.

## Draft Analysis

Run the analyzer from the workspace containing `config/` and `data/`:

```bash
ff-draft --workspace .
```

The report includes the current draft position, roster state, available ranked players,
tier/scarcity information, the active snake-draft lookahead window, and opponent position
exposure before the user's next pick.

Because the workspace is explicit, the installed package does not need to infer a Git
repository root.

## Recording Picks

Record one or more selections by player name or Yahoo Player ID:

```bash
ff-draft-update "Player Name" --workspace .
```

```bash
ff-draft-update 12345 "Another Player" --workspace .
```

With no player arguments, the updater prompts interactively until a blank line is entered:

```bash
ff-draft-update --workspace .
```

Undo the most recently recorded pick:

```bash
ff-draft-update --undo --workspace .
```

Successful picks are persisted immediately so an error resolving a later player does not
discard earlier updates.

## Yahoo OAuth

Yahoo integration is optional for the deterministic draft engine.

Create a local `oauth2.json` in the workspace root:

```json
{
  "consumer_key": "YOUR_YAHOO_CLIENT_ID",
  "consumer_secret": "YOUR_YAHOO_CLIENT_SECRET"
}
```

The file is intentionally ignored by Git. Never commit an access token, refresh token,
Client Secret, `.env`, or `oauth2.json`.

OAuth path precedence is:

```text
explicit path
    ↓
YAHOO_OAUTH_FILE
    ↓
<workspace>/oauth2.json
```

The Yahoo client loads the credential file, reuses a valid token, and refreshes and saves
an expired token when necessary.

To exercise the Yahoo connection boundary manually:

```bash
python scripts/check_yahoo_connection.py
```

This is an external integration check and requires valid Yahoo credentials and Fantasy
Sports API access.

## Quality Gates

The project uses:

- Ruff for linting and formatting.
- strict mypy for static typing.
- pytest for deterministic unit tests.
- pytest-cov with branch coverage.
- a small AST-based checker that requires test docstrings to document `GIVEN:`, `WHEN:`,
  and `THEN:` behavior.
- pre-commit for fast local checks.
- GitHub Actions for the complete CI gate.

Install the Git hook once per clone:

```bash
python -m pre_commit install
```

Run the local pre-commit checks manually:

```bash
python -m pre_commit run --all-files
```

Run the full test and coverage gate:

```bash
python -m pytest \
  --cov=fantasy_football_agent \
  --cov-branch \
  --cov-report=term-missing
```

The repository currently enforces a minimum of 90% branch-aware coverage. The threshold is
intentionally below 100% so coverage does not incentivize low-value tests of trivial
launcher boilerplate.

## Testing Philosophy

Tests focus on public behavior and meaningful boundaries rather than reproducing
implementation details. Important cases include:

- snake-draft turns and ownership;
- roster/FLEX accounting;
- tier boundaries and scarcity;
- player identity and duplicate-draft protection;
- state persistence and undo;
- CLI orchestration;
- OAuth refresh behavior without live network calls.

Unit tests do not require Yahoo credentials or network access.

## Data and Privacy

The repository contains only sanitized example inputs. Real league settings, current draft
state, raw Yahoo settings, OAuth credentials, and full Yahoo-derived ranking datasets
should remain local.

If you use ranking or league data from an external provider, make sure you are authorized
to store and redistribute that data. The project code does not require a particular
ranking provider as long as the local CSV follows the documented schema.

## Roadmap

The deterministic engine is the foundation for the next layer of the project. Planned
work includes:

1. richer Yahoo league-data ingestion;
2. recommendation models that consume deterministic draft state;
3. between-pick opponent/survival analysis;
4. an agent layer that explains and compares draft choices while leaving state and
   calculations deterministic.

The guiding rule remains the same: **the agent may reason about draft state, but it should
not invent draft state.**
